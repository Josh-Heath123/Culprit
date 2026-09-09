"""The protocol driver: one JSON object in, one JSON object out.

`docs/EXTRACTOR_PROTOCOL.md` is the contract. This module implements the
side of it that matters most in practice — the failure behaviour.

**Exit zero, always** (short of an unhandled crash, which is the
orchestrator's job to catch). Every source that cannot be read becomes a
`skipped` entry naming what was wanted and why it was not got. Nothing
here raises out to the caller, because a run that fails is a run that
stops, and an extractor's inability to import one framework must not
stop the report on everything else.

**Nothing is written to stdout but the response.** Anything a library
prints on import would corrupt the JSON document the orchestrator is
parsing, so stdout is captured for the duration of the extraction and
redirected to stderr, where it is diagnostic rather than destructive.
This is not hypothetical: Django prints warnings on `setup()`, and
plenty of application modules print on import.
"""

import argparse
import contextlib
import io
import json
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from culprit_model.errors import safe_message
from culprit_model.protocol import (
    EXTRACTOR_PROTOCOL_VERSION,
    ExtractorRequest,
    ExtractorResponse,
    Skip,
    Want,
)

from culprit_extract_python import EXTRACTOR_ID
from culprit_extract_python.discovery import DiscoveryError, discover
from culprit_extract_python.emit import FactBuilder

#: Wants this extractor can answer. Anything else in a request is
#: skipped as unsupported rather than ignored — a newer orchestrator
#: asking an older extractor for something must get an explicit "I do
#: not know how to do that", not silence.
SUPPORTED_WANTS = frozenset(
    {
        Want.HTTP_ROUTES,
        Want.DB_SCHEMA,
        Want.CONFIG_KEYS,
        Want.TEST_ASSERTIONS,
    }
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="culprit-extract-python",
        description=(
            "Culprit intent extractor for Python projects. Reads an extractor "
            "request on stdin and writes a response on stdout; see "
            "docs/EXTRACTOR_PROTOCOL.md."
        ),
    )
    parser.add_argument(
        "--app",
        default=None,
        help=(
            "the application object as module:attribute (e.g. app.main:app). "
            "Without it, conventional locations are tried and the ones that "
            "failed are reported."
        ),
    )
    parser.add_argument(
        "--no-import",
        action="store_true",
        help=(
            "never import the application. Static extraction only — useful "
            "when importing has side effects you do not want in CI."
        ),
    )
    arguments = parser.parse_args(argv)

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _emit(
            ExtractorResponse(
                extractor=EXTRACTOR_ID,
                skipped=(
                    Skip(want="*", reason=f"stdin was not one JSON object: {exc}"),
                ),
            )
        )

    try:
        request = ExtractorRequest.model_validate(payload)
    except Exception as exc:  # any pydantic failure
        return _emit(
            ExtractorResponse(
                extractor=EXTRACTOR_ID,
                skipped=(
                    Skip(want="*", reason=f"the request did not validate: {safe_message(exc)}"),
                ),
            )
        )

    if request.protocol != EXTRACTOR_PROTOCOL_VERSION:
        # Refuse rather than attempt. An extractor that answers a
        # protocol it does not understand is answering a question it may
        # be misreading, and a wrong fact is worse than a missing one.
        return _emit(
            ExtractorResponse(
                extractor=EXTRACTOR_ID,
                skipped=(
                    Skip(
                        want="*",
                        reason=(
                            f"orchestrator speaks protocol {request.protocol}; "
                            f"this extractor speaks {EXTRACTOR_PROTOCOL_VERSION}"
                        ),
                    ),
                ),
            )
        )

    return _emit(run(request, app_target=arguments.app, allow_import=not arguments.no_import))


def run(
    request: ExtractorRequest, *, app_target: str | None = None, allow_import: bool = True
) -> ExtractorResponse:
    """Performs the extraction described by `request`."""
    root = Path(request.root).resolve()
    component = request.component or root.name
    builder = FactBuilder(
        component=component,
        # A placeholder id: the orchestrator re-stamps every fact with
        # the real capture id, because only it knows what capture this
        # run is part of. Generating one here keeps `Fact` constructible
        # standalone, which is what makes this extractor testable
        # without an orchestrator.
        capture_id=_placeholder_capture_id(),
        captured_at=datetime.now(UTC),
        extractor=EXTRACTOR_ID,
    )

    wants = list(request.want) or sorted(SUPPORTED_WANTS)
    facts: list[Any] = []
    skipped: list[Skip] = []

    unsupported = [want for want in wants if want not in SUPPORTED_WANTS]
    for want in unsupported:
        skipped.append(
            Skip(
                want=str(want),
                reason=f"{EXTRACTOR_ID} does not extract {want}",
                extractor=EXTRACTOR_ID,
            )
        )
    wants = [want for want in wants if want in SUPPORTED_WANTS]

    # stdout belongs to the protocol from here until the response is
    # written. Anything an imported module prints goes to stderr.
    noise = io.StringIO()
    with contextlib.redirect_stdout(noise):
        app = None
        if allow_import and ({Want.HTTP_ROUTES, Want.DB_SCHEMA} & set(wants)):
            try:
                app = discover(root, app_target)
                builder.app_target = app.target
            except DiscoveryError as exc:
                app = None
                for want in (Want.HTTP_ROUTES, Want.DB_SCHEMA):
                    if want in wants:
                        skipped.append(
                            Skip(want=str(want), reason=str(exc), extractor=EXTRACTOR_ID)
                        )
            except Exception as exc:  # importing user code
                app = None
                for want in (Want.HTTP_ROUTES, Want.DB_SCHEMA):
                    if want in wants:
                        skipped.append(
                            Skip(
                                want=str(want),
                                reason=f"importing the application raised {safe_message(exc)}",
                                extractor=EXTRACTOR_ID,
                            )
                        )
        elif not allow_import and ({Want.HTTP_ROUTES, Want.DB_SCHEMA} & set(wants)):
            for want in (Want.HTTP_ROUTES, Want.DB_SCHEMA):
                if want in wants:
                    skipped.append(
                        Skip(
                            want=str(want),
                            reason=(
                                "--no-import was passed; runtime introspection "
                                "was not attempted"
                            ),
                            extractor=EXTRACTOR_ID,
                        )
                    )

        for want in wants:
            produced, problem = _extract_one(want, root, app, builder)
            facts.extend(produced)
            if problem is not None:
                skipped.append(problem)

    if noise.getvalue().strip():
        print(noise.getvalue(), file=sys.stderr)

    return ExtractorResponse(
        extractor=EXTRACTOR_ID,
        facts=tuple(facts),
        skipped=tuple(skipped),
    )


