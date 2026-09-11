from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import Agent
from app.auth_compat import PersistentSessionSet
from app.approval import ApprovalManager
from app.browser import BrowserManager
from app.code_analyzer import CodeAnalyzer
from app.config import settings
from app.connectivity import ConnectivityMonitor
from app.database import Database
from app.notifications import NotificationManager
from app.network import NetworkManager, NetworkProfile
from app.security import SecurityManager
from app.rate_limit import LoginRateLimiter
from app.task_manager import TaskManager


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"


# ================================================================
# الخدمات الأساسية
# ================================================================

db = Database(settings.database_path)

security = SecurityManager(settings)

network_manager = NetworkManager(
    database=db,
    security=security,
)

agent = Agent(
    database=db,
    settings=settings,
)

approval_manager = ApprovalManager(db)

browser = BrowserManager(
    settings=settings,
    database=db,
)

notifications = NotificationManager(
    settings=settings,
)

code_analyzer = CodeAnalyzer()

connectivity = ConnectivityMonitor(
    check_url=settings.connectivity_check_url,
    interval=settings.connectivity_interval,
)

task_manager = TaskManager(
    database=db,
    browser=browser,
    agent=agent,
    notifications=notifications,
    settings=settings,
    connectivity=connectivity,
)


_active_sessions = PersistentSessionSet()
_login_rate_limiter = LoginRateLimiter(
    settings.database_path,
    max_failures=5,
    window_seconds=300,
)


# ================================================================
# نماذج الطلبات
# ================================================================

class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    project_id: Optional[int] = None




class WorkCardActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=50)
    note: str = Field(default="", max_length=2000)


class BrowserOpenRequest(BaseModel):
    project_id: int
    site: str = Field(min_length=1, max_length=2000)
    url: Optional[str] = Field(default=None, max_length=2000)
    network_profile: Optional[str] = Field(default=None, max_length=80)


class NetworkProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    mode: str = Field(default="direct", max_length=20)
    proxy_server: str = Field(default="", max_length=500)
    username: str = Field(default="", max_length=200)
    password: str = Field(default="", max_length=500)
    bypass: str = Field(default="", max_length=1000)


class NetworkTestRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)

class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    workflow_type: str = Field(default="assistant", max_length=50)

class BrowserNavigateRequest(BaseModel):
    project_id: int
    url: str = Field(min_length=1, max_length=2000)


class BrowserClickRequest(BaseModel):
    project_id: int
    selector: str = Field(min_length=1, max_length=2000)


class BrowserFillRequest(BaseModel):
    project_id: int
    selector: str = Field(min_length=1, max_length=2000)
    value: str = Field(max_length=10000)


class SecretPanelRequest(BaseModel):
    password: str = Field(min_length=1)


# ================================================================
# المصادقة
# ================================================================

def _cookie_secure() -> bool:
    return settings.app_env.lower() == "production"


def _verify_admin_password(password: str) -> bool:
    configured = settings.admin_password

    if not configured:
        return False

    return security.secure_compare(
        password,
        configured,
    )


def _get_session_from_request(
    request: Request,
) -> Optional[str]:
    return request.cookies.get("session")


def _require_session(
    request: Request,
) -> str:
    token = _get_session_from_request(request)

    if not token or token not in _active_sessions:
        raise HTTPException(
            status_code=401,
            detail="جلسة الدخول غير صالحة أو منتهية.",
        )

    return token


# ================================================================
# الاتصال بالإنترنت
# ================================================================

async def _handle_offline() -> None:
    try:
        await task_manager.handle_offline()
    except Exception:
        pass

    try:
        db.create_event(
            event_type="connection_lost",
            message=(
                "انقطع اتصال الإنترنت. "
                "تم إيقاف الأعمال الجارية مؤقتاً."
            ),
        )
    except Exception:
        pass

    try:
        await notifications.send_offline()
    except Exception:
        pass


async def _handle_online() -> None:
    try:
        await task_manager.handle_online()
    except Exception:
        pass

    try:
        db.create_event(
            event_type="connection_restored",
            message=(
                "عاد اتصال الإنترنت. "
                "تم استئناف الأعمال المتوقفة."
            ),
        )
    except Exception:
        pass

    try:
        await notifications.send_restored()
    except Exception:
        pass


