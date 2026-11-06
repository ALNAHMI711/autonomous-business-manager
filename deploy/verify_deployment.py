#!/usr/bin/env python3
"""Black-box production checks for a deployed instance (HTTPS, headers, auth).

Usage (from any machine that can reach the site):
  python deploy/verify_deployment.py https://your-domain.example
  ADMIN_PASSWORD=... python deploy/verify_deployment.py https://your-domain.example --login

Checks:
  * plain HTTP redirects to HTTPS (or is not served)
  * HTTPS health endpoint answers 200
  * HSTS and the standard security headers are present
  * protected and admin-only endpoints refuse unauthenticated requests
  * with --login: the session cookie is Secure, HttpOnly and SameSite
Exit status 0 means every check passed.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import sys
from urllib.parse import urlparse

REQUIRED_HEADERS = (
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
    "content-security-policy",
    "referrer-policy",
)

PROTECTED_PATHS = (
    "/api/projects",
    "/api/network/profiles",
    "/api/network/my-profiles",
    "/api/secrets/unlock",
    "/api/system/status",
    "/api/events",
    "/api/control/kill-switch",
)


def evaluate_headers(headers: dict[str, str]) -> list[str]:
    lowered = {key.lower(): value for key, value in headers.items()}
    problems = [f"missing header: {name}" for name in REQUIRED_HEADERS if name not in lowered]
    hsts = lowered.get("strict-transport-security", "")
    if hsts:
        try:
            max_age = int(hsts.split("max-age=", 1)[1].split(";", 1)[0])
        except (IndexError, ValueError):
            max_age = 0
        if max_age < 15552000:
            problems.append("HSTS max-age is shorter than 180 days")
    return problems


def evaluate_cookie(set_cookie: str) -> list[str]:
    lowered = set_cookie.lower()
    problems = []
    if "secure" not in [part.strip() for part in lowered.split(";")]:
        problems.append("session cookie is missing Secure")
    if "httponly" not in lowered:
        problems.append("session cookie is missing HttpOnly")
    if "samesite=" not in lowered:
        problems.append("session cookie is missing SameSite")
    return problems


def _request(scheme: str, host: str, port: int | None, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None):
    if scheme == "https":
        connection = http.client.HTTPSConnection(host, port or 443, timeout=15, context=ssl.create_default_context())
    else:
        connection = http.client.HTTPConnection(host, port or 80, timeout=15)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        return response.status, response.getheaders(), data
    finally:
        connection.close()


def run(base_url: str, login_password: str | None) -> list[str]:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ["base URL must be https://<domain>"]
    host, port = parsed.hostname, parsed.port
    problems: list[str] = []

    try:
        status, headers, _ = _request("http", host, None, "GET", "/api/health")
        location = dict((k.lower(), v) for k, v in headers).get("location", "")
        if status not in (301, 302, 307, 308) or not location.startswith("https://"):
            problems.append(f"plain HTTP is served without redirecting to HTTPS (status {status})")
    except OSError:
        pass  # port 80 closed is acceptable

    status, headers, _ = _request("https", host, port, "GET", "/api/health")
    if status != 200:
        problems.append(f"HTTPS /api/health returned {status}")
    problems.extend(evaluate_headers(dict(headers)))

    for path in PROTECTED_PATHS:
        status, _, _ = _request("https", host, port, "GET", path)
        if status not in (401, 403):
            problems.append(f"{path} answered {status} to an unauthenticated request")

    if login_password:
        payload = json.dumps({"username": "admin", "password": login_password}).encode()
        status, headers, _ = _request(
            "https", host, port, "POST", "/api/login", payload,
            {"Content-Type": "application/json", "Origin": f"https://{parsed.netloc}"},
        )
        cookies = [value for key, value in headers if key.lower() == "set-cookie" and value.startswith("session=")]
        if status != 200 or not cookies:
            problems.append(f"login failed (status {status}); cannot verify cookie flags")
        else:
            problems.extend(evaluate_cookie(cookies[0]))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--login", action="store_true", help="also log in as admin using $ADMIN_PASSWORD")
    args = parser.parse_args(argv)

    password = os.environ.get("ADMIN_PASSWORD") if args.login else None
    if args.login and not password:
        print("FAIL: --login needs the ADMIN_PASSWORD environment variable", file=sys.stderr)
        return 2

    problems = run(args.base_url, password)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("PASS: deployment checks succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
