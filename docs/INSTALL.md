# Installing Culprit on your own VM

This is the real-deployment path — a domain you control, TLS, and CI/CD
pushing every `main` commit to it automatically. If you just want to try
Culprit locally first, use `just quickstart` instead (see the
[README](../README.md)); nothing here is required for that.

Total time: 15-20 minutes, most of it waiting on DNS propagation.

## 1. Provision a VM

Any VM running Ubuntu 22.04 with a public IPv4 address works — this was
built and verified against an Oracle Cloud Always Free instance
(`docs/IMPLEMENTATION_PLAN.md` §7), but Hetzner, DigitalOcean, or anything
else that gives you root SSH access is equally fine. You need at least
2 vCPU / 4GB RAM — Postgres, Redis, the API, the worker, and the frontend
all run on this one box.

Install Docker + the Compose plugin on it (Docker's own convenience
script is the fastest path for a fresh Ubuntu box):

```bash
curl -fsSL https://get.docker.com | sh
```

## 2. Open the firewall / security group

Inbound, from anywhere: **22** (SSH), **80** and **443** (HTTP/HTTPS —
Caddy needs 80 open for the Let's Encrypt ACME challenge, not just 443).
Nothing else needs to be public — `ingest-gateway` is reachable only
through Caddy's `/ingest/*` proxy on 80/443 (Phase 15), never on its own
port.

## 3. Point a domain at it

Create a DNS **A record** for the domain you'll use, pointing at the VM's
public IP. Caddy's automatic Let's Encrypt cannot issue a certificate for
a bare IP address — you need a real domain name, even a cheap/free
subdomain is fine. Give it a few minutes to propagate before continuing;
`dig your-domain.com` should return the VM's IP.

## 4. Generate `infra/.env.prod`

`infra/.env.prod` is created once, by hand, on the VM — never by CI, never
committed (see `infra/.env.prod.example`'s header comment for why). Clone
the repo somewhere on the VM to run the generator from (this does **not**
need to be the same directory CI deploys into — see step 6):

```bash
git clone https://github.com/Josh-Heath123/Culprit.git ~/culprit-repo
cd ~/culprit-repo
just bootstrap-env --domain your-domain.com
```

(No `just`? The recipe is one line —
`MSYS_NO_PATHCONV=1 docker run --rm -it -v "$(pwd):/repo" -w /repo python:3.12-slim python scripts/bootstrap_env.py --domain your-domain.com` —
the `MSYS_NO_PATHCONV` prefix only matters on Windows Git Bash, harmless elsewhere.)

This prompts for `LLM_PROVIDER` (gemini or anthropic), the matching API
key, and `VOYAGE_API_KEY` (needed for root-cause narratives — without it,
incidents still appear, just without a root-cause hypothesis), generates
every database-role password and the JWT signing key, and writes
`infra/.env.prod` with mode `0600`. No secret value is ever printed to the
terminal in this mode (contrast with `just quickstart`'s local path, which
does print a generated admin password — see Known Trap 4 in
`docs/SELF_HOSTED_PLAN.md` Phase 17 for why that split is deliberate).

Move the generated file to where the deploy step (step 6) expects it:

```bash
mkdir -p ~/culprit
cp ~/culprit-repo/infra/.env.prod ~/culprit/.env.prod
```

## 5. Wire up GitHub Actions

In your fork's repo settings → Secrets and variables → Actions, add:

| Secret | Value |
| --- | --- |
| `SSH_HOST` | the VM's public IP or hostname |
| `SSH_USER` | the SSH user (e.g. `ubuntu`) |
| `SSH_PRIVATE_KEY` | a private key whose public half is in that user's `~/.ssh/authorized_keys` on the VM |
| `SSH_PORT` | optional, defaults to 22 |

`.github/workflows/ci-cd.yml`'s `deploy` job only runs on pushes to
`main`, after lint/typecheck/pytest/Trivy all pass, and copies
`infra/docker-compose.prod.yml` + `infra/deploy.sh` to `~/culprit` on the
VM (flattened — they land as `~/culprit/docker-compose.prod.yml` and
`~/culprit/deploy.sh`, not under an `infra/` subdirectory) before running
`deploy.sh` there over SSH. It never touches `.env.prod`.

Published images are pulled from `ghcr.io/<your-github-username>/culprit/*`
— if your fork's GitHub Packages default to private, either flip them to
public (Packages → visibility) or `docker login ghcr.io` on the VM once
with a **classic** PAT that has `read:packages` scope (fine-grained PATs
don't support Packages access — confirmed against GitHub's own docs
during Phase 11).

## 6. Push to `main`

CI builds and pushes the three images, then SSHes into the VM and runs
`deploy.sh`: pull → `alembic upgrade head` → restart containers → health
check (`https://your-domain.com/api/incidents` and
`https://your-domain.com/ingest/healthz`, polled for up to a minute —
the first-ever Let's Encrypt issuance is the slow part). A green
`deploy` job means the stack is live.

## 7. Create the first admin user

A fresh install has no operator env-var backfill and no quickstart
bootstrap service (that only exists in `docker-compose.quickstart.yml`) —
you create the first admin yourself, once, directly against the running
`api` image:

```bash
cd ~/culprit
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm api \
  python -m scripts.create_user admin --role admin
```

This prompts for a password interactively (never as a command-line
argument — see `api/scripts/create_user.py`'s own docstring). Log in at
`https://your-domain.com` with it. Use `POST /users` (or the `/settings/users`
page once logged in) to invite anyone else — `create_user.py` is
deliberately the *only* way to create the very first admin from
zero, so there's never a window where an unauthenticated endpoint could
create one.

## 8. Onboard your own services

Point your services' OTel exporters at
`https://your-domain.com/ingest` — see
[`docs/INSTRUMENTATION.md`](INSTRUMENTATION.md) for the exact env vars and
a copy-pasteable Python example. Register each service and get its API
key either through `/settings/services` in the dashboard or
`just apply-model your-culprit.yaml` (see that command's own `--help` for
the file shape, and `demo-services/culprit.yaml` for a worked example)
run from your own machine against
`REGISTRY_ADMIN_DATABASE_URL` — check `infra/.env.prod` on the VM for that
value if you're running it remotely, or SSH in and run it there.

## Upgrading

Every push to `main` redeploys automatically (step 6). `infra/.env.prod`
is never touched by a deploy — a new required env var (a future phase
adding one) needs a manual one-line addition to it before that deploy,
documented in that phase's own notes when it happens.

## If something goes wrong

- **Health check fails on `deploy.sh`'s first run**: almost always a cold
  Let's Encrypt issuance racing the health check's retry budget (12
  attempts, 5s apart — see `infra/deploy.sh`'s own comments) or a DNS
  record that hasn't propagated yet. Re-run `./deploy.sh` on the VM by
  hand once DNS resolves.
- **`docker compose pull` fails on the VM**: see the GHCR visibility note
  in step 5.
- **Rolling back**: redeploy the previous image tag (`IMAGE_TAG` in
  `.env.prod`, or re-run the workflow for an earlier commit) and, if that
  commit's migration needs it, `docker compose -f docker-compose.prod.yml
  --env-file .env.prod run --rm api alembic downgrade -1` on the VM by
  hand — each phase's own docs note in `docs/SELF_HOSTED_PLAN.md` states
  whether its migration is safe to downgrade against real data.
