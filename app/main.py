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


# ================================================================
# الخدمات الأساسية
# ================================================================

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
        # إيقاف نهائي
        # --------------------------------------------------------

        if action == "stop":

            result = await task_manager.stop(
                work_card_id=card_id,
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
                work_card_id=card_id,
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
            status_code=400,
            detail=str(exc),
        ) from exc


# ================================================================
# الأحداث
# ================================================================

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


# ================================================================
# حالة النظام
# ================================================================

@app.get("/api/system/status")
async def system_status(
    _: str = Depends(_require_session),
):
    try:
        cards = db.list_all_work_cards()
    except Exception:
        cards = []

    running = 0
    paused = 0
    queued = 0
    completed = 0
    errors = 0

    for card in cards:
        status = str(
            card.get("status", "")
        ).lower()

        if status == "running":
            running += 1
        elif status == "paused":
            paused += 1
        elif status == "queued":
            queued += 1
        elif status == "completed":
            completed += 1
        elif status == "error":
            errors += 1

    return {
        "online": connectivity.is_online,
        "browser_initialized": (
            browser._playwright is not None
        ),
        "tasks": {
            "total": len(cards),
            "running": running,
            "paused": paused,
            "queued": queued,
            "completed": completed,
            "errors": errors,
        },
    }


# ================================================================
# المتصفح
# ================================================================

def _require_project(
    project_id: int,
):
    project = db.get_project(project_id)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود.",
        )

    return project


@app.post("/api/browser/open")
async def browser_open(
    request: BrowserOpenRequest,
    _: str = Depends(_require_session),
):
    _require_project(
        request.project_id
    )

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
    _require_project(
        request.project_id
    )

    try:
        result = await browser.navigate(
            project_id=request.project_id,
            url=request.url,
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


@app.post("/api/browser/click")
async def browser_click(
    request: BrowserClickRequest,
    _: str = Depends(_require_session),
):
    _require_project(
        request.project_id
    )

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
    _require_project(
        request.project_id
    )

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


@app.get("/api/browser/status/{project_id}")
async def browser_status(
    project_id: int,
    _: str = Depends(_require_session),
):
    _require_project(project_id)

    try:
        result = await browser.get_status(
            project_id
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


@app.get("/api/browser/text/{project_id}")
async def browser_text(
    project_id: int,
    _: str = Depends(_require_session),
):
    _require_project(project_id)

    try:
        result = await browser.get_text(
            project_id
        )

        return {
            "success": True,
            "text": result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post("/api/browser/inspect/{project_id}")
async def browser_inspect(
    project_id: int,
    _: str = Depends(_require_session),
):
    _require_project(project_id)

    try:
        result = await browser.inspect_page(
            project_id
        )

        return {
            "success": True,
            "page": result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post("/api/browser/screenshot/{project_id}")
async def browser_screenshot(
    project_id: int,
    _: str = Depends(_require_session),
):
    _require_project(project_id)

    try:
        result = await browser.screenshot(
            project_id
        )

        return {
            "success": True,
            "screenshot": result,
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
    _require_project(project_id)

    try:
        result = await browser.close_project(
            project_id
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


# ================================================================
# تحليل الملفات البرمجية
# ================================================================

@app.post("/api/code/analyze")
async def analyze_code(
    file: UploadFile = File(...),
    _: str = Depends(_require_session),
):

    filename = file.filename or "uploaded_code"

    if not filename:
        raise HTTPException(
            status_code=400,
            detail="اسم الملف غير صالح.",
        )

    try:
        raw = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"تعذر قراءة الملف: {exc}",
        ) from exc

    if len(raw) > settings.max_upload_size:
        raise HTTPException(
            status_code=413,
            detail="حجم الملف أكبر من الحد المسموح.",
        )

    try:
        source = raw.decode(
            "utf-8",
            errors="replace",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"تعذر قراءة النص: {exc}",
        ) from exc

    result = code_analyzer.analyze(
        filename=filename,
        source=source,
    )

    return {
        "success": True,
        "analysis": result,
    }


# ================================================================
# رفع الملفات
# ================================================================

@app.post("/api/uploads")
async def upload_file(
    file: UploadFile = File(...),
    project_id: Optional[int] = None,
    _: str = Depends(_require_session),
):

    filename = Path(
        file.filename or "uploaded_file"
    ).name

    if not filename:
        raise HTTPException(
            status_code=400,
            detail="اسم الملف غير صالح.",
        )

    if project_id is not None:
        _require_project(project_id)

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"تعذر قراءة الملف: {exc}",
        ) from exc

    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=413,
            detail="حجم الملف أكبر من الحد المسموح.",
        )

    upload_dir = settings.upload_directory

    target = upload_dir / filename

    # منع الكتابة خارج مجلد uploads.
    target = target.resolve()

    if upload_dir.resolve() not in target.parents:
        raise HTTPException(
            status_code=400,
            detail="مسار الملف غير صالح.",
        )

    target.write_bytes(content)

    try:
        record = db.create_uploaded_file(
            project_id=project_id,
            filename=filename,
            path=str(target),
            size=len(content),
        )
    except Exception:
        record = {
            "filename": filename,
            "path": str(target),
            "size": len(content),
            "project_id": project_id,
        }

    return {
        "success": True,
        "file": record,
    }


# ================================================================
# الأسرار
# ================================================================

@app.post("/api/secrets/unlock")
async def unlock_secrets(
    request: SecretPanelRequest,
    _: str = Depends(_require_session),
):
    if not settings.api_panel_password:
        raise HTTPException(
            status_code=503,
            detail="لوحة الأسرار غير مهيأة بعد.",
        )

    valid = security.secure_compare(
        request.password,
        settings.api_panel_password,
    )

    if not valid:
        raise HTTPException(
            status_code=401,
            detail="كلمة مرور لوحة الأسرار غير صحيحة.",
        )

    return {
        "success": True,
        "message": "تم فتح لوحة الأسرار.",
    }


# ================================================================
# إعدادات النظام العامة
# ================================================================

@app.get("/api/settings")
async def get_settings(
    _: str = Depends(_require_session),
):
    return {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "debug": settings.debug,
        "browser_headless": settings.browser_headless,
        "browser_timeout": settings.browser_timeout,
        "connectivity_interval": settings.connectivity_interval,
        "timezone": settings.timezone,
        "openai_configured": bool(
            settings.openai_api_key
        ),
        "telegram_configured": bool(
            settings.telegram_bot_token
            and settings.telegram_chat_id
        ),
        "whatsapp_configured": bool(
            settings.whatsapp_api_url
            and settings.whatsapp_access_token
        ),
    }


# ================================================================
# الأحداث الخاصة بالجلسات
# ================================================================

@app.get("/api/browser/sessions")
async def browser_sessions(
    _: str = Depends(_require_session),
):
    try:
        sessions = db.list_browser_sessions()
    except Exception:
        sessions = []

    return {
        "sessions": sessions,
    }


# ================================================================
# خطأ عام JSON
# ================================================================

@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request,
    exc: Exception,
):
    # لا نكشف تفاصيل داخلية للمستخدم النهائي.
    try:
        db.create_event(
            event_type="application_error",
            message=str(exc),
            metadata={
                "path": request.url.path,
                "method": request.method,
            },
        )
    except Exception:
        pass

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "detail": "حدث خطأ داخلي في النظام.",
        },
)
