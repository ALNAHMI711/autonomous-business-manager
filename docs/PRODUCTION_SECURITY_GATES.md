# Production Security Gates

This checklist tracks the remaining security gates before production deployment.

## Verified in the current `main`

- Project ownership is enforced at the middleware boundary.
- Global network-profile, network-test, secrets-unlock, and system-status routes are restricted to the bootstrap administrator through an explicit allowlist.
- Kill-switch control is administrator-only.
- Global events are administrator-only; project events are filtered by project ownership.
- Uploaded filenames are normalized and stored with generated prefixes.
- Network profile masking does not expose stored passwords.
- Admin user creation rolls back the ownership row when credential provisioning fails.
- Approval/work-card mutation paths are covered by project ownership checks at the API boundary.
- Browser open/navigate/click/fill/close operations are covered by project ownership checks at the API boundary.
- Events integration tests prove normal-user filtering of foreign/global events and administrator visibility of global events.
- CI has compile and pytest gates.

## Remaining gates

1. **Secrets ownership model** — the current `secrets` table is global. Keep secret management administrator-only until project/user-scoped ownership is implemented.
2. **Network profile ownership model** — profiles are global. Keep profile management administrator-only until project/user-scoped ownership is implemented.
3. **Deployment hardening** — production HTTPS, secure cookies, CSRF secret, secret injection, database backup/restore, and monitoring must be verified in an actual deployment environment.
4. **Repository governance** — protect `main` with required CI checks and prevent direct unreviewed production changes. Branch-protection state could not be verified through the currently connected GitHub integration.

No item in this document should be interpreted as evidence that production deployment is complete; each remaining gate requires verification.
