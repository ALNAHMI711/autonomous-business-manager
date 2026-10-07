# Security Policy

## Scope

Autonomous Business Manager is a private automation/control application. Production
deployment must be treated as a security-sensitive service because it can operate
browser sessions, external integrations, uploaded files, and encrypted credentials.

## Required production controls

Before exposing the service to the public Internet:

1. Set `APP_ENV=production` and keep `DEBUG=false`.
2. Use a strong, unique `SESSION_SECRET` and `CSRF_SECRET`.
3. Configure a valid `ENCRYPTION_KEY` and protect it outside the repository.
4. Use a strong administrator credential. Do not commit plaintext credentials.
5. Serve the application through HTTPS. The included Caddy configuration is intended
   to terminate TLS and reverse-proxy the application.
6. Keep the application container non-root (the Docker image uses a dedicated
   `appuser`).
7. Do not expose port 8000 directly to the Internet; expose the reverse proxy.
8. Keep database, browser-profile, upload, and proxy credentials on protected
   server storage with appropriate filesystem permissions.
9. Configure an operational backup schedule and periodically perform a restore test.
10. Protect the GitHub default branch with required CI/review checks before treating
    the repository as production-controlled.

## Authentication and authorization

- Sessions are persisted and associated with a durable user identity.
- Project-scoped operations are checked against project ownership at the API boundary.
- Global controls, global network profiles, network testing, secret-panel unlock,
  and system status are administrator-only while their underlying records remain
  global.
- Kill-switch control is administrator-only.
- Sensitive automation must remain behind the application's approval and execution
  gates.

## Secrets

Never place API keys, passwords, session secrets, encryption keys, proxy credentials,
Telegram tokens, or similar credentials in Git.

The repository's `.env.example` is documentation only. Production secrets should
be injected through the deployment environment or a dedicated secret manager.

Stored application secrets are encrypted. API responses and masked network-profile
views must not expose secret values.

## Browser automation

Browser targets must remain restricted by the application's URL policy. Do not use
the application to bypass CAPTCHAs, defeat access controls, spoof browser identity,
or perform unauthorized actions.

Uploads must be treated as untrusted input. Filenames are normalized before storage;
uploaded content must not be executed as code.

## Network routing

A configured public IP is not a source-IP override. Public egress changes require
an actual VPN, proxy, or other operating-system/network route.

Network policies are fail-closed when configured to require them. Global network
profiles remain administrator-only until project/user ownership is implemented for
those profiles.

## Reporting a vulnerability

Do not publish credentials, tokens, private URLs, or exploit details in a public issue.
For a suspected vulnerability, preserve the minimum evidence needed to reproduce it
and report it privately to the repository owner.

If a credential may have been exposed, revoke/rotate it immediately before continuing
development.

## Production status

Passing CI is not equivalent to production readiness. The remaining production gates
are tracked in `docs/PRODUCTION_SECURITY_GATES.md`, including deployment verification,
operational backup/restore testing, and repository governance.
