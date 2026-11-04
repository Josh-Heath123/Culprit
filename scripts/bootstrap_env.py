"""Generate infra/.env.prod (Phase 17).

Runs on the target machine only — never in CI (docs/SELF_HOSTED_PLAN.md's
Phase 17, invariant 5: secrets never enter CI). Composes every
`*_DATABASE_URL` from the role passwords it generates, so the two can
never drift from each other by hand-editing one and not the other — that
drift was the single most tedious/error-prone part of the original
Phase 11 setup.

Two modes:
  --local   DOMAIN=localhost, IMAGE_REGISTRY points at locally built
            images (docker-compose.quickstart.yml builds them, doesn't
            pull), no keys at all — `just quickstart` uses this.
  (default) Prompts for DOMAIN and, optionally, VOYAGE_API_KEY (postmortem
            embedding for search). This is the real-VM path documented in
            docs/INSTALL.md.

No LLM key is asked for: since Phase 32 part 2 nothing in Culprit calls a
model (the incident narrative job was removed).

Every generated value is escaped ($ -> $$) unconditionally before being
written, regardless of which mode produced it or whether the user typed
it — this is the exact footgun that corrupted OPERATOR_PASSWORD_HASH
during Phase 11 (see infra/.env.prod.example's header comment) and it
must never again be a human's job to remember.
"""

import argparse
import getpass
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PROD_PATH = REPO_ROOT / "infra" / ".env.prod"

#: (env var name, role/purpose) -- generated with secrets.token_urlsafe(32).
#: JWT_SECRET_KEY isn't a DB role password but belongs in the same
#: generate-and-escape pass; keeping it in this list is what guarantees
#: it goes through the same $ -> $$ escaping as everything else.
GENERATED_SECRETS: list[tuple[str, str]] = [
    ("POSTGRES_PASSWORD", "Postgres superuser"),
    ("INGESTION_WRITER_PASSWORD", "ingestion-writer role"),
    ("API_READER_PASSWORD", "api-reader role"),
    ("INGEST_GATEWAY_DB_PASSWORD", "ingest-gateway role"),
    ("ANOMALY_DETECTOR_DB_PASSWORD", "anomaly-detector role"),
    ("CORRELATION_ENGINE_DB_PASSWORD", "correlation-engine role"),
    ("ROOT_CAUSE_WRITER_DB_PASSWORD", "root-cause-writer role"),
    ("REGISTRY_ADMIN_DB_PASSWORD", "registry-admin role"),
    ("AUTH_SERVICE_DB_PASSWORD", "auth-service role"),
    ("POSTMORTEM_WRITER_DB_PASSWORD", "postmortem-writer role"),
    ("JWT_SECRET_KEY", "JWT signing key"),
    ("AGENT_AUTOMATION_TOKEN", "AI change-capture hook (Phase 21)"),
    ("MCP_READER_DB_PASSWORD", "mcp-reader role (Phase 24)"),
    ("FACT_WRITER_DB_PASSWORD", "fact-writer role (Phase 28)"),
    ("CAPTURE_WRITER_DB_PASSWORD", "capture-writer role (Phase 30)"),
    ("PROBE_WRITER_DB_PASSWORD", "probe-writer role (Phase 31)"),
    ("INVESTIGATION_WRITER_DB_PASSWORD", "investigation-writer role (Phase 32)"),
    ("CULPRIT_PROJECT_TOKEN", "capture upload token (Phase 28)"),
]

#: DB name/user for a fresh install. Deliberately "culprit", not
#: "signalstack" -- docs/SELF_HOSTED_PLAN.md Phase 17 Known Trap 2: the
#: live culprit.co.za database is still named "signalstack" and renaming
#: it is a data migration, not a config edit, so this script must never
#: run against that database. It only ever writes a brand-new .env.prod.
DB_NAME = "culprit"


def _escape_dollars(value: str) -> str:
    return value.replace("$", "$$")


def _gen_password() -> str:
    # token_urlsafe output never contains '$', but every value still goes
    # through _escape_dollars unconditionally below -- see module
    # docstring for why that must not be conditional on the source.
    return secrets.token_urlsafe(32)


def _db_url(role: str, password: str, db_host: str) -> str:
    return f"postgresql+asyncpg://{role}:{password}@{db_host}:5432/{DB_NAME}"


