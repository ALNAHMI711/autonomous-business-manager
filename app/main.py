from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import Agent
from app.approval import ApprovalManager
from app.browser import BrowserManager
from app.code_analyzer import CodeAnalyzer
from app.config import settings
from app.connectivity import ConnectivityMonitor
from app.database import Database
from app.notifications import NotificationManager
from app.security import PasswordHasher, SecretBox
from app.task_manager import TaskManager


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"


db = Database(settings.database_path)
password_hasher = PasswordHasher()
secret_box = SecretBox(settings.encryption_key)

agent = Agent(
    database=db,
    settings=settings,
)

approval_manager = ApprovalManager(db)

browser = BrowserManager(
    database=db,
    settings=settings,
)

notifications = NotificationManager(
    database=db,
    settings=settings,
)

code_analyzer = CodeAnalyzer()

connectivity = ConnectivityMonitor(
    database=db,
    settings=settings,
)

task_manager = TaskManager(
    database=db,
    agent=agent,
    browser=browser,
    notifications=notifications,
    approval_manager=approval_manager,
)


_active_sessions: set[str] = set()


class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    project_id: Optional[int] = None


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class WorkCardActionRequest(BaseModel):
    action: str


class BrowserOpenRequest(BaseModel):
    project_id: int
    site: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)


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
    password: str


def _cookie_secure() -> bool:
    return settings.app_env.lower() == "production"


def _verify_admin_password(password: str) -> bool:
    configured = settings.admin_password

    if not configured:
        return False

    return password == configured


def _get_session_from_request(request: Request) -> Optional[str]:
    return request.cookies.get("session")


def _require_session(request: Request) -> str:
    token = _get_session_from_request(request)

    if not token or token not in _active_sessions:
        raise HTTPException(
            status_code=401,
            detail="جلسة الدخول غير صالحة أو منتهية.",
        )

    return token


async def _handle_offline() -> None:
    """
    When internet connectivity is lost:
    - mark running work cards as paused
    - record an event
    - notify through configured channels
    """
    try:
        db.execute_script(
            """
            UPDATE work_cards
            SET status = 'paused',
                error_message = 'connection_lost',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'running'
            """
        )
    except Exception:
        pass

    try:
        db.create_event(
            event_type="connection_lost",
            message="انقطع اتصال الإنترنت. تم إيقاف الأعمال الجارية مؤقتاً.",
        )
    except Exception:
        pass

    try:
        await notifications.send_offline()
    except Exception:
        pass