# ================================================================
# دورة حياة التطبيق
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    settings.ensure_directories()

    db.initialize()

    try:
        _active_sessions.purge()
    except Exception:
        pass

    try:
        await browser.initialize()
    except Exception:
        # عدم تشغيل المتصفح لا يمنع تشغيل لوحة التحكم.
        pass

    connectivity.on_offline(_handle_offline)
    connectivity.on_online(_handle_online)

    try:
        await connectivity.start()
    except Exception:
        pass

    try:
        yield
    finally:

        try:
            await task_manager.shutdown()
        except Exception:
            pass

        try:
            await connectivity.stop()
        except Exception:
            pass

        try:
            await browser.shutdown()
        except Exception:
            pass


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug,
    lifespan=lifespan,
)


if STATIC_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(
            directory=str(STATIC_DIR)
        ),
        name="static",
    )


# ================================================================
# الصفحات
# ================================================================

@app.get("/")
async def root():
    return RedirectResponse(
        url="/dashboard",
        status_code=307,
    )


@app.get("/login")
async def login_page():
    return FileResponse(
        FRONTEND_DIR / "login.html"
    )


@app.get("/dashboard")
async def dashboard(
    request: Request,
):
    session = _get_session_from_request(request)

    if (
        not session
        or session not in _active_sessions
    ):
        return RedirectResponse(
            url="/login",
            status_code=307,
        )

    return FileResponse(
        FRONTEND_DIR / "index.html"
    )


# ================================================================
# الصحة
# ================================================================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "online": connectivity.is_online,
        "app": settings.app_name,
        "browser": {
            "initialized": browser._playwright is not None,
        },
    }


@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "online": connectivity.is_online,
        "browser_initialized": (
            browser._playwright is not None
        ),
    }


# ================================================================
# تسجيل الدخول
# ================================================================

@app.post("/api/login")
async def login(
    request: LoginRequest,
    http_request: Request,
):
    client_key = (
        http_request.client.host
        if http_request.client
        else "unknown"
    )

    allowed, retry_after = _login_rate_limiter.check(client_key)
    if not allowed:
        try:
            db.create_event(
                event_type="security_login_rate_limited",
                message="تم رفض محاولة دخول بسبب تجاوز حد المحاولات.",
                metadata={
                    "client_key": client_key,
                    "retry_after": retry_after,
                },
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=429,
            detail="تم تجاوز عدد محاولات الدخول. حاول لاحقاً.",
            headers={"Retry-After": str(retry_after)},
        )

    if not _verify_admin_password(
        request.password
    ):
        _, remaining = _login_rate_limiter.record_failure(client_key)
        try:
            db.create_event(
                event_type="security_login_failed",
                message="فشلت محاولة تسجيل دخول.",
                metadata={
                    "client_key": client_key,
                    "remaining_attempts": remaining,
                },
            )
        except Exception:
            pass
        if remaining == 0:
            raise HTTPException(
                status_code=429,
                detail="تم تجاوز عدد محاولات الدخول. حاول لاحقاً.",
                headers={"Retry-After": "300"},
            )
        raise HTTPException(
            status_code=401,
            detail="كلمة المرور غير صحيحة.",
        )

    _login_rate_limiter.record_success(client_key)

    token = security.generate_session_token()

    _active_sessions.add(token)

    response = JSONResponse(
        {
            "success": True,
            "message": "تم تسجيل الدخول بنجاح.",
        }
    )

    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=86400,
        path="/",
    )

    try:
        db.create_event(
            event_type="info",
            message="تم تسجيل دخول جديد إلى لوحة التحكم.",
        )
    except Exception:
        pass

    return response


@app.post("/api/logout")
async def logout(
    session: str = Depends(_require_session),
):
    _active_sessions.discard(session)

    response = JSONResponse(
        {
            "success": True,
            "message": "تم تسجيل الخروج.",
        }
    )

    response.delete_cookie(
        key="session",
        path="/",
    )

    return response


# ================================================================
# المشاريع
# ================================================================

@app.get("/api/projects")
async def list_projects(
    _: str = Depends(_require_session),
):
    return {
        "projects": db.list_projects(),
    }


