from __future__ import annotations

from typing import Awaitable, Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.csrf import CSRFProtector


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_PATHS = {"/api/login", "/health", "/api/health"}


class CSRFSecurityMiddleware:
    """Enforce same-origin/CSRF protection for authenticated unsafe requests."""

    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self.protector = CSRFProtector(secret)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        cookies = _parse_cookies(headers.get("cookie", ""))
        session = cookies.get("session", "")

        if method not in SAFE_METHODS and path not in EXEMPT_PATHS and session:
            origin = headers.get("origin")
            host = headers.get("host", "")
            referer = headers.get("referer")
            csrf_token = headers.get("x-csrf-token")

            same_origin = False
            if origin:
                same_origin = _origin_matches_host(origin, host)
            elif referer:
                same_origin = _origin_matches_host(referer, host)

            token_valid = self.protector.verify(session, csrf_token)
            if not same_origin and not token_valid:
                await _send_json(send, 403, "طلب مرفوض بسبب حماية CSRF.")
                return

        async def send_with_token(message: Message) -> None:
            if message.get("type") == "http.response.start" and session:
                token = self.protector.issue(session)
                raw_headers = list(message.get("headers", []))
                raw_headers.append((b"x-csrf-token", token.encode("ascii")))
                message = dict(message)
                message["headers"] = raw_headers
            await send(message)

        await self.app(scope, receive, send_with_token)


def _parse_cookies(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in raw.split(";"):
        if "=" not in item:
            continue
        key, value = item.strip().split("=", 1)
        result[key] = value
    return result


def _origin_matches_host(origin_or_url: str, host: str) -> bool:
    value = origin_or_url.strip().rstrip("/")
    if not value or not host:
        return False
    if "://" not in value:
        return False
    authority = value.split("://", 1)[1].split("/", 1)[0]
    return authority.lower() == host.lower()


async def _send_json(send: Send, status: int, detail: str) -> None:
    body = ('{"detail":"' + detail.replace('"', '\\"') + '"}').encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
