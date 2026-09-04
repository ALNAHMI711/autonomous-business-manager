from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Cookie, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent import Agent
from app.approval import ApprovalManager
from app.browser import BrowserManager
from app.code_analyzer import CodeAnalyzer
from app.config import get_settings
from app.connectivity import ConnectivityMonitor
from app.database import Database
from app.models import ApprovalAction, WorkStatus, WorkflowType
from app.notifications import NotificationManager
from app.security import PasswordHasher, SecretBox
from app.task_manager import TaskManager


settings = get_settings()
database = Database(settings.database_path)

agent = Agent(database)
browser = BrowserManager(database)
notifications = NotificationManager(database)
approvals = ApprovalManager(database)
code_analyzer = CodeAnalyzer()
secret_box = SecretBox(settings.encryption_key)

task_manager = TaskManager(
    database=database,
    agent=agent,
    browser=browser,
    notifications=notifications,
    approvals=approvals,
)

connectivity = ConnectivityMonitor(database)

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
)

frontend_dir = Path("frontend")
static_dir = frontend_dir / "static"

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ---------------------------------------------------------------------
# Session handling
# ---------------------------------------------------------------------

_active_sessions: set[str] = set()


def _verify_admin_password(password: str) -> bool:
    """
    Supports the current local setup where ADMIN_PASSWORD may be plain text,
    while also supporting the secure PBKDF2 format produced by PasswordHasher.
    """

    configured = settings.admin_password or ""

    if not configured:
        return False

    if configured.startswith("pbkdf2_sha256$"):
        return PasswordHasher.verify_password(password, configured)

    return secrets.compare_digest(password, configured)


def _require_session(session: Optional[str]) -> None:
    if not session or session not in _active_sessions:
        raise HTTPException(
            status_code=401,
            detail="جلسة غير صالحة أو منتهية",
        )


def _cookie_secure() -> bool:
    return settings.app_env.lower() == "production"


# ---------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    database.initialize()

    await browser.start()

    async def on_offline() -> None:
        await notifications.offline()

    async def on_online() -> None:
        await notifications.restored()

        # Resume only cards that were explicitly paused by connectivity.
        database.execute_script(
            """
            UPDATE work_cards
            SET status = 'queued'
            WHERE status = 'paused'
              AND error_message = 'connection_lost'
            """
        )

        database.execute_script(
            """
            UPDATE projects
            SET status = 'queued'
            WHERE status = 'paused'
            """
        )

    connectivity.on_offline = on_offline
    connectivity.on_online = on_online

    await connectivity.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await connectivity.stop()
    await browser.stop()


# ---------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------

@app.get("/")
async def login_page():
    return FileResponse(frontend_dir / "login.html")


@app.get("/dashboard")
async def dashboard_page(session: Optional[str] = Cookie(default=None)):
    _require_session(session)
    return FileResponse(frontend_dir / "index.html")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
    }


# ---------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------

class LoginRequest(BaseModel):
    password: str


@app.post("/api/login")
async def login(payload: LoginRequest, response: Response):
    if not _verify_admin_password(payload.password):
        raise HTTPException(
            status_code=401,
            detail="كلمة المرور غير صحيحة",
        )

    token = secrets.token_urlsafe(48)
    _active_sessions.add(token)

    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=60 * 60 * 24,
        path="/",
    )

    return {
        "success": True,
        "message": "تم تسجيل الدخول",
    }


@app.post("/api/logout")
async def logout(
    response: Response,
    session: Optional[str] = Cookie(default=None),
):
    if session:
        _active_sessions.discard(session)

    response.delete_cookie(
        key="session",
        path="/",
    )

    return {"success": True}


# ---------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    project_id: Optional[int] = None
    workflow_type: WorkflowType = WorkflowType.ASSISTANT


@app.post("/api/chat")
async def chat(
    payload: ChatRequest,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    message = payload.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="الرسالة فارغة",
        )

    return await agent.chat(
        message=message,
        project_id=payload.project_id,
        workflow_type=payload.workflow_type,
    )


# ---------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------

class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""
    workflow_type: WorkflowType = WorkflowType.ASSISTANT


@app.get("/api/projects")
async def list_projects(
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)
    return {
        "projects": database.list_projects(),
    }


@app.post("/api/projects")
async def create_project(
    payload: ProjectCreateRequest,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    name = payload.name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="اسم المشروع مطلوب",
        )

    project_id = database.create_project(
        name=name,
        description=payload.description.strip(),
        workflow_type=payload.workflow_type.value,
    )

    return {
        "success": True,
        "project_id": project_id,
    }


@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    project = database.get_project(project_id)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود",
        )

    return project


# ---------------------------------------------------------------------
# Work Cards
# ---------------------------------------------------------------------

