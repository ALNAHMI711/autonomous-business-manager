from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import Agent
from .approval import ApprovalManager
from .browser import BrowserManager
from .code_analyzer import CodeAnalyzer
from .config import get_settings
from .connectivity import ConnectivityMonitor
from .database import Database
from .models import ApprovalAction, WorkflowType
from .notifications import NotificationManager
from .security import PasswordHasher, SecretBox
from .task_manager import TaskManager


settings = get_settings()

database = Database(settings.database_path)
password_hasher = PasswordHasher()
secret_box = SecretBox(settings.encryption_key)

agent = Agent(
    settings=settings,
    database=database,
)

browser = BrowserManager(
    settings=settings,
    database=database,
)

notifications = NotificationManager(
    settings=settings,
    database=database,
)

approval = ApprovalManager(
    database=database,
)

code_analyzer = CodeAnalyzer()

task_manager = TaskManager(
    database=database,
    agent=agent,
    browser=browser,
    notifications=notifications,
    approval=approval,
)

connectivity = ConnectivityMonitor(
    settings=settings,
    database=database,
)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
)

app.mount(
    "/static",
    StaticFiles(directory="frontend/static"),
    name="static",
)


_active_sessions: set[str] = set()


class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    workflow_type: WorkflowType = WorkflowType.assistant


class WorkCardActionRequest(BaseModel):
    action: ApprovalAction


class CodeAnalyzeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=500000)


class BrowserOpenRequest(BaseModel):
    project_id: int
    site: str


class BrowserNavigateRequest(BaseModel):
    project_id: int
    url: str


class BrowserCloseRequest(BaseModel):
    project_id: int


class SecretPanelVerifyRequest(BaseModel):
    password: str = Field(min_length=1)


class SecretCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=10000)


def _verify_admin_password(password: str) -> bool:
    configured = settings.admin_password

    if not configured:
        return False

    try:
        if password_hasher.verify(
            password,
            configured,
        ):
            return True
    except Exception:
        pass

    return secrets.compare_digest(
        password,
        configured,
    )


def _verify_api_panel_password(password: str) -> bool:
    configured = settings.api_panel_password

    if not configured:
        return False

    try:
        if password_hasher.verify(
            password,
            configured,
        ):
            return True
    except Exception:
        pass

    return secrets.compare_digest(
        password,
        configured,
    )


def _cookie_secure() -> bool:
    return settings.app_env.lower() == "production"


def _require_session(
    session: str | None = Cookie(default=None),
) -> str:
    if not session:
        raise HTTPException(
            status_code=401,
            detail="يجب تسجيل الدخول أولاً.",
        )

    if session not in _active_sessions:
        raise HTTPException(
            status_code=401,
            detail="انتهت الجلسة.",
        )

    return session


async def _handle_offline() -> None:
    try:
        database.execute_script(
            """
            UPDATE work_cards
            SET
                status = 'paused',
                error_message = 'connection_lost'
            WHERE status = 'running';
            """
        )

        await notifications.send_offline()

    except Exception:
        pass


async def _handle_online() -> None:
    try:
        await notifications.send_restored()

        database.execute_script(
            """
            UPDATE work_cards
            SET
                status = 'queued',
                error_message = NULL
            WHERE
                status = 'paused'
                AND error_message = 'connection_lost';
            """
        )

    except Exception:
        pass


@app.on_event("startup")
async def startup() -> None:
    database.initialize()

    await browser.initialize()

    connectivity.set_callbacks(
        on_offline=_handle_offline,
        on_online=_handle_online,
    )

    await connectivity.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    try:
        await connectivity.stop()
    except Exception:
        pass

    try:
        await browser.shutdown()
    except Exception:
        pass


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(
        "frontend/login.html"
    )


@app.get("/dashboard")
async def dashboard(
    session: str | None = Cookie(default=None),
) -> Any:
    if (
        not session
        or session not in _active_sessions
    ):
        return RedirectResponse(
            url="/",
            status_code=303,
        )

    return FileResponse(
        "frontend/index.html"
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "internet": connectivity.is_online,
    }


@app.post("/api/login")
async def login(
    request: LoginRequest,
) -> Any:
    if not _verify_admin_password(
        request.password
    ):
        raise HTTPException(
            status_code=401,
            detail="كلمة المرور غير صحيحة.",
        )

    token = secrets.token_urlsafe(48)

    _active_sessions.add(token)

    response = {
        "success": True,
        "message": "تم تسجيل الدخول بنجاح.",
    }

    result = RedirectResponse(
        url="/dashboard",
        status_code=303,
    )

    result.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=86400,
        path="/",
    )

    return result if False else {
        **response,
        "_set_cookie": token,
    }


