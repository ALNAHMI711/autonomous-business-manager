from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add conservative browser security headers to every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
            "form-action 'self'; object-src 'none'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
        )
        if request.url.scheme == "https":
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
