"""Declarative service-registry sync (Phase 14).

Reads a YAML file describing the desired set of services, diffs it
against the `services`/`service_dependencies`/`api_keys` tables, and
applies creates/updates through the exact same functions
api/app/registry/service.py's HTTP router uses -- this script is a
different entry point into that logic, not a second implementation of
"what a service create/update means". Newly-issued API keys are printed
to stdout, once, the only place they're ever recoverable (same rule as
the HTTP API's response -- see app/registry/schemas.py's
ServiceCreateResponse).

Idempotent: re-running with an unchanged file makes no further writes.
Never deletes a service missing from the file unless --prune is passed,
and even then it's the same soft delete (disabled_at) DELETE /services/{id}
does by default -- historical telemetry is never touched (see
app/registry/service.py::delete_service's own docstring).

File shape:

    services:
      - name: checkout-api
        display_name: Checkout API
        depends_on: [inventory-api, payments-api]
        monitored_metrics: [http.server.duration, http.server.errors]
      - name: inventory-api
        depends_on: []

Run via `just apply-services path/to/services.yaml` (add `--prune` to
prune) or directly:
`cd api && uv run python -m scripts.apply_services path/to/services.yaml`.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Same convention as app/main.py / app/ingest_gateway/main.py -- this
# script imports app.registry.* directly (not app.main), so nothing else
# loads api/.env for it first.
load_dotenv()

from app.registry.config import REGISTRY_ADMIN_DATABASE_URL  # noqa: E402
from app.registry.schemas import ServiceCreate, ServiceOut, ServicePatch  # noqa: E402
from app.registry.service import (  # noqa: E402
    UnknownDependency,
    create_service,
    delete_service,
    list_services,
    patch_service,
)


def _load_desired(path: Path) -> dict[str, ServiceCreate]:
    raw = yaml.safe_load(path.read_text())
    if not raw or "services" not in raw:
        raise ValueError(f"{path}: expected a top-level 'services:' list")
    return {entry["name"]: ServiceCreate(**entry) for entry in raw["services"] or []}


def _diff_patch(existing: ServiceOut, desired: ServiceCreate) -> dict:
    """Only the fields that actually differ from what's already in the
    DB -- ServicePatch's exclude_unset=True (see app/registry/schemas.py)
    means an omitted field is left alone, and patch_service() rewrites
    every service_dependencies edge whenever `depends_on` is present at
    all, so including a field here that hasn't actually changed would
    still be harmless but is needless churn on every run."""
    fields: dict = {}
    if desired.display_name != existing.display_name:
        fields["display_name"] = desired.display_name
    if sorted(desired.monitored_metrics) != sorted(existing.monitored_metrics):
        fields["monitored_metrics"] = desired.monitored_metrics
    if sorted(desired.depends_on) != sorted(existing.depends_on):
        fields["depends_on"] = desired.depends_on
    return fields


async def apply_services(path: Path, *, prune: bool) -> int:
    try:
        desired_by_name = _load_desired(path)
    except (ValidationError, ValueError) as exc:
        print(f"invalid {path}:\n{exc}", file=sys.stderr)
        return 1

    engine = create_async_engine(REGISTRY_ADMIN_DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    created_count = 0
    updated_count = 0
    pruned_count = 0
    failed = False

    try:
        async with session_factory() as session:
            existing = {s.name: s for s in await list_services(session)}

            # Pass 1: create every missing service first, with depends_on
            # deferred to pass 2. A file listing two new, mutually-
            # unaware-of-order services (A depends_on B, both new) would
            # otherwise fail creating A before B exists in the DB at all
            # -- deferring every edge to a second pass, once every
            # name in the file is guaranteed to exist, sidesteps ordering
            # entirely rather than requiring the file to be topologically
            # sorted.
            for name, desired in desired_by_name.items():
                if name in existing:
                    continue
                to_create = ServiceCreate(
                    name=desired.name,
                    display_name=desired.display_name,
                    monitored_metrics=desired.monitored_metrics,
                    depends_on=[],
                )
                service, api_key = await create_service(session, to_create)
                existing[name] = service
                created_count += 1
                print(f"created {name}: {api_key}")

            # Pass 2: apply display_name/monitored_metrics/depends_on
            # diffs -- covers both services just created above (which
            # still need their real depends_on applied) and pre-existing
            # ones whose declared state has drifted from the file.
            for name, desired in desired_by_name.items():
                current = existing[name]
                fields = _diff_patch(current, desired)
                if not fields:
                    continue
                try:
                    await patch_service(session, current.id, ServicePatch(**fields))
                except UnknownDependency as exc:
                    print(f"error: {name}: {exc}", file=sys.stderr)
                    failed = True
                    continue
                updated_count += 1
                print(f"updated {name}: {', '.join(fields)}")

            if prune:
                for name, service in existing.items():
                    if name not in desired_by_name and not service.disabled:
                        await delete_service(session, service.id, purge=False)
                        pruned_count += 1
                        print(f"disabled {name} (missing from {path})")
    finally:
        await engine.dispose()

    print(f"done: {created_count} created, {updated_count} updated, {pruned_count} disabled")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="YAML file listing desired services")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="soft-delete (disable) any registered service missing from the file",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(apply_services(args.path, prune=args.prune)))


if __name__ == "__main__":
    main()