@app.post("/api/projects")
async def create_project(
    request: ProjectCreateRequest,
    _: str = Depends(_require_session),
):
    project = db.create_project(
        name=request.name,
        description=request.description,
        workflow_type=request.workflow_type,
    )

    return {
        "success": True,
        "project": project,
    }


@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    _: str = Depends(_require_session),
):
    project = db.get_project(project_id)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود.",
        )

    return {
        "project": project,
    }


@app.delete("/api/projects/{project_id}")
async def delete_project(
    project_id: int,
    _: str = Depends(_require_session),
):
    project = db.get_project(project_id)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود.",
        )

    db.delete_project(project_id)

    return {
        "success": True,
        "message": "تم حذف المشروع.",
    }


# ================================================================
# المحادثة والوكيل
# ================================================================

@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    _: str = Depends(_require_session),
):
    result = await agent.chat(
        message=request.message,
        project_id=request.project_id,
    )

    return {
        "success": True,
        "response": result,
    }


@app.get("/api/chat/{project_id}")
async def project_chat(
    project_id: int,
    _: str = Depends(_require_session),
):
    project = db.get_project(project_id)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود.",
        )

    return {
        "messages": db.list_chat_messages(
            project_id
        ),
    }


# ================================================================
# بطاقات العمل
# ================================================================

@app.get("/api/work-cards")
async def list_work_cards(
    project_id: Optional[int] = None,
    _: str = Depends(_require_session),
):

    if project_id is not None:
        cards = db.list_work_cards(
            project_id
        )
    else:
        cards = db.list_all_work_cards()

    return {
        "work_cards": cards,
    }


@app.get("/api/work-cards/{card_id}")
async def get_work_card(
    card_id: int,
    _: str = Depends(_require_session),
):
    card = db.get_work_card(card_id)

    if not card:
        raise HTTPException(
            status_code=404,
            detail="بطاقة العمل غير موجودة.",
        )

    return {
        "work_card": card,
    }