def _prompt(label: str, *, default: str | None = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    reader = getpass.getpass if secret else input
    value = reader(f"{label}{suffix}: ").strip()
    return value or (default or "")


def build_env(*, local: bool, domain: str | None) -> tuple[dict[str, str], str]:
    """Returns (env vars to write, admin password to print) -- the admin
    password is generated here (not by create_user.py, which has no
    non-interactive input path by design -- see api/scripts/create_user.py's
    own docstring) so the quickstart bootstrap step can pipe it into
    create_user.py's stdin without ever putting it on a command line."""
    passwords = {name: _gen_password() for name, _ in GENERATED_SECRETS}

    env: dict[str, str] = {}
    env["POSTGRES_USER"] = DB_NAME
    env["POSTGRES_PASSWORD"] = passwords["POSTGRES_PASSWORD"]
    env["POSTGRES_DB"] = DB_NAME
    env["DASHBOARD_DATABASE_URL"] = _db_url(DB_NAME, passwords["POSTGRES_PASSWORD"], "postgres")
    env["REDIS_URL"] = "redis://redis:6379"

    env["INGESTION_WRITER_PASSWORD"] = passwords["INGESTION_WRITER_PASSWORD"]
    env["API_READER_PASSWORD"] = passwords["API_READER_PASSWORD"]

    env["INGEST_GATEWAY_DB_PASSWORD"] = passwords["INGEST_GATEWAY_DB_PASSWORD"]
    env["INGEST_GATEWAY_DATABASE_URL"] = _db_url(
        "ingest-gateway", passwords["INGEST_GATEWAY_DB_PASSWORD"], "postgres"
    )
    # Fresh install onboards its own services via the registry API /
    # `just apply-services` -- these three stay blank, exactly like
    # infra/.env.prod.example's own default (Phase 14 loosening).
    env["ORDER_SERVICE_API_KEY"] = ""
    env["INVENTORY_SERVICE_API_KEY"] = ""
    env["PAYMENTS_SERVICE_API_KEY"] = ""

    env["REGISTRY_ADMIN_DB_PASSWORD"] = passwords["REGISTRY_ADMIN_DB_PASSWORD"]
    env["REGISTRY_ADMIN_DATABASE_URL"] = _db_url(
        "registry-admin", passwords["REGISTRY_ADMIN_DB_PASSWORD"], "postgres"
    )

    env["INGEST_RATE_LIMIT"] = "600/minute"
    env["INGEST_MAX_BODY_BYTES"] = "5MB"

    env["ANOMALY_DETECTOR_DB_PASSWORD"] = passwords["ANOMALY_DETECTOR_DB_PASSWORD"]
    env["ANOMALY_DATABASE_URL"] = _db_url(
        "anomaly-detector", passwords["ANOMALY_DETECTOR_DB_PASSWORD"], "postgres"
    )

    env["CORRELATION_ENGINE_DB_PASSWORD"] = passwords["CORRELATION_ENGINE_DB_PASSWORD"]
    env["CORRELATION_DATABASE_URL"] = _db_url(
        "correlation-engine", passwords["CORRELATION_ENGINE_DB_PASSWORD"], "postgres"
    )

    env["ROOT_CAUSE_WRITER_DB_PASSWORD"] = passwords["ROOT_CAUSE_WRITER_DB_PASSWORD"]
    env["ROOT_CAUSE_DATABASE_URL"] = _db_url(
        "root-cause-writer", passwords["ROOT_CAUSE_WRITER_DB_PASSWORD"], "postgres"
    )

    if local:
        env["VOYAGE_API_KEY"] = ""
        print(
            "--local mode: no VOYAGE_API_KEY set. Postmortems are stored but not "
            "embedded for search until it is set in infra/.env.prod and the stack "
            "is restarted. Nothing else needs a key.",
            file=sys.stderr,
        )
    else:
        env["VOYAGE_API_KEY"] = _prompt(
            "VOYAGE_API_KEY (optional; embeds postmortems for search)", secret=True
        )

    env["API_READER_DATABASE_URL"] = _db_url(
        "api-reader", passwords["API_READER_PASSWORD"], "postgres"
    )
    resolved_domain = domain or ("localhost" if local else _prompt("DOMAIN"))
    env["CORS_ALLOW_ORIGINS"] = (
        f"http://{resolved_domain}" if local else f"https://{resolved_domain}"
    )

    env["JWT_SECRET_KEY"] = passwords["JWT_SECRET_KEY"]
    env["JWT_EXPIRY_MINUTES"] = "60"

    # OPERATOR_* stay blank: the quickstart/local-VM admin is created by
    # create_user.py (via the bootstrap step for --local, or `just
    # create-user` for a real install), not the single-operator env-var
    # backfill -- see api/migrations/versions/fbf4cb16570a_create_users_table.py.
    env["OPERATOR_USERNAME"] = ""
    env["OPERATOR_PASSWORD_HASH"] = ""

    env["AUTH_SERVICE_DB_PASSWORD"] = passwords["AUTH_SERVICE_DB_PASSWORD"]
    env["AUTH_SERVICE_DATABASE_URL"] = _db_url(
        "auth-service", passwords["AUTH_SERVICE_DB_PASSWORD"], "postgres"
    )

    # Phase 18: postmortem-writer role. Required by
    # api/migrations/versions/35b434e21f5c_postmortem_write_path.py's
    # _require_env -- without this, `alembic upgrade head` in the
    # quickstart bootstrap service (infra/docker-compose.quickstart.yml)
    # raises RuntimeError and the whole quickstart flow fails.
    env["POSTMORTEM_WRITER_DB_PASSWORD"] = passwords["POSTMORTEM_WRITER_DB_PASSWORD"]
    env["POSTMORTEM_WRITER_DATABASE_URL"] = _db_url(
        "postmortem-writer", passwords["POSTMORTEM_WRITER_DB_PASSWORD"], "postgres"
    )

    # Phase 21 (docs/AI_NATIVE_PLAN.md): not a DB role password, like
    # JWT_SECRET_KEY above -- the shared bearer credential
    # .claude/hooks/capture_ai_change.sh authenticates POST
    # /ai-change-records with. Optional at the application layer
    # (api/app/auth/config.py reads it with a blank default, not
    # os.environ[...]), but generated here unconditionally anyway so the
    # hook works out of the box on a fresh install rather than silently
    # doing nothing until someone notices and sets it by hand.
    env["AGENT_AUTOMATION_TOKEN"] = passwords["AGENT_AUTOMATION_TOKEN"]

    # Phase 24 (docs/AI_NATIVE_PLAN.md): mcp-reader role -- read-only for
    # mcp_server/, the local stdio MCP server. Required at migration time
    # (that phase's own migration's _require_env), same reasoning as
    # POSTMORTEM_WRITER_DB_PASSWORD above.
    env["MCP_READER_DB_PASSWORD"] = passwords["MCP_READER_DB_PASSWORD"]
    env["MCP_READER_DATABASE_URL"] = _db_url(
        "mcp-reader", passwords["MCP_READER_DB_PASSWORD"], "postgres"
    )

    # Phase 28 (docs/DIAGNOSTIC_PLAN.md): fact-writer role -- the only
    # role that may INSERT into captures/intent_facts, used by
    # POST /facts/captures. Required at migration time (that phase's own
    # migration's _require_env), same reasoning as
    # POSTMORTEM_WRITER_DB_PASSWORD above.
    env["FACT_WRITER_DB_PASSWORD"] = passwords["FACT_WRITER_DB_PASSWORD"]
    env["FACT_WRITER_DATABASE_URL"] = _db_url(
        "fact-writer", passwords["FACT_WRITER_DB_PASSWORD"], "postgres"
    )

    # Phase 30: capture-writer -- the only role that may INSERT into
    # configured_facts, used by POST /captures. A separate role from
    # fact-writer because what a running environment is configured to do
    # (production included) is a different trust domain from what a
    # repository says about itself. Required at migration time.
    env["CAPTURE_WRITER_DB_PASSWORD"] = passwords["CAPTURE_WRITER_DB_PASSWORD"]
    env["CAPTURE_WRITER_DATABASE_URL"] = _db_url(
        "capture-writer", passwords["CAPTURE_WRITER_DB_PASSWORD"], "postgres"
    )

    # Phase 31: probe-writer -- the only role that may INSERT into
    # readings, used by POST /readings and by the worker's anomaly job.
    # A separate role again rather than a reuse: a credential that posts
    # readings is one that already had reach into a running environment.
    # Required at migration time.
    env["PROBE_WRITER_DB_PASSWORD"] = passwords["PROBE_WRITER_DB_PASSWORD"]
    env["PROBE_WRITER_DATABASE_URL"] = _db_url(
        "probe-writer", passwords["PROBE_WRITER_DB_PASSWORD"], "postgres"
    )
    # Phase 32 part 2: investigation-writer -- INSERT on the five
    # investigation tables and nothing else, behind POST /investigations.
    env["INVESTIGATION_WRITER_DB_PASSWORD"] = passwords["INVESTIGATION_WRITER_DB_PASSWORD"]
    env["INVESTIGATION_WRITER_DATABASE_URL"] = _db_url(
        "investigation-writer", passwords["INVESTIGATION_WRITER_DB_PASSWORD"], "postgres"
    )

    # Phase 28: the project token `culprit` presents to POST
    # /facts/captures. Not a DB role password (like JWT_SECRET_KEY and
    # AGENT_AUTOMATION_TOKEN above) -- a shared bearer credential for an
    # unattended CLI run, deliberately not a user JWT, because the caller
    # is CI and has no session to log in with.
    env["CULPRIT_PROJECT_TOKEN"] = passwords["CULPRIT_PROJECT_TOKEN"]

    env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = ""

    env["WORKER_INGESTION_DATABASE_URL"] = _db_url(
        "ingestion-writer", passwords["INGESTION_WRITER_PASSWORD"], "postgres"
    )

    # frontend/Caddyfile's site address is `{$DOMAIN:localhost}` --
    # Caddy only skips automatic HTTPS/Let's-Encrypt when the site
    # address has an explicit scheme, so --local mode writes the full
    # `http://localhost` (plain HTTP, matching the quickstart acceptance
    # criterion of a working dashboard at http://localhost with no TLS
    # involved) while a real domain stays bare so Caddy's automatic
    # Let's Encrypt still kicks in. CORS_ALLOW_ORIGINS above intentionally
    # uses the bare `resolved_domain`, not this value.
    env["DOMAIN"] = f"http://{resolved_domain}" if local else resolved_domain
    if local:
        env["IMAGE_REGISTRY"] = ""
        env["IMAGE_TAG"] = ""
    else:
        # ghcr.io/josh-heath123/culprit, not .../view: the repository was
        # renamed from `View` to `Culprit` in Phase 20 and the images have
        # been published under the new path since. This still said `view`,
        # so every non-local bootstrap produced a .env.prod whose
        # `docker compose pull` reached for images that are not there
        # (Phase 26 truth repair, docs/DIAGNOSTIC_PLAN.md).
        env["IMAGE_REGISTRY"] = "ghcr.io/josh-heath123/culprit"
        env["IMAGE_TAG"] = "latest"

    # Written into .env.prod (0600, never committed, same as every other
    # secret here) so the quickstart compose's one-shot `bootstrap`
    # service can read it via its own env_file: and pipe it into
    # create_user.py's stdin -- see infra/docker-compose.quickstart.yml.
    # Blank for a real-VM install: docs/SELF_HOSTED_PLAN.md Phase 17
    # Known Trap 4 requires the admin password be *prompted for* there,
    # via `just create-user` on the host, not generated/printed.
    admin_password = _gen_password() if local else ""
    env["QUICKSTART_ADMIN_USERNAME"] = "admin" if local else ""
    env["QUICKSTART_ADMIN_PASSWORD"] = admin_password
    return env, admin_password


def render_env_file(env: dict[str, str]) -> str:
    lines = [
        "# Generated by scripts/bootstrap_env.py -- see that file before hand-editing.",
        "# Every value below has already been $ -> $$ escaped for Docker Compose's",
        "# env_file interpolation (see infra/.env.prod.example's header comment).",
        "",
    ]
    for name, value in env.items():
        lines.append(f"{name}={_escape_dollars(value)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="generate a local-quickstart env")
    parser.add_argument("--domain", help="domain for a real-VM install (skips the prompt)")
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing infra/.env.prod"
    )
    args = parser.parse_args()

    if ENV_PROD_PATH.exists() and not args.force:
        print(
            f"error: {ENV_PROD_PATH} already exists. Pass --force to overwrite it "
            "(this will invalidate every existing session/API key derived from its secrets).",
            file=sys.stderr,
        )
        return 1

    env, admin_password = build_env(local=args.local, domain=args.domain)

    ENV_PROD_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PROD_PATH.write_text(render_env_file(env))
    ENV_PROD_PATH.chmod(0o600)

    print(f"wrote {ENV_PROD_PATH} (mode 0600)")
    print(f"generated {len(GENERATED_SECRETS)} secrets; no secret value is printed above.")
    if args.local:
        # Handed to docker-compose.quickstart.yml's bootstrap service via
        # QUICKSTART_ADMIN_PASSWORD, piped into create_user.py's stdin --
        # never passed as a CLI arg. Printed once, to stdout, specifically
        # because Known Trap 4 says the quickstart path (unlike
        # docs/INSTALL.md's real-VM path, which always prompts) is allowed
        # to print a generated admin password to a local terminal.
        print(f"QUICKSTART_ADMIN_PASSWORD={admin_password}")
        print("next: just quickstart-up")
    else:
        print(
            "next: docker compose -f infra/docker-compose.prod.yml "
            "--env-file infra/.env.prod config"
        )
        print("      then follow docs/INSTALL.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
