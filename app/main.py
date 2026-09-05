from __future__ import annotations

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
from app.security import SecurityManager
from app.task_manager import TaskManager


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"


# ----------------------------------------------------------------------
# Core services
# ----------------------------------------------------------------------

db = Database(settings.database_path)

security = SecurityManager(settings)

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


_active_sessions: set[str] = set()


# ----------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------

class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    project_id: Optional[int] = None


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class WorkCardActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=50)
    note: str = Field(default="", max_length=2000)


class BrowserOpenRequest(BaseModel):
    project_id: int
    site: str = Field(min_length=1, max_length=2000)
    url: Optional[str] = Field(default=None, max_length=2000)


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


# ----------------------------------------------------------------------
# Authentication
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Connectivity callbacks
# ----------------------------------------------------------------------

async def _handle_offline() -> None:
    """
    Pause running tasks when the internet connection disappears.
    """

    try:
        await task_manager.handle_offline()
    except Exception:
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
    """
    Resume tasks that were paused because of connectivity loss.
    """

    try:
        await task_manager.handle_online()
    except Exception:
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
            message=(
                "عاد اتصال الإنترنت. "
                "تم استئناف الأعمال المتوقفة بسبب الانقطاع."
            ),
        )
    except Exception:
        pass

    try:
        await notifications.send_restored()
    except Exception:
        pass


# ----------------------------------------------------------------------
# Application lifecycle
# ----------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize and safely shut down all application services.
    """

    db.initialize()

    try:
        settings.ensure_directories()
    except Exception:
        pass

    try:
        await browser.initialize()
    except Exception:
        # Browser automation should not prevent the dashboard
        # from starting. Browser operations will report their own errors.
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
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )


# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Login / logout
# ----------------------------------------------------------------------

@app.post("/api/login")
async def login(
    request: LoginRequest,
):
    if not _verify_admin_password(
        request.password
    ):
        raise HTTPException(
            status_code=401,
            detail="كلمة المرور غير صحيحة.",
        )

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


# ----------------------------------------------------------------------
# Projects
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Chat / Agent
# ----------------------------------------------------------------------

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
        "messages": db.list_chat_messages(
            project_id
        ),
    }


# ----------------------------------------------------------------------
# Work cards
# ----------------------------------------------------------------------

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
        if action == "approve":
            result = await task_manager.approve(
                card_id
            )

            if result:
                await task_manager.run(
                    card_id
                )

            return {
                "success": True,
                "result": db.get_work_card(
                    card_id
                ),
            }

        if action == "reject":
            result = await approval_manager.reject(
                card_id=card_id,
                note=request.note,
            )

        elif action == "pause":
            result = await task_manager.pause(
                work_card_id=card_id,
                reason=request.note or "manual_pause",
            )

        elif action == "stop":
            result = await task_manager.stop(
                work_card_id=card_id,
            )

        elif action == "resume":
            result = await task_manager.resume(
                work_card_id=card_id,
            )

        else:
            raise ValueError(
                "إجراء غير مدعوم."
            )

        return {
            "success": True,
            "result": result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


# ----------------------------------------------------------------------
# Events
# ----------------------------------------------------------------------

@app.get("/api/events")
async def events(
    limit: int = 100,
    _: str = Depends(_require_session),
):
    limit = max(
        1,
        min(limit, 500),
    )

    return {
        "events": db.list_events(
            limit=limit
        ),
    }


# ----------------------------------------------------------------------
# Browser automation
# ----------------------------------------------------------------------

@app.post("/api/browser/open")
async def browser_open(
    request: BrowserOpenRequest,
    _: str = Depends(_require_session),
):
    project = db.get_project(
        request.project_id
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود.",
        )

    # BrowserManager uses the URL supplied as the site/profile origin.
    target = request.url or request.site

    try:
        result = await browser.open_project(
            project_id=request.project_id,
            site=target,
        )

        return {
            "success": True,
            "browser": result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post("/api/browser/navigate")
async def browser_navigate(
    request: BrowserNavigateRequest,
    _: str = Depends(_require_session),
):
    try:
        result = await browser.navigate(
            project_id=request.project_id,
            url=request.url,
        )

        if result.get("session_expired"):
            try:
                await notifications.send_session_expired(
                    request.project_id
                )
            except Exception:
                pass

        return {
            "success": True,
            "browser": result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.get("/api/browser/status/{project_id}")
async def browser_status(
    project_id: int,
    _: str = Depends(_require_session),
):
    try:
        result = await browser.get_status(
            project_id
        )

        return {
            "status": result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post("/api/browser/click")
async def browser_click(
    request: BrowserClickRequest,
    _: str = Depends(_require_session),
):
    try:
        result = await browser.click(
            project_id=request.project_id,
            selector=request.selector,
        )

        return {
            "success": True,
            "result": result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post("/api/browser/fill")
async def browser_fill(
    request: BrowserFillRequest,
    _: str = Depends(_require_session),
):
    try:
        result = await browser.fill(
            project_id=request.project_id,
            selector=request.selector,
            value=request.value,
        )

        return {
            "success": True,
            "result": result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post("/api/browser/close/{project_id}")
async def browser_close(
    project_id: int,
    _: str = Depends(_require_session),
):
    try:
        await browser.close_project(
            project_id
        )

        return {
            "success": True,
            "message": "تم إغلاق جلسة المتصفح.",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


# ----------------------------------------------------------------------
# Code analyzer
# ----------------------------------------------------------------------

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
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="الملف يجب أن يكون نصياً بترميز UTF-8.",
        ) from exc

    result = code_analyzer.analyze(
        filename=file.filename,
        source=text,
    )

    return {
        "success": True,
        "analysis": result,
    }


# ----------------------------------------------------------------------
# Secret panel
# ----------------------------------------------------------------------

@app.post("/api/secrets/panel/verify")
async def verify_secret_panel(
    request: SecretPanelRequest,
    _: str = Depends(_require_session),
):
    configured = settings.api_panel_password

    if not configured:
        raise HTTPException(
            status_code=503,
            detail="لوحة الأسرار غير مهيأة بعد.",
        )

    if not security.secure_compare(
        request.password,
        configured,
    ):
        raise HTTPException(
            status_code=403,
            detail="كلمة مرور لوحة الأسرار غير صحيحة.",
        )

    return {
        "success": True,
        "message": "تم التحقق بنجاح.",
        "encryption_available": (
            security.encryption_available
        ),
        "secrets": db.list_secrets_metadata(),
    }


# ----------------------------------------------------------------------
# Browser / project status
# ----------------------------------------------------------------------

@app.get("/api/status")
async def system_status(
    _: str = Depends(_require_session),
):
    return {
        "online": connectivity.is_online,
        "running_tasks": task_manager.get_running_ids(),
        "encryption_available": (
            security.encryption_available
        ),
        "telegram_configured": (
            notifications.telegram_configured()
        ),
        "whatsapp_configured": (
            notifications.whatsapp_configured()
        ),
    }


# ----------------------------------------------------------------------
# Error handlers
# ----------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception(
    request: Request,
    exc: Exception,
):
    # Keep internal exception details out of production responses.
    if settings.debug:
        detail = str(exc)
    else:
        detail = "حدث خطأ داخلي في النظام."

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "detail": detail,
        },
)
