from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import zipfile
from pathlib import Path
from typing import Any

from fastapi import (
    Cookie,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import Agent
from .approval import ApprovalManager
from .browser import BrowserManager
from .code_analyzer import CodeAnalyzer
from .config import get_settings
from .connectivity import ConnectivityMonitor
from .database import Database
from .models import EventType, WorkStatus
from .notifications import NotificationManager
from .security import PasswordHasher, SecretBox
from .task_manager import TaskManager


settings = get_settings()

database = Database(
    settings.database_path
)

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

task_manager = TaskManager(
    database=database,
    agent=agent,
    browser=browser,
    notifications=notifications,
)

approvals = ApprovalManager(
    database
)

code_analyzer = CodeAnalyzer()

secret_box = SecretBox(
    settings.encryption_key
)

connectivity = ConnectivityMonitor(
    database=database,
)


app = FastAPI(
    title=settings.app_name,
    version="2.0.0",
)


# ============================================================
# Runtime state
# ============================================================

_active_sessions: set[str] = set()

_connectivity_task: asyncio.Task | None = None


# ============================================================
# Pydantic models
# ============================================================

class LoginRequest(BaseModel):
    password: str = Field(
        min_length=1,
        max_length=256,
    )


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=20_000,
    )

    workflow_type: str = "assistant"

    project_id: int | None = None


class ProjectRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=200,
    )

    workflow_type: str = Field(
        min_length=1,
        max_length=100,
    )

    description: str = Field(
        default="",
        max_length=5_000,
    )


class CardActionRequest(BaseModel):
    action: str = Field(
        min_length=1,
        max_length=30,
    )


class BrowserOpenRequest(BaseModel):
    project_id: int

    site_name: str = Field(
        min_length=1,
        max_length=100,
    )

    url: str = Field(
        min_length=8,
        max_length=2_000,
    )


class BrowserNavigateRequest(BaseModel):
    project_id: int

    url: str = Field(
        min_length=8,
        max_length=2_000,
    )


class SecretRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
    )

    value: str = Field(
        min_length=1,
        max_length=50_000,
    )


class CodeAnalysisRequest(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=100_000,
    )


# ============================================================
# Authentication helpers
# ============================================================

def create_session() -> str:
    token = secrets.token_urlsafe(48)

    _active_sessions.add(token)

    return token


def is_authenticated(
    session: str | None,
) -> bool:

    if not session:
        return False

    return session in _active_sessions


def require_auth(
    session: str | None,
) -> None:

    if not is_authenticated(session):
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )


# ============================================================
# Startup / shutdown
# ============================================================

@app.on_event("startup")
async def startup_event() -> None:
    global _connectivity_task

    await browser.start()

    async def on_offline() -> None:
        await notifications.offline()

    async def on_online() -> None:
        await notifications.restored()

        database.execute_script(
            """
            UPDATE work_cards
            SET status = 'queued',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'paused'
            """
        )

    connectivity.set_callbacks(
        on_offline=on_offline,
        on_online=on_online,
    )

    _connectivity_task = asyncio.create_task(
        connectivity.run()
    )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _connectivity_task

    connectivity.stop()

    if _connectivity_task:
        _connectivity_task.cancel()

        try:
            await _connectivity_task
        except asyncio.CancelledError:
            pass

    await browser.stop()


# ============================================================
# Static frontend
# ============================================================

frontend_dir = (
    Path(__file__).resolve().parent.parent
    / "frontend"
)

if frontend_dir.exists():

    app.mount(
        "/static",
        StaticFiles(
            directory=str(
                frontend_dir / "static"
            ),
        ),
        name="static",
    )


@app.get("/")
async def root() -> FileResponse:

    index_file = frontend_dir / "login.html"

    if not index_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Frontend not found.",
        )

    return FileResponse(
        str(index_file)
    )


@app.get("/dashboard")
async def dashboard(
    session: str | None = Cookie(
        default=None
    ),
) -> FileResponse:

    require_auth(session)

    index_file = frontend_dir / "index.html"

    if not index_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Dashboard not found.",
        )

    return FileResponse(
        str(index_file)
    )


# ============================================================
# Health
# ============================================================