async def _handle_online() -> None:
    """
    When connectivity returns:
    - resume cards paused specifically because of connection loss
    - record an event
    - notify
    """
    try:
        db.execute_script(
            """
            UPDATE work_cards
            SET status = 'queued',
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'paused'
              AND error_message = 'connection_lost'
            """
        )
    except Exception:
        pass

    try:
        db.create_event(
            event_type="connection_restored",
            message="عاد اتصال الإنترنت. تم استئناف الأعمال المتوقفة بسبب الانقطاع.",
        )
    except Exception:
        pass

    try:
        await notifications.send_restored()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle.
    """
    try:
        db.initialize()
    except Exception:
        pass

    try:
        await browser.initialize()
    except Exception:
        pass

    try:
        connectivity.set_callbacks(
            on_offline=_handle_offline,
            on_online=_handle_online,
        )
    except Exception:
        pass

    try:
        await connectivity.start()
    except Exception:
        pass

    yield

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
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )


@app.get("/")
async def root():
    token = _get_session_from_request

    return RedirectResponse(url="/dashboard")


@app.get("/login")
async def login_page():
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/dashboard")
async def dashboard(request: Request):
    session = _get_session_from_request(request)

    if not session or session not in _active_sessions:
        return RedirectResponse(url="/login")

    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
async def health():
    online = True

    try:
        online = connectivity.is_online()
    except Exception:
        pass

    return {
        "status": "ok",
        "online": online,
        "app": settings.app_name,
    }


@app.post("/api/login")
async def login(request: LoginRequest):
    if not _verify_admin_password(request.password):
        raise HTTPException(
            status_code=401,
            detail="كلمة المرور غير صحيحة.",
        )

    token = secrets.token_urlsafe(48)

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
async def logout(session: str = Depends(_require_session)):
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


@app.get("/api/projects")
async def list_projects(_: str = Depends(_require_session)):
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
    }


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
    return {
        "messages": db.list_chat_messages(project_id),
    }


@app.get("/api/work-cards")
async def list_work_cards(
    project_id: Optional[int] = None,
    _: str = Depends(_require_session),
):
    if project_id is not None:
        cards = db.list_work_cards(project_id)
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
    allowed = {
        "approve",
        "reject",
        "pause",
        "stop",
        "resume",
    }

    if request.action not in allowed:
        raise HTTPException(
            status_code=400,
            detail="إجراء غير صالح.",
        )

    try:
        result = await approval_manager.handle_action(
            card_id=card_id,
            action=request.action,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        "result": result,
    }


@app.get("/api/events")
async def events(
    limit: int = 100,
    _: str = Depends(_require_session),
):
    limit = max(1, min(limit, 500))

    return {
        "events": db.list_events(limit=limit),
    }


@app.post("/api/browser/open")
async def browser_open(
    request: BrowserOpenRequest,
    _: str = Depends(_require_session),
):
    project = db.get_project(request.project_id)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود.",
        )

    result = await browser.open_project(
        project_id=request.project_id,
        site=request.site,
        url=request.url,
    )

    return {
        "success": True,
        "browser": result,
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
        "browser": result,
    }


@app.get("/api/browser/status/{project_id}")
async def browser_status(
    project_id: int,
    _: str = Depends(_require_session),
):
    return {
        "status": await browser.get_status(project_id),
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
    result = await browser.close_project(project_id)

    return {
        "success": True,
        "result": result,
    }


@app.post("/api/code/analyze")
async def analyze_code(
    file: UploadFile = File(...),
    _: str = Depends(_require_session),
):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="اسم الملف غير موجود.",
        )

    content = await file.read()

    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=413,
            detail="حجم الملف أكبر من الحد المسموح.",
        )

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="الملف يجب أن يكون نصياً بترميز UTF-8.",
        )

    result = code_analyzer.analyze(
        filename=file.filename,
        source=text,
    )

    try:
        db.save_uploaded_file(
            filename=file.filename,
            content_size=len(content),
            analysis=result,
        )
    except Exception:
        pass

    return {
        "success": True,
        "filename": file.filename,
        "analysis": result,
    }


@app.post("/api/secrets/panel/verify")
async def verify_secret_panel(
    request: SecretPanelRequest,
    _: str = Depends(_require_session),
):
    if not settings.api_panel_password:
        raise HTTPException(
            status_code=503,
            detail="لوحة الأسرار غير مهيأة.",
        )

    if request.password != settings.api_panel_password:
        raise HTTPException(
            status_code=401,
            detail="كلمة مرور لوحة الأسرار غير صحيحة.",
        )

    return {
        "success": True,
        "message": "تم فتح لوحة الأسرار.",
    }


@app.get("/api/secrets")
async def list_secrets(
    _: str = Depends(_require_session),
):
    return {
        "secrets": db.list_secrets_metadata(),
    }


@app.get("/api/notifications/status")
async def notification_status(
    _: str = Depends(_require_session),
):
    return {
        "telegram": notifications.telegram_configured(),
        "whatsapp": notifications.whatsapp_configured(),
    }


@app.get("/api/browser/sessions")
async def browser_sessions(
    _: str = Depends(_require_session),
):
    return {
        "sessions": db.list_browser_sessions(),
    }


@app.get("/api/connectivity")
async def connectivity_status(
    _: str = Depends(_require_session),
):
    try:
        online = connectivity.is_online()
    except Exception:
        online = False

    return {
        "online": online,
    }


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "detail": "المسار غير موجود.",
            },
        )

    return JSONResponse(
        status_code=404,
        content={
            "success": False,
            "detail": "الصفحة غير موجودة.",
        },
)
