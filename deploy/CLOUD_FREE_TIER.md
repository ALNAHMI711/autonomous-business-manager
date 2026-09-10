# Cloud deployment — free/always-free options

## Primary target: Oracle Cloud Always Free

Oracle Cloud currently documents Always Free compute resources that do not expire. The documented allowance includes up to two AMD micro VMs or an Ampere A1 Flex allocation equivalent to 2 OCPUs and 12 GB RAM, subject to region/capacity limits. Oracle also documents that idle Always Free compute can be reclaimed when it remains below its utilization thresholds for seven days.

Recommended layout:

`Internet -> HTTPS reverse proxy -> FastAPI container -> SQLite/data volume`

For a larger production deployment later:

`Internet -> HTTPS -> reverse proxy -> FastAPI -> PostgreSQL/Redis -> workers`

### Oracle setup

1. Create one Oracle Cloud Free Tier account using the official signup flow.
2. Select the home region carefully; Always Free compute is tied to the home region.
3. Create an Always Free Ubuntu VM.
4. Open only SSH and HTTPS in the cloud firewall. Do not expose SQLite or internal services.
5. Install Docker and Docker Compose.
6. Clone this repository and create `.env` from `.env.example`.
7. Start with `docker compose up -d --build`.
8. Put a real TLS reverse proxy in front of port 8000.
9. Configure backups before treating the VM as the only copy of business data.

## Secondary option: Google Cloud Free Tier

Google documents a non-expiring free usage allowance for one e2-micro Compute Engine VM per month, 30 GB standard persistent disk and 1 GB monthly outbound transfer, with region restrictions. This is smaller than the Oracle A1 option and is better treated as a fallback/control-plane host for this application.

## Important limitation

No provider can honestly guarantee that a free VM will be available forever without capacity, account, policy, or service changes. "Always Free" means the provider's documented eligible resources have no scheduled expiration; it does not mean unlimited resources or a contractual guarantee of uninterrupted service.

## Safety for this project

- LIVE trading must remain OFF until the production security gates pass.
- Store secrets only in environment/secret storage; never commit them.
- Use HTTPS and secure cookies in production.
- Keep SSH restricted and use key authentication.
- Enable automatic security updates where appropriate.
- Keep a second backup of the SQLite database.
- The free VM is infrastructure only; it does not bypass exchange, country, network, or platform policies.
