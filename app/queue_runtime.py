from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.main import app, db, task_manager, settings, security, network_manager
from app.csrf_middleware import CSRFSecurityMiddleware
from app.project_access import ProjectAccessMiddleware
from app.persistent_queue import PersistentTaskQueue
from app.queue_worker import PersistentQueueWorker
from app.kill_switch import KillSwitch
from app.security_headers import SecurityHeadersMiddleware
from app.network_policy import NetworkPolicyManager
from app.security import SecurityManager


queue = PersistentTaskQueue(settings.database_path)
kill_switch = KillSwitch(settings.database_path)
network_policy = NetworkPolicyManager(db, security, network_manager)
_original_run = task_manager.run
_original_enqueue = task_manager.enqueue


async def _verify_network_for_card(work_card_id: int) -> bool:
    card = db.get_work_card(work_card_id)
    if not card:
        return False
    project_id = card.get("project_id")
    if project_id is None:
        return True
    policy = network_policy.get(int(project_id))
    if policy is None:
        return True
    result = await network_policy.verify_project(int(project_id))
    if result.get("allowed"):
        return True
    if not policy.fail_closed:
        try:
            db.create_event(
                event_type="network_policy_warning",
                message="فشل تحقق سياسة الشبكة لكن fail_closed غير مفعّل.",
                project_id=int(project_id),
                metadata={"work_card_id": work_card_id, "reason": result.get("reason")},
            )
        except Exception:
            pass
        return True
    try:
        db.create_event(
            event_type="network_execution_blocked",
            message="تم منع تنفيذ المهمة بسبب فشل سياسة الشبكة.",
            project_id=int(project_id),
            metadata={"work_card_id": work_card_id, "reason": result.get("reason")},
        )
    except Exception:
        pass
    return False


async def _queue_run(work_card_id: int) -> bool:
    """Public execution entrypoint: persist first, execute via the worker."""
    if kill_switch.is_active() or not await _verify_network_for_card(work_card_id):
        return False
    card = db.get_work_card(work_card_id)
    if not card:
        return False
    status = str(card.get("status", "")).lower()
    if status in {"needs_approval", "completed", "stopped", "error"}:
        return False
    return bool(queue.enqueue(work_card_id, {"work_card_id": work_card_id}))


async def _queue_enqueue(work_card_id: int) -> bool:
    if kill_switch.is_active() or not await _verify_network_for_card(work_card_id):
        return False
    accepted = await _original_enqueue(work_card_id)
    if not accepted:
        return False
    return bool(queue.enqueue(work_card_id, {"work_card_id": work_card_id}))


class _ExecutionGate:
    """Keep the durable worker behind the same fail-safe gates."""

    def __init__(self, manager, gate: KillSwitch) -> None:
        self._manager = manager
        self._gate = gate
        self.db = manager.db

    async def run(self, work_card_id: int) -> bool:
        if self._gate.is_active() or not await _verify_network_for_card(work_card_id):
            return False
        return bool(await self._manager.run(work_card_id))


task_manager.run = _queue_run  # type: ignore[method-assign]
task_manager.enqueue = _queue_enqueue  # type: ignore[method-assign]
execution_manager = _ExecutionGate(SimpleNamespace(run=_original_run, db=db), kill_switch)
worker = PersistentQueueWorker(queue, execution_manager)


async def _sync_queued_cards() -> None:
    for card in db.list_all_work_cards():
        if str(card.get("status", "")).lower() != "queued":
            continue
        card_id = int(card["id"])
        item = queue.get(card_id)
        if item is None or item.get("status") in {"failed", "cancelled"}:
            queue.enqueue(card_id, {"work_card_id": card_id})


async def _require_control_session(request: Request) -> str:
    """Reuse the application's authenticated admin session boundary."""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="جلسة الدخول غير صالحة أو منتهية.")
    from app.main import _require_session
    return _require_session(request)


@app.get("/api/control/kill-switch", dependencies=[Depends(_require_control_session)])
async def kill_switch_status() -> JSONResponse:
    return JSONResponse({"ok": True, **kill_switch.status()})


@app.post("/api/control/kill-switch", dependencies=[Depends(_require_control_session)])
async def engage_kill_switch(request: Request) -> JSONResponse:
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    reason = str(payload.get("reason", "manual_kill_switch"))[:500]

    state = kill_switch.engage(reason)
    stopped = 0
    for card in db.list_all_work_cards():
        if str(card.get("status", "")).lower() == "running":
            try:
                if await task_manager.stop(int(card["id"])):
                    stopped += 1
            except Exception:
                continue

    try:
        db.create_event(
            event_type="kill_switch_engaged",
            message=f"تم تفعيل مفتاح الإيقاف: {reason}",
            metadata={"reason": reason, "stopped_tasks": stopped},
        )
    except Exception:
        pass

    return JSONResponse({"ok": True, **state, "stopped_tasks": stopped})


@app.post("/api/control/kill-switch/release", dependencies=[Depends(_require_control_session)])
async def release_kill_switch(request: Request) -> JSONResponse:
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if payload.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="يجب تأكيد إعادة تشغيل الأتمتة.")

    state = kill_switch.release()
    try:
        db.create_event(
            event_type="kill_switch_released",
            message="تم إلغاء مفتاح الإيقاف وإعادة السماح بالتنفيذ.",
        )
    except Exception:
        pass
    return JSONResponse({"ok": True, **state})


_original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan(application):
    async with _original_lifespan(application):
        await _sync_queued_cards()
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()


app.router.lifespan_context = _lifespan
app.add_middleware(ProjectAccessMiddleware, database=db)
app.add_middleware(SecurityHeadersMiddleware)

if settings.app_env.lower() == "production" and not settings.csrf_secret:
    raise RuntimeError("CSRF_SECRET must be configured in production")
if settings.csrf_secret:
    app.add_middleware(CSRFSecurityMiddleware, secret=settings.csrf_secret)
