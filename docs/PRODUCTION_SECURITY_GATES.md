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
- A SQLite online-backup utility is included at `deploy/backup_database.py`; it performs an integrity check and refuses to overwrite an existing backup.
- A SQLite restore utility is included at `deploy/restore_database.py`; it validates the source and restored database and refuses to overwrite an existing destination unless explicitly forced.

- Network profiles are owner-scoped: each user manages only their own profiles through `/api/network/my-profiles`, a project can only bind or use profiles owned by its own owner, and the administrator's global profiles stay admin-only. A network policy that names a profile the project owner does not have fails closed (`required_network_profile_missing`) instead of silently connecting directly.
- The browser now actually receives the project's bound proxy when a session is opened (previously only the profile name was recorded).
- `ProjectAccessMiddleware` validates every project id a request carries (path, query and JSON body), closing a bypass where an owned id in the query string hid a victim's id in the body.
- Per-user secrets: see gate 1 below (now implemented).
- `deploy/restore_drill.py` proves backup -> restore round-trips with matching row counts; `deploy/verify_deployment.py` black-box checks HTTPS redirect, HSTS/security headers, unauthenticated access to protected/admin endpoints and session-cookie flags on a live host.

## Remaining gates

1. **Secrets ownership model** — implemented. `secrets.owner_id` is added by an idempotent migration that backfills network-profile secrets from their `u<id>` name (un-prefixed = administrator, id 1). Users manage their own secrets through `/api/my-secrets` (list metadata / put / delete); values are never returned over HTTP and are decrypted only server-side via `UserSecretStore.reveal`. Names are validated so a user cannot spoof another user's `user_secret:u<id>:` namespace. The global `/api/secrets/unlock` remains administrator-only.
2. **Network profile ownership model** — implemented (owner namespace + project binding checks). Existing profiles remain the administrator's global profiles.
3. **Deployment hardening** — production HTTPS, secure cookies, CSRF secret, secret injection, database backup/restore, and monitoring must be verified in an actual deployment environment. The repository contains backup/restore primitives, a restore drill and a deployment verifier, but they must still be **run on the target host**: install the cron entry from `deploy/backup-cron.example`, run `python deploy/restore_drill.py` there, and run `python deploy/verify_deployment.py https://<domain> --login` against the live site. Record the results here when done.
4. **Repository governance** — protect `main` with required CI checks and prevent direct unreviewed production changes. Checked on 2026-10-21: `main` is **not protected** (GitHub API returns "Branch not protected"). Enable required status check `test` and require pull requests before production use.

No item in this document should be interpreted as evidence that production deployment is complete; each remaining gate requires verification.
