"""Static extraction: config-key reads and test status-code assertions.

The third preference tier (`.claude/rules/model.md`): used only for what
neither an artefact nor introspection can give. A config key read via
`os.environ["X"]` leaves no runtime trace unless that line executes, and
a test's expectation about a status code exists nowhere but the test.

Python's own `ast` module, not tree-sitter. The plan's field 11 names
tree-sitter for the *Node* extractor, and this is a Python package
running in a Python project — `ast` is exact, in the standard library,
and always agrees with the interpreter that will run the code. Bringing
in a second parser to parse Python would be strictly worse.

**These are the lowest-confidence facts this extractor emits** (rank 60
for a config read, rank 50 for a test assertion), and the ranks are what
keeps them honest: they inform a report and lose to introspection when
the two disagree, without ever being silently discarded (§2.4).
"""

import ast
from pathlib import Path
from typing import Any

from culprit_model import build
from culprit_model.planes import ConfidenceRank, SourceKind
from culprit_model.protocol import Predicate
from culprit_model.shape import ValueShape

from culprit_extract_python.emit import FactBuilder

#: Directories never walked. Third-party code reads its own config keys
#: constantly, and attributing `urllib3`'s `HTTPS_PROXY` to the user's
#: component would be a confidently wrong fact.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "site-packages",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)

#: How deep to walk. Same bound and same reason as the Go side's
#: maxScanDepth — see docs/LIMITS.md.
MAX_DEPTH = 6

#: The two-argument forms whose second argument is a default value.
#: `os.environ.get("PORT", "8000")` tells us both that PORT is read and
#: what shape a value for it takes, which is a genuinely better fact
#: than the key name alone.
_DEFAULTING_CALLS = frozenset({"get", "getenv"})


def python_files(root: Path) -> list[Path]:
    """Every project-owned .py file under root, in a stable order."""
    found: list[Path] = []
    root = root.resolve()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if SKIP_DIRS.intersection(relative.parts):
            continue
        if len(relative.parts) - 1 > MAX_DEPTH:
            continue
        found.append(path)
    return found


def extract_config_keys(root: Path, builder: FactBuilder) -> list[Any]:
    """Finds `os.environ[...]`, `os.environ.get(...)`, `os.getenv(...)`.

    Only literal keys. `os.environ[name]` where `name` is a variable is
    skipped silently rather than guessed at — a config subject built
    from a guess would never match anything and would sit in the report
    as a permanent phantom finding.
    """
    facts: list[Any] = []
    for path in python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            # A file that does not parse under this interpreter — a
            # Python 2 relic, a template — contributes nothing. Not an
            # error: the rest of the tree is still worth reading.
            continue
        artefact = _relative(root, path)
        for node in ast.walk(tree):
            found = _config_read(node)
            if found is None:
                continue
            key, default = found
            try:
                subject = build("config", component=builder.component, key=key)
            except Exception:  # a key containing a separator
                continue
            locator = f"L{getattr(node, 'lineno', 0)}"
            facts.append(
                builder.fact(
                    subject,
                    Predicate.READ_BY,
                    True,
                    source_kind=SourceKind.STATIC,
                    artefact=artefact,
                    locator=locator,
                    rank=ConfidenceRank.STATIC_FRAMEWORK_CODE,
                )
            )
            # A default is a claim about the shape a value should take,
            # so it becomes a shape — never the default itself, even
            # though a default in committed source is public. The rule
            # is structural, not case-by-case, and a `DEFAULT_PASSWORD =
            # "changeme"` fallback is exactly why.
            if default is not None:
                facts.append(
                    builder.config_fact(
                        subject,
                        Predicate.DEFAULT_SHAPE,
                        ValueShape.of(default),
                        artefact=artefact,
                        locator=locator,
                    )
                )
            else:
                facts.append(
                    builder.fact(
                        subject,
                        Predicate.REQUIRED,
                        True,
                        source_kind=SourceKind.STATIC,
                        artefact=artefact,
                        locator=locator,
                        rank=ConfidenceRank.STATIC_FRAMEWORK_CODE,
                    )
                )
    return facts


def _config_read(node: ast.AST) -> tuple[str, Any] | None:
    """Returns (key, default) for a recognised environment read."""
    # os.environ["KEY"] / environ["KEY"]
    if isinstance(node, ast.Subscript) and _is_environ(node.value):
        key = _literal_str(node.slice)
        return (key, None) if key else None

    if not isinstance(node, ast.Call) or not node.args:
        return None
    key = _literal_str(node.args[0])
    if key is None:
        return None

    func = node.func
    # os.getenv("KEY"[, default])
    if isinstance(func, ast.Name) and func.id == "getenv":
        return key, _literal_value(node.args[1]) if len(node.args) > 1 else None
    if isinstance(func, ast.Attribute) and func.attr in _DEFAULTING_CALLS:
        if func.attr == "getenv" and _is_os(func.value):
            return key, _literal_value(node.args[1]) if len(node.args) > 1 else None
        if func.attr == "get" and _is_environ(func.value):
            return key, _literal_value(node.args[1]) if len(node.args) > 1 else None
    return None


