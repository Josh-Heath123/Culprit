"""Subject URIs — the join key of the whole model.

docs/DIAGNOSTIC_PLAN.md §2.3 and Phase 26's field 7:
`culprit_model.subjects.build()` is the *only* sanctioned way to
construct a subject URI. Comparison only works if two sources describing
the same thing produce the same string, and the single reliable way to
guarantee that is to have exactly one function that knows the format.
Direct string formatting of a subject anywhere else is a lint failure —
`scripts/tests/test_subject_construction.py` scans for it.

    component:orders-svc
    connection:orders-svc->payments-svc
    http:orders-svc/POST /api/v1/orders
    http:orders-svc/POST /api/v1/orders#request.body
    config:orders-svc/DATABASE_URL
    schema:orders-db/public.orders
    schema:orders-db/public.orders.total_cents
    dep:orders-svc/stripe
    image:orders-svc
    auth:orders-svc->payments-svc/audience

A Go implementation lives at `cli/internal/model/subjects.go` from Phase
28 and shares a conformance fixture with this one (§2.3). The fixture is
`shared/tests/subject_conformance.json`, written here so the Go side has
something to be conformant *to*, rather than the two being written
independently and reconciled afterwards.
"""

from enum import StrEnum
from typing import Any

from culprit_model.canonical import (
    canonical_component,
    canonical_identifier,
    canonical_method,
    canonical_path,
)


class SubjectKind(StrEnum):
    COMPONENT = "component"
    CONNECTION = "connection"
    HTTP = "http"
    CONFIG = "config"
    SCHEMA = "schema"
    DEP = "dep"
    IMAGE = "image"
    AUTH = "auth"


#: The `from->to` separator inside a connection/auth subject. A component
#: name can never contain it, which is what makes parse() unambiguous.
_ARROW = "->"

_ASPECT = "#"


class SubjectError(ValueError):
    """Raised for a subject that cannot be built or parsed.

    Deliberately loud. A silently-mangled subject is worse than a crash:
    it produces a Fact that will never compare equal to the thing it is
    actually about, and the resulting "no divergence found" is a false
    negative nobody investigates.
    """


#: Characters that mean something structural inside a subject, per part.
#: A part containing one of its own separators is rejected rather than
#: embedded: `build("http", component="ns/orders", ...)` would otherwise
#: produce `http:ns/orders/GET /x`, which parses back as component `ns`
#: and method `orders/GET` without raising anything. That is precisely
#: the silently-mangled subject SubjectError exists to prevent — and
#: component names are user-controlled (an OTel `service.name`, a
#: registry row someone typed, a `namespace/name` pair).
#:
#: `path` is absent deliberately: `canonical_path` already strips `?`
#: and `#`, and `/` is what a path is made of. `aspect` allows `.`
#: (`request.body` is the plan's own example) but not `#`.
#: Tokens, not characters: the connection separator is the two-character
#: `->`, and forbidding `-` on its own would reject `orders-svc`, which
#: is what almost every component in this project is called.
_ARROW_SEPARATED = ("/", _ARROW, _ASPECT, " ")
_DOT_SEPARATED = ("/", ".", _ASPECT, " ")

_FORBIDDEN_IN_PART: dict[str, tuple[str, ...]] = {
    "name": _ARROW_SEPARATED,
    "component": _ARROW_SEPARATED,
    "from_component": _ARROW_SEPARATED,
    "to_component": _ARROW_SEPARATED,
    "database": _ARROW_SEPARATED,
    # `/` is deliberately absent here, unlike every other name-shaped
    # part. `_parse_dep` partitions on the *first* `/`, so
    # `dep:web/@babel/parser` parses back as component `web`,
    # dependency `@babel/parser` — it round-trips exactly. Forbidding
    # `/` here silently dropped every scoped npm package and every Go
    # module path, which is most of the dependencies in a real
    # repository (found in Phase 28, against this repo's own frontend).
    # The conformance fixture pins both round trips.
    "dependency": (_ARROW, _ASPECT, " "),
    "key": ("/", _ASPECT, " "),
    "namespace": _DOT_SEPARATED,
    "table": _DOT_SEPARATED,
    "column": _DOT_SEPARATED,
    "aspect": ("/", _ASPECT, " "),
}


