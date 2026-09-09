"""Rendering a validation failure without rendering what failed.

`str(pydantic.ValidationError)` includes an `input_value=...` for each
error. That is exactly the right default for a library and exactly the
wrong one here: the input to a rejected `ValueShape` field can be the
config value the whole type exists to keep out of reach.

    ValueShape(type="postgresql://u:hunter2@db/orders", ...)
    # ValidationError: ... input_value='postgresql://u:hunter2@db/orders'

At the HTTP boundary `api/app/errors.py` already strips it. This is the
same protection for everywhere else — chiefly the extractor plugins,
whose broad `except Exception` turns a failure into a `skipped` reason,
and a `skipped` reason travels *inside the capture bundle*. A bundle is
the artefact §5 promises is safe to attach to a bug report, so a
credential arriving in it through an error message would defeat the
promise as thoroughly as one arriving in a fact.

No call site does that today — `ValueShape` is only ever built by `of()`,
`absent()` and `unknown()`, none of which can put a value in a field. The
point is that the guarantee should not depend on that staying true.

    except Exception as exc:
        skipped.append(Skip(want=..., reason=safe_message(exc)))
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError


def safe_message(exc: BaseException) -> str:
    """A one-line description of `exc` that never echoes an input value.

    For a `ValidationError`, renders each error as `location: message`
    using `include_input=False`. For anything else, `str(exc)` — those
    are this codebase's own exceptions, whose messages are written not to
    carry values (see `culprit_model.facts` and `subjects.SubjectError`).
    """
    if not isinstance(exc, ValidationError):
        return f"{type(exc).__name__}: {exc}"

    rendered: list[str] = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
        rendered.append(f"{location}: {error.get('msg', 'invalid')}")
    return f"{type(exc).__name__}: " + "; ".join(rendered)


def safe_errors(exc: ValidationError) -> list[Mapping[str, Any]]:
    """`exc.errors()` with the echoed input and context removed."""
    return list(exc.errors(include_url=False, include_context=False, include_input=False))
