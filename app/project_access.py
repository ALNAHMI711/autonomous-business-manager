from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth_store import AuthStore
from app.database import Database
from app.ownership import OwnershipStore
from app.security import hash_session_token


class ProjectAccessMiddleware:
    """Fail closed on project-scoped API requests with durable owner checks."""

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    PROJECT_PATHS = {
        "/api/projects/",
        "/api/chat/",
        "/api/browser/close/",
    }
    OWNER_LIST_PATHS = {"/api/projects", "/api/work-cards", "/api/approvals"}

    def __init__(self, app: ASGIApp, database: Database) -> None:
        self.app = app
        self.database = database
        self.ownership = OwnershipStore(str(database.database_path))
        self.auth = AuthStore(str(database.database_path))
        self.ownership.initialize()
        self.auth.initialize()

    @staticmethod
    def _session_token(headers: list[tuple[bytes, bytes]]) -> Optional[str]:
        for key, value in headers:
            if key.lower() != b"cookie":
                continue
            for part in value.decode("utf-8", "ignore").split(";"):
                name, separator, token = part.strip().partition("=")
                if separator and name == "session" and token:
                    return token
        return None

    def _user_id(self, headers: list[tuple[bytes, bytes]]) -> Optional[int]:
        token = self._session_token(headers)
        if not token:
            return None
        return self.auth.user_id(hash_session_token(token))

    @staticmethod
    def _path_id(path: str, prefix: str) -> Optional[int]:
        if not path.startswith(prefix):
            return None
        raw = path[len(prefix):].strip("/").split("/", 1)[0]
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _validate_project(self, project_id: Any, user_id: Optional[int]) -> bool:
        try:
            value = int(project_id)
        except (TypeError, ValueError):
            return False
        if value <= 0 or user_id is None:
            return False
        return self.ownership.user_can_access_project(user_id, value)

    def _validate_card(self, card_id: Any, user_id: Optional[int]) -> bool:
        try:
            value = int(card_id)
        except (TypeError, ValueError):
            return False
        if value <= 0 or user_id is None:
            return False
        card = self.database.get_work_card(value)
        if not card:
            return False
        project_id = card.get("project_id")
        return project_id is not None and self._validate_project(project_id, user_id)

    async def _read_body(self, receive: Receive) -> tuple[bytes, Receive]:
        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                return b"".join(chunks), receive
            chunks.append(message.get("body", b""))
            more = bool(message.get("more_body", False))
        body = b"".join(chunks)
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return body, replay

    async def _owner_filtered_send(self, path: str, user_id: int, send: Send) -> Send:
        messages: list[Message] = []

        async def capture(message: Message) -> None:
            messages.append(message)

        async def flush() -> None:
            body = b"".join(
                message.get("body", b"")
                for message in messages
                if message.get("type") == "http.response.body"
            )
            status = next(
                (int(message.get("status", 200)) for message in messages if message.get("type") == "http.response.start"),
                200,
            )
            headers = list(
                next(
                    (message.get("headers", []) for message in messages if message.get("type") == "http.response.start"),
                    [],
                )
            )
            try:
                payload = json.loads(body.decode("utf-8"))
                allowed_projects = set(self.ownership.list_project_ids(user_id))
                if path == "/api/projects" and isinstance(payload.get("projects"), list):
                    payload["projects"] = [
                        project for project in payload["projects"]
                        if int(project.get("id", -1)) in allowed_projects
                    ]
                elif path == "/api/work-cards" and isinstance(payload.get("work_cards"), list):
                    payload["work_cards"] = [
                        card for card in payload["work_cards"]
                        if card.get("project_id") is not None
                        and int(card.get("project_id")) in allowed_projects
                    ]
                elif path == "/api/approvals" and isinstance(payload.get("approvals"), list):
                    payload["approvals"] = [
                        approval for approval in payload["approvals"]
                        if self._validate_card(approval.get("work_card_id"), user_id)
                    ]
                elif path == "/api/projects" and isinstance(payload.get("project"), dict):
                    project = payload["project"]
                    project_id = project.get("id")
                    if project_id is None or not self.ownership.assign_project(int(project_id), user_id):
                        await self._reject(send, 500, "تعذر تثبيت ملكية المشروع.")
                        return
                    project["owner_id"] = user_id
                else:
                    await send(messages[0])
                    for message in messages[1:]:
                        await send(message)
                    return
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode("ascii")))
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                pass
            await send({"type": "http.response.start", "status": status, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        async def proxy(message: Message) -> None:
            await capture(message)

        proxy.flush = flush  # type: ignore[attr-defined]
        return proxy  # type: ignore[return-value]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", [])
        user_id = self._user_id(headers)
        if user_id is None:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        query = parse_qs((scope.get("query_string") or b"").decode("utf-8", "ignore"))
        project_id: Any = query.get("project_id", [None])[0]

        for prefix in self.PROJECT_PATHS:
            if path.startswith(prefix):
                project_id = self._path_id(path, prefix)
                break

        if path.startswith("/api/work-cards/"):
            card_id = self._path_id(path, "/api/work-cards/")
            if card_id is not None and not self._validate_card(card_id, user_id):
                await self._reject(send, 404, "بطاقة العمل أو مشروعها غير موجود.")
                return

        body = b""
        replay_receive = receive
        if project_id is None and method not in self.SAFE_METHODS:
            body, replay_receive = await self._read_body(receive)
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
                project_id = payload.get("project_id")
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {}

        if project_id is not None and not self._validate_project(project_id, user_id):
            await self._reject(send, 404, "المشروع غير موجود.")
            return

        if path == "/api/projects" and method == "POST":
            proxy = await self._owner_filtered_send(path, user_id, send)
            await self.app(scope, replay_receive, proxy)
            await proxy.flush()  # type: ignore[attr-defined]
            return

        if method == "GET" and path in self.OWNER_LIST_PATHS and "project_id" not in query:
            proxy = await self._owner_filtered_send(path, user_id, send)
            await self.app(scope, replay_receive, proxy)
            await proxy.flush()  # type: ignore[attr-defined]
            return

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(send: Send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})