@app.get("/health")
async def health() -> dict[str, Any]:

    return {
        "status": "active",
        "system": settings.app_name,
        "version": "2.0.0",
        "internet": connectivity.online,
        "browser": browser.browser is not None,
    }


# ============================================================
# Authentication
# ============================================================

@app.post("/api/login")
async def login(
    request: LoginRequest,
) -> dict[str, Any]:

    if not PasswordHasher.verify_password(
        request.password,
        settings.admin_password,
    ):
        raise HTTPException(
            status_code=401,
            detail="كلمة المرور غير صحيحة.",
        )

    token = create_session()

    return {
        "success": True,
        "session": token,
    }


@app.post("/api/logout")
async def logout(
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    if session:
        _active_sessions.discard(session)

    return {
        "success": True
    }


# ============================================================
# Dashboard data
# ============================================================

@app.get("/api/dashboard")
async def dashboard_data(
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    return {
        "projects": database.list_projects(),
        "work_cards": database.list_work_cards(),
        "events": database.list_events(
            limit=100
        ),
        "internet": connectivity.online,
    }


# ============================================================
# Chat
# ============================================================

@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    result = await task_manager.create_task_from_chat(
        message=request.message,
        workflow_type=request.workflow_type,
        project_id=request.project_id,
    )

    return result


# ============================================================
# Projects
# ============================================================

@app.get("/api/projects")
async def list_projects(
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    return {
        "projects": database.list_projects()
    }


@app.post("/api/projects")
async def create_project(
    request: ProjectRequest,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    project_id = database.create_project(
        name=request.name,
        workflow_type=request.workflow_type,
        description=request.description,
    )

    database.add_event(
        event_type=EventType.INFO.value,
        message=(
            f"Project #{project_id} created."
        ),
        project_id=project_id,
    )

    return {
        "success": True,
        "project_id": project_id,
    }


@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    project = database.get_project(
        project_id
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود.",
        )

    return {
        "project": project,
        "messages": database.get_messages(
            project_id
        ),
        "work_cards": database.list_work_cards(
            project_id
        ),
        "events": database.list_events(
            project_id
        ),
    }


# ============================================================
# Work Cards
# ============================================================

@app.get("/api/work-cards")
async def list_work_cards(
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    return {
        "work_cards": database.list_work_cards()
    }


@app.get("/api/work-cards/{card_id}")
async def get_work_card(
    card_id: int,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    card = database.get_work_card(
        card_id
    )

    if not card:
        raise HTTPException(
            status_code=404,
            detail="Work Card غير موجود.",
        )

    return {
        "work_card": card
    }


@app.post("/api/work-cards/{card_id}/action")
async def work_card_action(
    card_id: int,
    request: CardActionRequest,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    action = request.action.lower().strip()

    if action == "approve":
        result = await task_manager.approve(
            card_id
        )

    elif action == "reject":
        result = await task_manager.reject(
            card_id
        )

    elif action == "pause":
        result = await task_manager.pause(
            card_id
        )

    elif action == "stop":
        result = await task_manager.stop(
            card_id
        )

    elif action == "resume":
        result = await task_manager.resume(
            card_id
        )

    else:
        raise HTTPException(
            status_code=400,
            detail="إجراء غير معروف.",
        )

    return result


# ============================================================
# Code analysis
# ============================================================

@app.post("/api/code/analyze")
async def analyze_code(
    request: CodeAnalysisRequest,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    result = code_analyzer.analyze(
        request.code
    )

    database.add_event(
        event_type=EventType.SECURITY.value,
        message="Code analysis completed.",
    )

    return result


# ============================================================
# File uploads
# ============================================================

def _safe_filename(
    filename: str,
) -> str:

    filename = Path(
        filename
    ).name

    allowed = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "._-"
    )

    cleaned = "".join(
        char if char in allowed else "_"
        for char in filename
    )

    return cleaned[:180] or "upload"


def _zip_is_safe(
    zip_path: Path,
) -> bool:

    try:
        with zipfile.ZipFile(
            zip_path,
            "r",
        ) as archive:

            root = zip_path.parent.resolve()

            for member in archive.infolist():

                target = (
                    root
                    / member.filename
                ).resolve()

                if (
                    target != root
                    and root not in target.parents
                ):
                    return False

        return True

    except zipfile.BadZipFile:
        return False


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    project_id: int | None = None,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="اسم الملف غير موجود.",
        )

    filename = _safe_filename(
        file.filename
    )

    upload_root = Path(
        settings.upload_dir
    )

    upload_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = upload_root / (
        f"{secrets.token_hex(12)}"
        f"_{filename}"
    )

    size = 0
    digest = hashlib.sha256()

    try:
        with target.open("wb") as output:

            while True:

                chunk = await file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                size += len(chunk)

                if (
                    size
                    > settings.max_upload_bytes
                ):
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "الملف يتجاوز الحد "
                            "المسموح به."
                        ),
                    )

                digest.update(chunk)
                output.write(chunk)

    except Exception:
        if target.exists():
            target.unlink()

        raise

    sha256 = digest.hexdigest()

    file_id = database.add_uploaded_file(
        original_name=filename,
        stored_path=str(target),
        size_bytes=size,
        sha256=sha256,
        project_id=project_id,
    )

    is_zip = (
        filename.lower().endswith(".zip")
    )

    zip_safe = None

    if is_zip:
        zip_safe = _zip_is_safe(
            target
        )

        if not zip_safe:
            database.add_event(
                event_type=EventType.SECURITY.value,
                message=(
                    "Unsafe ZIP archive rejected."
                ),
                project_id=project_id,
            )

            target.unlink(
                missing_ok=True
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "ملف ZIP يحتوي على مسارات "
                    "غير آمنة."
                ),
            )

    database.add_event(
        event_type=EventType.INFO.value,
        message=(
            f"File uploaded: {filename}"
        ),
        project_id=project_id,
    )

    return {
        "success": True,
        "file_id": file_id,
        "filename": filename,
        "size": size,
        "sha256": sha256,
        "zip": is_zip,
        "zip_safe": zip_safe,
    }


# ============================================================
# Browser
# ============================================================

@app.post("/api/browser/open")
async def browser_open(
    request: BrowserOpenRequest,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    project = database.get_project(
        request.project_id
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail="المشروع غير موجود.",
        )

    try:
        page = await browser.open_session(
            project_id=request.project_id,
            site_name=request.site_name,
            url=request.url,
        )

        return {
            "success": True,
            "url": page.url,
            "title": await page.title(),
        }

    except Exception as exc:

        database.add_event(
            event_type=EventType.ERROR.value,
            message=(
                "Browser open failed: "
                f"{type(exc).__name__}"
            ),
            project_id=request.project_id,
        )

        raise HTTPException(
            status_code=500,
            detail="تعذر فتح جلسة المتصفح.",
        ) from exc


@app.post("/api/browser/navigate")
async def browser_navigate(
    request: BrowserNavigateRequest,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    result = await browser.navigate(
        project_id=request.project_id,
        url=request.url,
    )

    return result


@app.get("/api/browser/{project_id}/status")
async def browser_status(
    project_id: int,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    result = await browser.check_session(
        project_id
    )

    return result


@app.post("/api/browser/{project_id}/close")
async def browser_close(
    project_id: int,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    await browser.close_session(
        project_id
    )

    return {
        "success": True
    }


# ============================================================
# Protected secret panel
# ============================================================

@app.post("/api/panel/verify")
async def verify_panel(
    password: str,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    if not secrets.compare_digest(
        password,
        settings.api_panel_password,
    ):
        raise HTTPException(
            status_code=401,
            detail="كلمة مرور اللوحة غير صحيحة.",
        )

    return {
        "success": True
    }


@app.post("/api/secrets")
async def save_secret(
    request: SecretRequest,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    encrypted = secret_box.encrypt(
        request.value
    )

    database.save_secret(
        name=request.name,
        encrypted_value=encrypted,
    )

    database.add_event(
        event_type=EventType.SECURITY.value,
        message=(
            f"Encrypted secret saved: "
            f"{request.name}"
        ),
    )

    return {
        "success": True,
        "name": request.name,
    }


# ============================================================
# Events
# ============================================================

@app.get("/api/events")
async def events(
    project_id: int | None = None,
    session: str | None = Cookie(
        default=None
    ),
) -> dict[str, Any]:

    require_auth(session)

    return {
        "events": database.list_events(
            project_id=project_id,
            limit=200,
        )
}