@app.post("/api/logout")
async def logout(
    session: str = Depends(_require_session),
) -> Any:
    _active_sessions.discard(session)

    response = {
        "success": True,
        "message": "تم تسجيل الخروج.",
    }

    return response


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    session: str = Depends(_require_session),
) -> dict[str, Any]:
    result = await agent.chat(
        request.message
    )

    return result


@app.get("/api/projects")
async def list_projects(
    session: str = Depends(_require_session),
) -> Any:
    return database.list_projects()


@app.post("/api/projects")
async def create_project(
    request: ProjectCreateRequest,
    session: str = Depends(_require_session),
) -> Any:
    project_id = database.create_project(
        name=request.name,
        description=request.description,
        workflow_type=request.workflow_type.value,
    )

    return database.get_project(project_id)


@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    session: str = Depends(_require_session),
) -> Any:
    project = database.get_project(project_id)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود.",
        )

    return project


@app.get("/api/work-cards")
async def list_work_cards(
    session: str = Depends(_require_session),
) -> Any:
    return database.list_work_cards()


@app.get("/api/work-cards/{card_id}")
async def get_work_card(
    card_id: int,
    session: str = Depends(_require_session),
) -> Any:
    card = database.get_work_card(card_id)

    if not card:
        raise HTTPException(
            status_code=404,
            detail="بطاقة العمل غير موجودة.",
        )

    return card


@app.post("/api/work-cards/{card_id}/action")
async def work_card_action(
    card_id: int,
    request: WorkCardActionRequest,
    session: str = Depends(_require_session),
) -> Any:
    try:
        result = approval.handle(
            card_id=card_id,
            action=request.action,
        )

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@app.post("/api/code/analyze")
async def analyze_code(
    request: CodeAnalyzeRequest,
    session: str = Depends(_require_session),
) -> Any:
    return code_analyzer.analyze(
        request.code
    )


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    session: str = Depends(_require_session),
) -> Any:
    filename = Path(
        file.filename or "upload.bin"
    ).name

    if not filename:
        filename = "upload.bin"

    content = await file.read()

    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=413,
            detail="حجم الملف أكبر من الحد المسموح.",
        )

    upload_dir = Path(
        settings.upload_dir
    )

    upload_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    safe_name = (
        f"{secrets.token_hex(8)}_{filename}"
    )

    target = upload_dir / safe_name

    target.write_bytes(content)

    file_id = database.create_uploaded_file(
        original_name=filename,
        stored_path=str(target),
        size=len(content),
        content_type=file.content_type or "",
    )

    return {
        "success": True,
        "file_id": file_id,
        "filename": filename,
        "size": len(content),
    }


@app.post("/api/browser/open")
async def browser_open(
    request: BrowserOpenRequest,
    session: str = Depends(_require_session),
) -> Any:
    try:
        return await browser.open_project(
            project_id=request.project_id,
            site=request.site,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"تعذر فتح المتصفح: {exc}",
        )


@app.post("/api/browser/navigate")
async def browser_navigate(
    request: BrowserNavigateRequest,
    session: str = Depends(_require_session),
) -> Any:
    try:
        result = await browser.navigate(
            project_id=request.project_id,
            url=request.url,
        )

        if result.get("session_expired"):
            await notifications.send_reauth(
                project_id=request.project_id
            )

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"تعذر الانتقال: {exc}",
        )


@app.get("/api/browser/status/{project_id}")
async def browser_status(
    project_id: int,
    session: str = Depends(_require_session),
) -> Any:
    result = await browser.get_status(
        project_id
    )

    if result.get("session_expired"):
        await notifications.send_reauth(
            project_id=project_id
        )

    return result


@app.post("/api/browser/close")
async def browser_close(
    request: BrowserCloseRequest,
    session: str = Depends(_require_session),
) -> Any:
    await browser.close_project(
        request.project_id
    )

    return {
        "success": True,
        "project_id": request.project_id,
        "status": "closed",
    }


@app.post("/api/secrets/panel/verify")
async def verify_secret_panel(
    request: SecretPanelVerifyRequest,
    session: str = Depends(_require_session),
) -> Any:
    if not _verify_api_panel_password(
        request.password
    ):
        raise HTTPException(
            status_code=401,
            detail="كلمة مرور لوحة الأسرار غير صحيحة.",
        )

    return {
        "success": True,
        "message": "تم التحقق من لوحة الأسرار.",
    }


@app.post("/api/secrets")
async def create_secret(
    request: SecretCreateRequest,
    session: str = Depends(_require_session),
) -> Any:
    encrypted = secret_box.encrypt(
        request.value
    )

    secret_id = database.create_secret(
        name=request.name,
        encrypted_value=encrypted,
    )

    return {
        "success": True,
        "secret_id": secret_id,
        "name": request.name,
    }


@app.get("/api/events")
async def list_events(
    session: str = Depends(_require_session),
) -> Any:
    return database.list_events(limit=100)
