"""Declarative system-model sync (Phase 27) — `culprit.yaml` in, model out.

Was `apply_services.py` (Phase 14), which read a `services:` list and
diffed it against `services`/`service_dependencies`. It reads a
`culprit.yaml` and diffs it against `components`/`connections` now; the
diff-and-apply logic itself lives in `app/model/service.py`'s
`apply_manifest`, which `POST /model/apply` also calls. This script is a
different entry point into that logic, not a second implementation of
what applying a model means.

Newly-issued API keys are printed to stdout, once — the only place they
are ever recoverable, the same rule the HTTP API follows (see
`app/model/schemas.py`'s `ComponentCreateResponse`).

Idempotent: re-running with an unchanged file makes no further writes.
Never disables a component missing from the file unless `--prune` is
passed, and even then it is the same soft delete
`DELETE /model/components/{id}` does by default — historical telemetry is
never touched (see `app/model/service.py::delete_component`).

`--export` prints the current model as a `culprit.yaml` instead of
applying one. `apply` then `--export` then `diff` is Phase 27's second
acceptance criterion, and having both directions behind one command is
what makes that checkable by a person rather than only by a test.

Run via `just apply-model path/to/culprit.yaml` (add `--prune`), or
directly:
`cd api && uv run python -m scripts.apply_model path/to/culprit.yaml`.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Same convention as app/main.py -- this script imports app.model.*
# directly (not app.main), so nothing else loads api/.env for it first.
load_dotenv()

from app.model.manifest import ManifestError, dump_manifest, read_manifest  # noqa: E402
from app.model.service import (  # noqa: E402
    UnknownComponentName,
    apply_manifest,
    export_manifest,
)
from app.registry.config import REGISTRY_ADMIN_DATABASE_URL  # noqa: E402


async def _run_apply(path: Path, *, prune: bool) -> int:
    try:
        manifest = read_manifest(path)
    except ManifestError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    engine = create_async_engine(REGISTRY_ADMIN_DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            try:
                result = await apply_manifest(session, manifest, prune=prune)
            except UnknownComponentName as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
    finally:
        await engine.dispose()

    for name in result.components_created:
        # The key, not just the name: this is the one moment it exists
        # anywhere outside the hash in the database.
        print(f"created component {name}: {result.api_keys.get(name, '<no key>')}")
    for name in result.components_updated:
        print(f"updated component {name}")
    for name in result.components_disabled:
        print(f"disabled component {name} (missing from {path})")
    for label in result.connections_created:
        print(f"created connection {label}")
    for label in result.connections_updated:
        print(f"updated connection {label}")
    for label in result.connections_removed:
        print(f"removed connection {label} (missing from {path})")

    print(
        f"done: {len(result.components_created)} component(s) created, "
        f"{len(result.components_updated)} updated, "
        f"{len(result.components_disabled)} disabled; "
        f"{len(result.connections_created)} connection(s) created, "
        f"{len(result.connections_updated)} updated, "
        f"{len(result.connections_removed)} removed"
    )
    return 0


async def _run_export(merge_from: Path | None) -> int:
    engine = create_async_engine(REGISTRY_ADMIN_DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            manifest = await export_manifest(session)
    finally:
        await engine.dispose()

    # Phase 28: the `extract:` section is NOT stored server-side.
    #
    # Extraction runs in the `culprit` binary against a checkout, with no
    # control plane involved, so nothing in the database knows about it.
    # A plain export therefore cannot reproduce it, and writing that
    # export over a hand-maintained file would delete the user's
    # extractor configuration outright — the same class of defect the
    # Phase 27 audit found in `declared_by`, and the documented
    # `apply-model --export > culprit.yaml` workflow walks straight into
    # it.
    #
    # So: pass the current file and its `extract:` section is carried
    # through; omit it and stderr says plainly what is being dropped.
    # The export never silently loses it either way.
    if merge_from is not None:
        current = read_manifest(merge_from)
        if current.extract is not None:
            manifest = manifest.model_copy(update={"extract": current.extract})
    else:
        print(
            "note: --export does not include an `extract:` section — the control "
            "plane does not store one (docs/DIAGNOSTIC_PLAN.md Phase 28 field 3). "
            "If your culprit.yaml has one, pass it as an argument to carry it "
            "through: apply_model.py --export culprit.yaml",
            file=sys.stderr,
        )

    # stdout only, so `apply_model.py --export > culprit.yaml` and a diff
    # against the applied file are both one shell command.
    print(dump_manifest(manifest), end="")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        help=(
            "culprit.yaml describing the system. With --export, an optional "
            "path to the current file, whose `extract:` section is carried "
            "into the output (the control plane does not store one)."
        ),
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="soft-delete (disable) any component missing from the file",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="print the current model as a culprit.yaml instead of applying one",
    )
    args = parser.parse_args()

    if args.export:
        if args.prune:
            parser.error("--export cannot be combined with --prune")
        raise SystemExit(asyncio.run(_run_export(args.path)))

    if args.path is None:
        parser.error("a culprit.yaml path is required (or pass --export)")
    raise SystemExit(asyncio.run(_run_apply(args.path, prune=args.prune)))


if __name__ == "__main__":
    main()