@app.post("/api/work-cards/{card_id}/action")
async def work_card_action(
    card_id: int,
    request: WorkCardActionRequest,
    _: str = Depends(_require_session),
):
    action = request.action.strip().lower()

    if action not in ApprovalManager.ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail="إجراء غير صالح.",
        )

    card = db.get_work_card(card_id)

    if not card:
        raise HTTPException(
            status_code=404,
            detail="بطاقة العمل غير موجودة.",
        )

    try:

        # --------------------------------------------------------
        # الموافقة
        # --------------------------------------------------------

        if action == "approve":

            approved = await task_manager.approve(
                card_id
            )

            if not approved:
                raise HTTPException(
                    status_code=400,
                    detail="تعذر اعتماد المهمة.",
                )

            started = await task_manager.run(
                card_id
            )

            return {
                "success": True,
                "approved": True,
                "started": started,
                "work_card": db.get_work_card(
                    card_id
                ),
            }

        # --------------------------------------------------------
        # الرفض
        # --------------------------------------------------------

        if action == "reject":

            # مهم:
            # ApprovalManager.reject() متزامنة.
            result = approval_manager.reject(
                card_id=card_id,
                note=request.note,
            )

            return {
                "success": bool(result),
                "result": result,
                "work_card": db.get_work_card(
                    card_id
                ),
            }

        # --------------------------------------------------------
        # إيقاف مؤقت
        # --------------------------------------------------------

        if action == "pause":

            result = await task_manager.pause(
                work_card_id=card_id,
                reason=(
                    request.note
                    or "manual_pause"
                ),
            )

            return {
                "success": bool(result),
                "result": result,
                "work_card": db.get_work_card(
                    card_id
                ),
            }

        # --------------------------------------------------------
        # استئناف
        # --------------------------------------------------------

        if action == "resume":

            result = await task_manager.resume(
                card_id
            )

            return {
                "success": bool(result),
                "result": result,
                "work_card": db.get_work_card(
                    card_id
                ),
            }

        # --------------------------------------------------------
        # إيقاف
        # --------------------------------------------------------

        if action == "stop":

            result = await task_manager.stop(
                work_card_id=card_id,
                reason=(
                    request.note
                    or "manual_stop"
                ),
            )

            return {
                "success": bool(result),
                "result": result,
                "work_card": db.get_work_card(
                    card_id
                ),
            }

        raise HTTPException(
            status_code=400,
            detail="إجراء غير مدعوم.",
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ================================================================
# الموافقات
# ================================================================

@app.get("/api/approvals")
async def list_approvals(
    _: str = Depends(_require_session),
):
    return {
        "approvals": approval_manager.list_pending(),
    }


# ================================================================
# المتصفح
# ================================================================

@app.post("/api/browser/open")
async def browser_open(
    request: BrowserOpenRequest,
    _: str = Depends(_require_session),
):
    result = await browser.open(
        project_id=request.project_id,
        site=request.site,
        url=request.url,
        network_profile=request.network_profile,
    )

    return {
        "success": True,
        "result": result,
    }


@app.post("/api/browser/navigate")
async def browser_navigate(
    request: BrowserNavigateRequest,
    _: str = Depends(_require_session),
):
    result = await browser.navigate(
        project_id=request.project_id,
        url=request.url,
    )

    return {
        "success": True,
        "result": result,
    }


@app.post("/api/browser/click")
async def browser_click(
    request: BrowserClickRequest,
    _: str = Depends(_require_session),
):
    result = await browser.click(
        project_id=request.project_id,
        selector=request.selector,
    )

    return {
        "success": True,
        "result": result,
    }


@app.post("/api/browser/fill")
async def browser_fill(
    request: BrowserFillRequest,
    _: str = Depends(_require_session),
):
    result = await browser.fill(
        project_id=request.project_id,
        selector=request.selector,
        value=request.value,
    )

    return {
        "success": True,
        "result": result,
    }


@app.post("/api/browser/close/{project_id}")
async def browser_close(
    project_id: int,
    _: str = Depends(_require_session),
):
    result = await browser.close(
        project_id=project_id,
    )

    return {
        "success": True,
        "result": result,
    }


# ================================================================
# الشبكة
# ================================================================

@app.get("/api/network/profiles")
async def network_profiles(
    _: str = Depends(_require_session),
):
    return {
        "profiles": network_manager.list_profiles(),
    }


@app.post("/api/network/profiles")
async def create_network_profile(
    request: NetworkProfileRequest,
    _: str = Depends(_require_session),
):
    profile = NetworkProfile(
        name=request.name,
        mode=request.mode,
        proxy_server=request.proxy_server,
        username=request.username,
        password=request.password,
        bypass=request.bypass,
    )

    network_manager.save_profile(profile)

    return {
        "success": True,
        "profile": {
            "name": profile.name,
            "mode": profile.mode,
            "proxy_server": profile.proxy_server,
        },
    }


@app.post("/api/network/test")
async def test_network_profile(
    request: NetworkTestRequest,
    _: str = Depends(_require_session),
):
    result = await network_manager.test_connectivity(
        request.name
    )

    return {
        "success": True,
        "result": result,
    }


# ================================================================
# секретات
# ================================================================

@app.post("/api/secrets/unlock")
async def unlock_secrets(
    request: SecretPanelRequest,
    _: str = Depends(_require_session),
):
    if not _verify_admin_password(
        request.password
    ):
        raise HTTPException(
            status_code=401,
            detail="كلمة المرور غير صحيحة.",
        )

    return {
        "success": True,
        "message": "تم فتح لوحة الأسرار.",
    }


# ================================================================
# رفع الملفات
# ================================================================

@app.post("/api/uploads")
async def upload_file(
    file: UploadFile = File(...),
    _: str = Depends(_require_session),
):
    content = await file.read()

    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=413,
            detail="حجم الملف أكبر من الحد المسموح.",
        )

    filename = file.filename or "upload.bin"

    path = settings.upload_dir / filename
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_bytes(content)

    record = db.save_uploaded_file(
        filename=filename,
        path=str(path),
        size=len(content),
        content_type=file.content_type or "application/octet-stream",
    )

    return {
        "success": True,
        "file": record,
    }


# ================================================================
# معلومات النظام
# ================================================================

@app.get("/api/system/status")
async def system_status(
    _: str = Depends(_require_session),
):
    return {
        "app": settings.app_name,
        "environment": settings.app_env,
        "debug": settings.debug,
        "online": connectivity.is_online,
        "browser_initialized": browser._playwright is not None,
        "projects": len(db.list_projects()),
        "work_cards": len(db.list_all_work_cards()),
        "pending_approvals": len(approval_manager.list_pending()),
    }
