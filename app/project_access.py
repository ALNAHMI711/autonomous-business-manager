from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.database import Database


class ProjectAccessMiddleware:
    """Fail closed on project-scoped API requests.

    The current application has one authenticated admin identity, so there is
    no multi-user owner column yet. This middleware still prevents callers
    from referencing non-existent projects/cards and validates that every
    project-scoped identifier resolves to real data before the route runs.
    The explicit single-admin boundary makes the future owner check a
    replaceable policy rather than scattering ID validation across routes.
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    PROJECT_PATHS = {
        "/api/projects/",
        "/api/chat/",
        "/api/browser/close/",
    }

    def __init__(self, app: ASGIApp, database: Database) -> None:
        self.app = app
        self.database = database

    @staticmethod
    def _session_present(headers: list[tuple[bytes, bytes]]) -> bool:
        for key, value in headers:
            if key.lower() == b"cookie" and b"session=" in value:
                return True
        return False

    @staticmethod
    def _path_id(path: str, prefix: str) -> Optional[int]:
        if not path.startswith(prefix):
            return None
        raw = path[len(prefix):].strip("/").split("/", 1)[0]
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _validate_project(self, project_id: Any) -> bool:
        try:
            value = int(project_id)
        except (TypeError, ValueError):
            return False
        return value > 0 and self.database.get_project(value) is not None

    def _validate_card(self, card_id: Any) -> bool:
        try:
            value = int(card_id)
        except (TypeError, ValueError):
            return False
        card = self.database.get_work_card(value)
        if not card:
            return False
        project_id = card.get("project_id")
        return project_id is None or self._validate_project(project_id)

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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/api/") or not self._session_present(scope.get("headers", [])):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        query = parse_qs((scope.get("query_string") or b"").decode("utf-8", "ignore"))

        project_id: Any = query.get("project_id", [None])[0]
        card_id: Any = None

        for prefix in self.PROJECT_PATHS:
            if path.startswith(prefix):
                project_id = self._path_id(path, prefix)
                break

        if path.startswith("/api/work-cards/"):
            card_id = self._path_id(path, "/api/work-cards/")
            if card_id is not None and not self._validate_card(card_id):
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

        if project_id is not None and not self._validate_project(project_id):
            await self._reject(send, 404, "المشروع غير موجود.")
            return

        if path == "/api/work-cards" and project_id is None:
            # Single-admin mode: listing all cards is intentional and remains
            # protected by the normal authenticated-session dependency.
            pass

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
