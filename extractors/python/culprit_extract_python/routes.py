"""HTTP route extraction by runtime introspection (rank 90).

Why introspection rather than parsing decorators: every framework here
registers routes at import time through code. FastAPI's
`include_router(prefix=...)`, Flask's blueprints, Django's `include()`
— a static parser sees `@router.post("/orders")` and has no idea the
router is mounted at `/api/v1`. Asking the running app is the only way
to get the path a request will actually match, which is the only path
worth comparing anything against.

Each framework's reader is guarded: an ImportError or an unexpected
internal shape produces a skip with the reason, never an exception out
of the extractor.
"""

from collections.abc import Iterable
from typing import Any

from culprit_model import build
from culprit_model.planes import ConfidenceRank, SourceKind
from culprit_model.protocol import Predicate

from culprit_extract_python.emit import FactBuilder

#: Methods a framework reports that describe no application behaviour.
#: Flask and Django add these automatically to every rule, and emitting
#: them would triple the route count with facts nobody wrote.
IMPLICIT_METHODS = frozenset({"HEAD", "OPTIONS"})


def extract_routes(app: object, framework: str, builder: FactBuilder) -> list[Any]:
    """Dispatches to the right reader. Raises nothing — see module doc."""
    if framework == "fastapi":
        return _fastapi_routes(app, builder)
    if framework == "flask":
        return _flask_routes(app, builder)
    if framework == "django":
        return _django_routes(app, builder)
    return []


# --- FastAPI ------------------------------------------------------------


def _fastapi_routes(app: Any, builder: FactBuilder) -> list[Any]:
    """Reads `app.openapi()`.

    The generated document, not `app.routes`, and the difference is the
    point: `openapi()` resolves prefixes, response models and pydantic
    request schemas into one description, which is exactly the interface
    Culprit models (D6). Walking `app.routes` would give the paths but
    none of the shape.

    Rank 90, not 80: this is what the running application says about
    itself, and it is what a committed `openapi.json` is a possibly-stale
    copy of. When the two disagree, Phase 29 has an `intent_conflict` to
    report — which is often the actual bug.
    """
    document = app.openapi()
    paths = document.get("paths") or {}
    facts: list[Any] = []

    for path in sorted(paths):
        operations = paths[path] or {}
        for method in sorted(operations):
            if method.upper() in IMPLICIT_METHODS or not isinstance(operations[method], dict):
                continue
            operation = operations[method]
            subject = build(
                "http", component=builder.component, method=method, path=path
            )
            locator = f"$.paths.{path}.{method}"
            facts.append(
                builder.fact(
                    subject,
                    Predicate.EXISTS,
                    {"path": path, "method": method.upper()},
                    source_kind=SourceKind.INTROSPECTION,
                    artefact=builder.app_target,
                    locator=locator,
                    rank=ConfidenceRank.RUNTIME_INTROSPECTION,
                )
            )

            responses = operation.get("responses") or {}
            if responses:
                facts.append(
                    builder.fact(
                        subject,
                        Predicate.STATUS_CODES,
                        sorted(str(code) for code in responses),
                        source_kind=SourceKind.INTROSPECTION,
                        artefact=builder.app_target,
                        locator=locator,
                        rank=ConfidenceRank.RUNTIME_INTROSPECTION,
                    )
                )

            body = operation.get("requestBody")
            if isinstance(body, dict):
                aspect = build(
                    "http",
                    component=builder.component,
                    method=method,
                    path=path,
                    aspect="request.body",
                )
                content = body.get("content") or {}
                facts.append(
                    builder.fact(
                        aspect,
                        Predicate.REQUEST_SCHEMA,
                        {
                            "required": bool(body.get("required", False)),
                            "content_types": sorted(content),
                        },
                        source_kind=SourceKind.INTROSPECTION,
                        artefact=builder.app_target,
                        locator=locator,
                        rank=ConfidenceRank.RUNTIME_INTROSPECTION,
                    )
                )
    return facts


# --- Flask --------------------------------------------------------------


def _flask_routes(app: Any, builder: FactBuilder) -> list[Any]:
    """Reads `app.url_map`.

    Flask has no OpenAPI document, so this is routes only — no request
    or response shape. That is an honest partial answer rather than an
    invented one: guessing a schema from a view function's signature is
    the kind of inference D6 rules out.

    `rule.rule` carries Werkzeug's `<int:id>` converter syntax, which
    `canonical_path` already normalises to `{}` — one of the four
    conventions it is table-tested against.
    """
    facts: list[Any] = []
    rules = sorted(app.url_map.iter_rules(), key=lambda rule: (rule.rule, rule.endpoint))
    for rule in rules:
        if rule.rule.startswith("/static/"):
            # Flask registers this itself on every app. It is framework
            # furniture, not this system's intent.
            continue
        methods = sorted((rule.methods or set()) - IMPLICIT_METHODS)
        for method in methods:
            subject = build("http", component=builder.component, method=method, path=rule.rule)
            facts.append(
                builder.fact(
                    subject,
                    Predicate.EXISTS,
                    {"path": rule.rule, "method": method, "endpoint": rule.endpoint},
                    source_kind=SourceKind.INTROSPECTION,
                    artefact=builder.app_target,
                    locator=rule.endpoint,
                    rank=ConfidenceRank.RUNTIME_INTROSPECTION,
                )
            )
    return facts


# --- Django -------------------------------------------------------------


def _django_routes(app: Any, builder: FactBuilder) -> list[Any]:
    """Walks the root URLconf's resolver.

    Django's route patterns are `RoutePattern` (`<int:pk>`) or
    `RegexPattern` (`^orders/(?P<pk>[0-9]+)/$`), and `canonical_path`
    handles both — the second is the one the canonicaliser's own tests
    call out as the awkward case, since a naive "cut at the ?" would turn
    it into `/orders/(`.

    Methods are not reported: a Django URLconf does not know them (a
    class-based view's `http_method_names` does, and reaching into every
    view class to ask is the kind of implementation-level analysis D6
    excludes). Each route is emitted once under the `*` method, which is
    an honest "this path exists, methods unknown".
    """
    from django.urls import get_resolver  # optional, guarded by the caller

    facts: list[Any] = []
    for pattern, prefix in sorted(_walk_django(get_resolver(), ""), key=lambda item: item[1]):
        subject = build("http", component=builder.component, method="*", path=prefix)
        facts.append(
            builder.fact(
                subject,
                Predicate.EXISTS,
                {"path": prefix, "method": "*", "name": getattr(pattern, "name", None)},
                source_kind=SourceKind.INTROSPECTION,
                artefact=builder.app_target,
                locator=str(getattr(pattern, "name", "") or ""),
                rank=ConfidenceRank.RUNTIME_INTROSPECTION,
            )
        )
    return facts


def _walk_django(resolver: Any, prefix: str) -> Iterable[tuple[Any, str]]:
    for entry in getattr(resolver, "url_patterns", []):
        here = prefix + str(entry.pattern)
        if hasattr(entry, "url_patterns"):
            yield from _walk_django(entry, here)
        else:
            yield entry, "/" + here.lstrip("^/")
