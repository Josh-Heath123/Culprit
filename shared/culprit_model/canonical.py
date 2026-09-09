"""Canonicalisation: making two sources describing the same thing say it
identically.

docs/DIAGNOSTIC_PLAN.md §2.3 calls path templating "the single
highest-risk piece of code in the extraction layer", because comparison
across planes is only meaningful if `/orders/{id}` (FastAPI/OpenAPI),
`/orders/:id` (Express), `/orders/<int:id>` (Flask/Django) and
`^orders/(?P<pk>[0-9]+)/$` (Django `re_path`) all reduce to one string.
Everything here is pure, deterministic and table-tested — see
shared/tests/test_canonical.py.

The deliberate choice worth knowing about: **parameter names are erased,
not preserved.** `/orders/{id}` and `/orders/{order_id}` both become
`/orders/{}`. Keeping the name would mean a Django view calling its
capture `pk` and an OpenAPI document calling it `id` describe "different"
routes and never get compared — which is the exact failure this module
exists to prevent. The cost is that two genuinely different routes with
identical shapes collide, which cannot happen inside one component
because a router that had both would itself be ambiguous. The original,
un-erased path is kept in the Fact's `value`/provenance for reporting;
only the subject URI is canonical.
"""

import json
import re
from typing import Any

#: A parameter placeholder inside one path segment, in the four templating
#: conventions this project actually meets. Applied *within* a segment
#: rather than to whole segments, so `/files/{name}.json` and
#: `/v1/item-:id` normalise correctly too.
_PARAM_PATTERNS = (
    # OpenAPI / FastAPI / Starlette: {id}, {id:path}, {file_path:path}
    re.compile(r"\{[^{}/]*\}"),
    # Flask / Django path(): <id>, <int:pk>, <path:subpath>
    re.compile(r"<[^<>/]*>"),
    # Django re_path named group: (?P<pk>[0-9]+); and bare regex groups.
    # Non-nested only — a nested group is a documented limit, not a
    # silently wrong answer, because it leaves the segment untouched.
    re.compile(r"\((?:\?P<[^>]*>)?[^()]*\)[*+?]?"),
    # Express / Rails / Sinatra: :id, and :id(\d+) once the group above
    # has already been collapsed.
    re.compile(r":[A-Za-z_][A-Za-z0-9_]*"),
    # Express/Ant-style catch-alls.
    re.compile(r"\*\*?"),
)

_PLACEHOLDER = "{}"

#: Stripped before segmentation — Django `re_path` anchors.
_ANCHORS = ("^", "$")

#: Also the aspect separator in a subject URI (`...#request.body`), which
#: is why a path may never contain one by the time `subjects.build` sees it.
_ASPECT_SEPARATOR = "#"


def canonical_path(path: str) -> str:
    """Normalises a route path to `/literal/{}/literal` form.

    Idempotent: `canonical_path(canonical_path(p)) == canonical_path(p)`
    for every input, which is what lets a subject URI be rebuilt from a
    parsed one without drifting.
    """
    path = path.strip()
    if path.startswith(_ANCHORS[0]):
        path = path[1:]
    if path.endswith(_ANCHORS[1]):
        path = path[:-1]

    if not path.startswith("/"):
        path = "/" + path

    segments = [segment for segment in path.split("/") if segment != ""]
    normalised = "/" + "/".join(_canonical_segment(segment) for segment in segments)

    # Query string and fragment are cut *after* parameter normalisation,
    # not before. A Django `re_path` route legitimately contains a `?`
    # inside `(?P<pk>...)`, and cutting first turned `^orders/(?P<pk>\d+)$`
    # into `/orders/(` — a wrong answer that still looked like a path.
    # By this point every parameter has already collapsed to `{}`, so any
    # `?` still standing really is a query separator (or an Express
    # optional-parameter marker, whose optionality this deliberately
    # drops — see docs/LIMITS.md).
    for cut in ("?", _ASPECT_SEPARATOR):
        head, _, _ = normalised.partition(cut)
        normalised = head
    normalised = normalised.rstrip("/")
    return normalised or "/"


def _canonical_segment(segment: str) -> str:
    # Regex groups first: `(?P<pk>[0-9]+)` contains a `:`-free body but a
    # `\d`-style class that the Express pattern would otherwise not touch,
    # and `:id(\d+)` must lose its group before the `:id` pattern runs.
    for pattern in _PARAM_PATTERNS:
        segment = pattern.sub(_PLACEHOLDER, segment)
    # Collapse `{}{}`, which only arises from an already-odd source path
    # like `<int:a><int:b>`; one parameter per position is the invariant.
    while _PLACEHOLDER * 2 in segment:
        segment = segment.replace(_PLACEHOLDER * 2, _PLACEHOLDER)
    return segment


def canonical_method(method: str) -> str:
    """HTTP methods are case-insensitive in every source we read them
    from and upper-case in every one we print them to."""
    return method.strip().upper()


def canonical_component(name: str) -> str:
    """Component/service names.

    Lower-cased and trimmed: these are DNS-ish names (`order-service`,
    `orders-svc`) that appear in a Docker service name, an OTel
    `service.name` resource attribute and a registry row, and those three
    disagree on case far more often than they disagree on identity.
    Underscores are *not* folded to hyphens — `order_service` (the
    demo-services directory) and `order-service` (its registered name)
    are genuinely two different strings, and papering over that here
    would hide a real naming divergence rather than surface it.
    """
    return name.strip().lower()


def canonical_identifier(name: str) -> str:
    """Postgres identifiers (schema, table, column names).

    Lower-cased because Postgres folds unquoted identifiers that way, so
    a migration writing `Orders` and an introspection reading `orders`
    are the same object. A quoted mixed-case identifier is therefore not
    round-trippable through a subject URI — a documented limit
    (docs/LIMITS.md), not a silent one: this project's own schema uses no
    quoted identifiers.
    """
    return name.strip().lower()


def canonical_value(value: Any) -> Any:
    """Recursively canonicalises a Fact value for comparison.

    Mappings get key-ordered, sets and frozensets become sorted lists
    (a set has no order, so any order but a deterministic one would make
    equal values compare unequal), and everything else is returned as-is.
    Lists are *not* sorted: order is meaningful in a list of path
    segments or middleware, and sorting would erase a real divergence.
    """
    if isinstance(value, dict):
        return {key: canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (set, frozenset)):
        return [canonical_value(item) for item in sorted(value, key=_sort_key)]
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    return value


def _sort_key(item: Any) -> str:
    return json.dumps(item, sort_keys=True, default=str)


def canonical_json(value: Any) -> str:
    """A stable string form of a value, for hashing and equality.

    `separators` is pinned so whitespace can never make two equal values
    hash differently, and `default=str` means an unexpected type
    (a datetime an extractor forgot to serialise) degrades to a stable
    string rather than raising in the middle of a comparison run.
    """
    return json.dumps(
        canonical_value(value), sort_keys=True, separators=(",", ":"), default=str
    )


def values_equal(left: Any, right: Any) -> bool:
    """The only sanctioned equality test between two Fact values."""
    return canonical_json(left) == canonical_json(right)