def build(kind: "SubjectKind | str", **parts: Any) -> str:
    """Constructs a canonical subject URI.

    Every part is canonicalised on the way in (see `canonical.py`), so a
    caller passing `"Order-Service"` and one passing `"order-service"`
    produce the same subject. Unknown, missing, or separator-bearing
    parts raise `SubjectError` rather than producing a subject that looks
    well-formed and parses back into something else.
    """
    kind = SubjectKind(kind)
    expected = _REQUIRED[kind] | _OPTIONAL[kind]
    unexpected = set(parts) - expected
    if unexpected:
        raise SubjectError(
            f"{kind}: unexpected part(s) {sorted(unexpected)}; expected {sorted(expected)}"
        )
    missing = {name for name in _REQUIRED[kind] if not str(parts.get(name, "")).strip()}
    if missing:
        raise SubjectError(f"{kind}: missing required part(s) {sorted(missing)}")
    for name, value in parts.items():
        # Checked against the *trimmed* value: surrounding whitespace is
        # something every builder strips anyway (`"  Orders-SVC "` is a
        # supported input), whereas a space *inside* a component name
        # would break the `METHOD path` split and must be rejected.
        candidate = str(value).strip()
        offending = sorted(
            {token for token in _FORBIDDEN_IN_PART.get(name, ()) if token in candidate}
        )
        if offending:
            raise SubjectError(
                f"{kind}: part {name}={value!r} contains subject separator(s) "
                f"{offending} — it would parse back as something else"
            )
    return _BUILDERS[kind](parts)


def parse(subject: str) -> tuple[SubjectKind, dict[str, str]]:
    """The inverse of `build`, for reporting and severity computation.

    `build(*parse(s))` returns `s` for every subject `build` produced —
    asserted as a round-trip property over the conformance fixture, which
    is what keeps the two halves from drifting apart.
    """
    scheme, separator, rest = subject.partition(":")
    if not separator:
        raise SubjectError(f"not a subject URI (no scheme): {subject!r}")
    try:
        kind = SubjectKind(scheme)
    except ValueError as exc:
        raise SubjectError(f"unknown subject kind {scheme!r} in {subject!r}") from exc
    return kind, _PARSERS[kind](rest, subject)


# --- builders ---------------------------------------------------------


def _build_component(parts: dict[str, Any]) -> str:
    return f"component:{canonical_component(parts['name'])}"


def _build_connection(parts: dict[str, Any]) -> str:
    source = canonical_component(parts["from_component"])
    target = canonical_component(parts["to_component"])
    return f"connection:{source}{_ARROW}{target}"


def _build_http(parts: dict[str, Any]) -> str:
    component = canonical_component(parts["component"])
    method = canonical_method(parts["method"])
    path = canonical_path(parts["path"])
    subject = f"http:{component}/{method} {path}"
    aspect = str(parts.get("aspect", "")).strip()
    return f"{subject}{_ASPECT}{aspect}" if aspect else subject


def _build_config(parts: dict[str, Any]) -> str:
    # The key is trimmed but not case-folded: environment variable names
    # are case-sensitive on every platform this runs on, and folding them
    # would merge two genuinely distinct keys into one subject.
    return f"config:{canonical_component(parts['component'])}/{str(parts['key']).strip()}"


def _build_schema(parts: dict[str, Any]) -> str:
    database = canonical_component(parts["database"])
    namespace = canonical_identifier(str(parts.get("namespace") or "public"))
    table = canonical_identifier(parts["table"])
    dotted = f"{namespace}.{table}"
    column = str(parts.get("column", "")).strip()
    if column:
        dotted = f"{dotted}.{canonical_identifier(column)}"
    return f"schema:{database}/{dotted}"


def _build_dep(parts: dict[str, Any]) -> str:
    component = canonical_component(parts["component"])
    return f"dep:{component}/{canonical_component(parts['dependency'])}"


def _build_image(parts: dict[str, Any]) -> str:
    return f"image:{canonical_component(parts['component'])}"


def _build_auth(parts: dict[str, Any]) -> str:
    source = canonical_component(parts["from_component"])
    target = canonical_component(parts["to_component"])
    aspect = str(parts["aspect"]).strip()
    return f"auth:{source}{_ARROW}{target}/{aspect}"


# --- parsers ----------------------------------------------------------


def _split_arrow(rest: str, subject: str) -> tuple[str, str]:
    source, separator, target = rest.partition(_ARROW)
    if not separator or not source or not target:
        raise SubjectError(f"expected 'from{_ARROW}to' in {subject!r}")
    return source, target


