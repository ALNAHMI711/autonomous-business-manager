# Autonomous Business Manager — Engineering Audit

## Current baseline
The system is a FastAPI + SQLite + Playwright Arabic RTL business automation platform with an Agent, approval flow, task manager, connectivity monitor, encrypted secrets, browser sessions, static code analysis, notifications and a dashboard. The current repository structure exposes these components under `app/` and the Arabic dashboard under `frontend/`.

## Current strengths
- FastAPI API and SQLite persistence with foreign keys, WAL and busy timeout.
- Fernet encryption for stored secrets and PBKDF2-HMAC-SHA256 password utilities.
- Playwright browser automation with HTTPS/localhost URL restrictions.
- Human approval states and controlled browser operations.
- Connectivity monitoring with pause/resume callbacks.
- Arabic RTL frontend and project/work-card concepts.

## Critical gaps found
1. `app/main.py` contained indentation defects in the project request model and project creation endpoint.
2. Authentication sessions are held in memory and therefore do not survive process restart.
3. There is no mature persistent worker/queue architecture yet; execution currently relies on in-process asyncio tasks.
4. There was no reliable automated test suite or CI gate in the baseline.
5. Browser network routing was not configurable per project.
6. Rate limiting, persistent sessions, RBAC, execution verification and recovery policy need production hardening.
7. A true VPN cannot be created by the web application; VPN routing remains an OS/device function. The application can use the device route or an explicit HTTP/HTTPS/SOCKS5 proxy.

## Network feature design
The intended network policy is:

`Project -> Network Profile -> Browser Context -> OS/mobile-data route or proxy`

Profiles:
- `direct`: no proxy; uses the host's normal route. When running on Termux over phone mobile data, this uses the phone's network path.
- `proxy`: HTTP, HTTPS or SOCKS5 proxy with optional credentials and bypass list.

Credentials are stored through the existing encrypted secrets mechanism and are never returned in plaintext by the profile listing API.

The browser implementation will use Playwright browser-context proxy support. Playwright documents HTTP(S) and SOCKS proxies as a supported `proxy` option for browser contexts.

## Delivery plan
### P0 — reliability and security
- Fix syntax/indentation defects.
- Add tests and CI.
- Harden authentication and persistent sessions.
- Add rate limiting.
- Add persistent queue/worker semantics.
- Add tool permissions and execution verification.

### P1 — autonomous execution
- Structured planner and tool bus.
- Retry/recovery policies.
- Goal and memory tracking.
- Multi-step workflow state.
- Network profile selection per project.
- Business connector isolation.

### P2 — production scale
- PostgreSQL/Redis option.
- Background workers.
- Observability and metrics.
- RBAC and audit controls.
- Webhooks/external API.
- Deployment packaging and rollback strategy.

## Acceptance gates
Every phase must pass:
1. Syntax/compile check.
2. Unit/API tests.
3. CI workflow.
4. Security review.
5. Browser/network smoke test where applicable.
6. Commit and commit-SHA verification.
7. End-to-end UI acceptance before production deployment.

## Important operational distinction
Adding an IP address to a field does not make it the phone's public source IP. To change the public egress IP, the runtime must use a proxy, a VPN, or another network route that owns that IP. The application therefore exposes explicit proxy routing rather than pretending a destination IP is a source IP.