@app.get("/api/work-cards")
async def list_work_cards(
    project_id: Optional[int] = None,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    return {
        "cards": database.list_work_cards(project_id),
    }


@app.get("/api/work-cards/{card_id}")
async def get_work_card(
    card_id: int,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    card = database.get_work_card(card_id)

    if not card:
        raise HTTPException(
            status_code=404,
            detail="بطاقة العمل غير موجودة",
        )

    return card


class WorkCardActionRequest(BaseModel):
    action: ApprovalAction


@app.post("/api/work-cards/{card_id}/action")
async def work_card_action(
    card_id: int,
    payload: WorkCardActionRequest,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    try:
        result = await task_manager.handle_action(
            card_id=card_id,
            action=payload.action,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return {
        "success": True,
        "result": result,
    }


# ---------------------------------------------------------------------
# Code analysis
# ---------------------------------------------------------------------

class AnalyzeCodeRequest(BaseModel):
    code: str
    filename: str = "uploaded_code.py"


@app.post("/api/code/analyze")
async def analyze_code(
    payload: AnalyzeCodeRequest,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    if len(payload.code) > 500_000:
        raise HTTPException(
            status_code=413,
            detail="الملف كبير جداً للتحليل",
        )

    return code_analyzer.analyze(
        code=payload.code,
        filename=payload.filename,
    )


# ---------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------

@app.post("/api/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    project_id: Optional[int] = None,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    max_size = settings.max_upload_mb * 1024 * 1024

    original_name = file.filename or "uploaded_file"
    safe_name = Path(original_name).name

    if safe_name in {"", ".", ".."}:
        raise HTTPException(
            status_code=400,
            detail="اسم الملف غير صالح",
        )

    upload_root = Path(settings.upload_dir)
    upload_root.mkdir(parents=True, exist_ok=True)

    project_folder = (
        upload_root / str(project_id)
        if project_id is not None
        else upload_root / "general"
    )

    project_folder.mkdir(parents=True, exist_ok=True)

    target = project_folder / safe_name

    # Avoid accidental overwrite.
    if target.exists():
        target = project_folder / (
            f"{target.stem}_{secrets.token_hex(4)}{target.suffix}"
        )

    total = 0
    sha256 = hashlib.sha256()

    try:
        with target.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                total += len(chunk)

                if total > max_size:
                    target.unlink(missing_ok=True)

                    raise HTTPException(
                        status_code=413,
                        detail=f"الحد الأقصى للرفع هو {settings.max_upload_mb}MB",
                    )

                output.write(chunk)
                sha256.update(chunk)

    except HTTPException:
        raise

    except Exception:
        target.unlink(missing_ok=True)
        raise

    uploaded_id = database.create_uploaded_file(
        project_id=project_id,
        filename=target.name,
        original_filename=safe_name,
        path=str(target),
        size=total,
        sha256=sha256.hexdigest(),
    )

    return {
        "success": True,
        "file_id": uploaded_id,
        "filename": target.name,
        "size": total,
        "sha256": sha256.hexdigest(),
    }


# ---------------------------------------------------------------------
# Browser automation
# ---------------------------------------------------------------------

class BrowserOpenRequest(BaseModel):
    project_id: int
    site_name: str
    url: str


@app.post("/api/browser/open")
async def browser_open(
    payload: BrowserOpenRequest,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    return await browser.open_session(
        project_id=payload.project_id,
        site_name=payload.site_name,
        url=payload.url,
    )


class BrowserNavigateRequest(BaseModel):
    project_id: int
    site_name: str
    url: str


@app.post("/api/browser/navigate")
async def browser_navigate(
    payload: BrowserNavigateRequest,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    return await browser.navigate(
        project_id=payload.project_id,
        site_name=payload.site_name,
        url=payload.url,
    )


@app.get("/api/browser/status")
async def browser_status(
    project_id: int,
    site_name: str,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    return await browser.check_session(
        project_id=project_id,
        site_name=site_name,
    )


@app.post("/api/browser/close")
async def browser_close(
    project_id: int,
    site_name: str,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    await browser.close_session(
        project_id=project_id,
        site_name=site_name,
    )

    return {"success": True}


# ---------------------------------------------------------------------
# Secret / API panel
# ---------------------------------------------------------------------

class PanelVerifyRequest(BaseModel):
    password: str


@app.post("/api/panel/verify")
async def verify_panel(
    payload: PanelVerifyRequest,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    configured = settings.api_panel_password or ""

    valid = secrets.compare_digest(
        payload.password,
        configured,
    )

    if not valid:
        raise HTTPException(
            status_code=403,
            detail="كلمة مرور اللوحة السرية غير صحيحة",
        )

    return {
        "success": True,
        "message": "تم فتح اللوحة السرية",
    }


class SecretCreateRequest(BaseModel):
    project_id: Optional[int] = None
    name: str
    value: str


@app.post("/api/secrets")
async def create_secret(
    payload: SecretCreateRequest,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    if not payload.name.strip():
        raise HTTPException(
            status_code=400,
            detail="اسم السر مطلوب",
        )

    if not payload.value:
        raise HTTPException(
            status_code=400,
            detail="قيمة السر مطلوبة",
        )

    encrypted = secret_box.encrypt(payload.value)

    secret_id = database.create_secret(
        project_id=payload.project_id,
        name=payload.name.strip(),
        encrypted_value=encrypted,
    )

    return {
        "success": True,
        "secret_id": secret_id,
    }


# ---------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------

@app.get("/api/events")
async def list_events(
    project_id: Optional[int] = None,
    limit: int = 100,
    session: Optional[str] = Cookie(default=None),
):
    _require_session(session)

    limit = max(1, min(limit, 500))

    return {
        "events": database.list_events(
            project_id=project_id,
            limit=limit,
        ),
    }