def _parse_component(rest: str, subject: str) -> dict[str, str]:
    if not rest:
        raise SubjectError(f"empty component name in {subject!r}")
    return {"name": rest}


def _parse_connection(rest: str, subject: str) -> dict[str, str]:
    source, target = _split_arrow(rest, subject)
    return {"from_component": source, "to_component": target}


def _parse_http(rest: str, subject: str) -> dict[str, str]:
    component, separator, remainder = rest.partition("/")
    if not separator:
        raise SubjectError(f"expected 'component/METHOD path' in {subject!r}")
    remainder, aspect_separator, aspect = remainder.partition(_ASPECT)
    method, method_separator, path = remainder.partition(" ")
    if not method_separator:
        raise SubjectError(f"expected 'METHOD path' in {subject!r}")
    parsed = {"component": component, "method": method, "path": path}
    if aspect_separator:
        parsed["aspect"] = aspect
    return parsed


def _parse_config(rest: str, subject: str) -> dict[str, str]:
    component, separator, key = rest.partition("/")
    if not separator or not key:
        raise SubjectError(f"expected 'component/KEY' in {subject!r}")
    return {"component": component, "key": key}


def _parse_schema(rest: str, subject: str) -> dict[str, str]:
    database, separator, dotted = rest.partition("/")
    if not separator:
        raise SubjectError(f"expected 'database/namespace.table' in {subject!r}")
    pieces = dotted.split(".")
    if len(pieces) == 2:
        namespace, table, column = pieces[0], pieces[1], ""
    elif len(pieces) == 3:
        namespace, table, column = pieces
    else:
        raise SubjectError(f"expected 'namespace.table[.column]' in {subject!r}")
    parsed = {"database": database, "namespace": namespace, "table": table}
    if column:
        parsed["column"] = column
    return parsed


def _parse_dep(rest: str, subject: str) -> dict[str, str]:
    component, separator, dependency = rest.partition("/")
    if not separator or not dependency:
        raise SubjectError(f"expected 'component/dependency' in {subject!r}")
    return {"component": component, "dependency": dependency}


def _parse_image(rest: str, subject: str) -> dict[str, str]:
    if not rest:
        raise SubjectError(f"empty component name in {subject!r}")
    return {"component": rest}


def _parse_auth(rest: str, subject: str) -> dict[str, str]:
    pair, separator, aspect = rest.partition("/")
    if not separator or not aspect:
        raise SubjectError(f"expected 'from{_ARROW}to/aspect' in {subject!r}")
    source, target = _split_arrow(pair, subject)
    return {"from_component": source, "to_component": target, "aspect": aspect}


_BUILDERS = {
    SubjectKind.COMPONENT: _build_component,
    SubjectKind.CONNECTION: _build_connection,
    SubjectKind.HTTP: _build_http,
    SubjectKind.CONFIG: _build_config,
    SubjectKind.SCHEMA: _build_schema,
    SubjectKind.DEP: _build_dep,
    SubjectKind.IMAGE: _build_image,
    SubjectKind.AUTH: _build_auth,
}

_PARSERS = {
    SubjectKind.COMPONENT: _parse_component,
    SubjectKind.CONNECTION: _parse_connection,
    SubjectKind.HTTP: _parse_http,
    SubjectKind.CONFIG: _parse_config,
    SubjectKind.SCHEMA: _parse_schema,
    SubjectKind.DEP: _parse_dep,
    SubjectKind.IMAGE: _parse_image,
    SubjectKind.AUTH: _parse_auth,
}

_REQUIRED: dict[SubjectKind, set[str]] = {
    SubjectKind.COMPONENT: {"name"},
    SubjectKind.CONNECTION: {"from_component", "to_component"},
    SubjectKind.HTTP: {"component", "method", "path"},
    SubjectKind.CONFIG: {"component", "key"},
    SubjectKind.SCHEMA: {"database", "table"},
    SubjectKind.DEP: {"component", "dependency"},
    SubjectKind.IMAGE: {"component"},
    SubjectKind.AUTH: {"from_component", "to_component", "aspect"},
}

_OPTIONAL: dict[SubjectKind, set[str]] = {
    SubjectKind.COMPONENT: set(),
    SubjectKind.CONNECTION: set(),
    SubjectKind.HTTP: {"aspect"},
    SubjectKind.CONFIG: set(),
    SubjectKind.SCHEMA: {"namespace", "column"},
    SubjectKind.DEP: set(),
    SubjectKind.IMAGE: set(),
    SubjectKind.AUTH: set(),
}