def _extract_one(
    want: Want, root: Path, app: Any, builder: FactBuilder
) -> tuple[list[Any], Skip | None]:
    """Runs one want, converting any failure into a Skip.

    The broad `except Exception` is deliberate and is the honesty rule
    from `.claude/rules/model.md` in code: an extractor never fails the
    run. A traceback is put in the reason so the gap is diagnosable, and
    the other wants still run.
    """
    try:
        if want is Want.HTTP_ROUTES:
            if app is None:
                return [], None  # already skipped at discovery
            from culprit_extract_python.routes import extract_routes
            facts = extract_routes(app.obj, app.framework, builder)
            if not facts:
                return [], Skip(
                    want=str(want),
                    reason=f"{app.framework} application at {app.target} declares no routes",
                    extractor=EXTRACTOR_ID,
                )
            return facts, None

        if want is Want.DB_SCHEMA:
            return _database_facts(root, app, builder)

        if want is Want.CONFIG_KEYS:
            from culprit_extract_python.static_scan import extract_config_keys
            facts = extract_config_keys(root, builder)
            if not facts:
                return [], Skip(
                    want=str(want),
                    reason="no os.environ / os.getenv read with a literal key was found",
                    extractor=EXTRACTOR_ID,
                )
            return facts, None

        if want is Want.TEST_ASSERTIONS:
            from culprit_extract_python.static_scan import (
                extract_test_assertions,
            )

            facts = extract_test_assertions(root, builder)
            if not facts:
                return [], Skip(
                    want=str(want),
                    reason="no test asserting a status code next to a client call was found",
                    extractor=EXTRACTOR_ID,
                )
            return facts, None
    except Exception as exc:  # see docstring
        # safe_message, not f"{exc}": a pydantic ValidationError renders
        # the input it rejected, and this reason travels inside the
        # capture bundle — the artefact §5 promises is safe to attach to
        # a bug report. See culprit_model.errors.
        return [], Skip(
            want=str(want),
            reason=f"{safe_message(exc)} ({_where(exc)})",
            extractor=EXTRACTOR_ID,
        )
    return [], None


def _database_facts(root: Path, app: Any, builder: FactBuilder) -> tuple[list[Any], Skip | None]:
    """Schema and migration head, each degrading on its own."""
    facts: list[Any] = []
    reasons: list[str] = []

    if app is not None:
        try:
            from culprit_extract_python.database import extract_schema
            schema = extract_schema(builder)
            if schema:
                facts.extend(schema)
            else:
                reasons.append("no SQLAlchemy metadata was reachable from the imported app")
        except Exception as exc:
            reasons.append(f"reading SQLAlchemy metadata raised {safe_message(exc)}")

    try:
        from culprit_extract_python.database import extract_migration_head
        head = extract_migration_head(root, builder)
        if head:
            facts.extend(head)
        else:
            reasons.append("no alembic.ini found; migration head not read")
    except ImportError:
        reasons.append("alembic is not installed; migration head not read")
    except Exception as exc:
        reasons.append(f"reading the alembic head raised {safe_message(exc)}")

    if facts:
        # Partial success is reported as success plus nothing: the facts
        # that were got are real, and a Skip alongside them would say a
        # want was missed when it was half met. The half that was missed
        # shows as an absent subject, which is what Phase 29 compares.
        return facts, None
    return [], Skip(
        want=str(Want.DB_SCHEMA),
        reason="; ".join(reasons) or "no database schema found",
        extractor=EXTRACTOR_ID,
    )


def _where(exc: BaseException) -> str:
    """The last frame of a traceback, for a one-line reason."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "no traceback"
    last = frames[-1]
    return f"{last.filename}:{last.lineno}"


def _placeholder_capture_id() -> UUID:
    return uuid4()


def _emit(response: ExtractorResponse) -> int:
    """Writes the response and returns the exit code — always zero.

    Zero even when everything was skipped. The orchestrator reads the
    `skipped` list; a non-zero exit would make it synthesise its own
    generic skips and throw away the specific reasons this extractor
    worked out.
    """
    sys.stdout.write(response.model_dump_json())
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