def _is_os(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "os"


def _is_environ(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "environ"
    return isinstance(node, ast.Attribute) and node.attr == "environ" and _is_os(node.value)


def _literal_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
        return node.value
    return None


def _literal_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    return None


# --- test assertions ----------------------------------------------------

#: Names a test client is conventionally bound to. Restricted rather
#: than "any object with a .get method", because `session.get(...)` and
#: `cache.get(...)` are not HTTP calls and would produce routes that do
#: not exist.
_CLIENT_NAMES = frozenset({"client", "test_client", "app_client", "api_client", "ac", "c"})

_HTTP_CALL_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "request"}
)


def extract_test_assertions(root: Path, builder: FactBuilder) -> list[Any]:
    """Finds routes a test exercises, by looking for a client call next
    to an asserted status code.

    **The claim is that the route is exercised, not what it returns.**

    Phase 28 emitted the asserted status codes here, as `status_codes`,
    reasoning that a wrong pairing would surface as a visible
    `intent_conflict` somebody could look at. Phase 29 ran the comparator
    over this repository and showed that reasoning to be wrong. Three
    findings came out, all noise, all the same shape: one test asserts
    201 for `POST /services` and another asserts 403, so the two "disagree".

    They do not. A route answers 201 to an admin and 403 to a member, and
    both tests are correct. `status_codes` on a route table means "the
    set of codes this route can return"; on a test it meant "a code seen
    once, in one scenario, possibly paired with the wrong call". Those
    are different claims and they must not share a predicate — comparison
    is by (subject, predicate), and a predicate that means two things
    produces a disagreement between two facts that are both true.

    So the status code is dropped and the surviving claim is the one that
    was always the valuable part: **this route is exercised by a test**.
    That still finds a test hitting a route the application does not
    serve, and it still tells §0.1's coverage report which parts of the
    surface no test touches. What is lost — "the test expects 200 and the
    app returns 404" — was never soundly detectable this way.

    The pairing heuristic itself is unchanged and still stated in
    `docs/LIMITS.md`: within one test function, every asserted code is
    paired with every path the function calls. It now costs less, because
    the mis-pairing no longer changes what is claimed.
    """
    facts: list[Any] = []
    for path in python_files(root):
        name = path.name
        if not (name.startswith("test_") or name.endswith("_test.py")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        artefact = _relative(root, path)
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = _client_calls(function)
            codes = _asserted_status_codes(function)
            if not calls or not codes:
                continue
            for method, route, line in calls:
                try:
                    subject = build(
                        "http", component=builder.component, method=method, path=route
                    )
                except Exception:
                    continue
                facts.append(
                    builder.fact(
                        subject,
                        Predicate.EXERCISED_BY_TEST,
                        True,
                        source_kind=SourceKind.TEST,
                        artefact=artefact,
                        locator=f"{function.name}:L{line}",
                        rank=ConfidenceRank.STATIC_TESTS,
                    )
                )
    return facts


def _client_calls(function: ast.AST) -> list[tuple[str, str, int]]:
    calls: list[tuple[str, str, int]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attribute = node.func
        if attribute.attr not in _HTTP_CALL_METHODS:
            continue
        target = attribute.value
        while isinstance(target, ast.Await):  # pragma: no cover - defensive
            target = target.value
        if not isinstance(target, ast.Name) or target.id not in _CLIENT_NAMES:
            continue
        if not node.args:
            continue
        route = _literal_str(node.args[0])
        if route is None or not route.startswith("/"):
            continue
        method = attribute.attr.upper()
        if method == "REQUEST":
            continue  # the method is the first argument; the path is the second
        calls.append((method, route, getattr(node, "lineno", 0)))
    return calls


def _asserted_status_codes(function: ast.AST) -> list[int]:
    codes: list[int] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare) or len(node.comparators) != 1:
            continue
        if not isinstance(node.ops[0], ast.Eq):
            continue
        left, right = node.left, node.comparators[0]
        if not (isinstance(left, ast.Attribute) and left.attr in {"status_code", "status"}):
            continue
        if isinstance(right, ast.Constant) and isinstance(right.value, int):
            codes.append(right.value)
    return codes


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
