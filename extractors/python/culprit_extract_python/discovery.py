"""Finding the application object to introspect.

Runtime introspection needs something to introspect, and there is no
standard for where a Python project keeps its app. So: an explicit
`--app module:attribute`, and failing that a search over the
conventional spellings.

**Auto-discovery is a convenience, not a guess.** Every candidate below
is a real convention (`app.main:app` is FastAPI's own tutorial layout;
`wsgi:application` is what every Django `startproject` emits), and a
candidate that imports but is not a recognisable app object is rejected
rather than accepted hopefully. When nothing is found, the extractor
skips with the list of what it tried — a reader can then pass `--app`,
which is a much better outcome than facts extracted from the wrong
module.

Importing a user's application executes their code, at the same trust
level as running their test suite. That is stated plainly in
`docs/EXTRACTOR_PROTOCOL.md` because a user is entitled to know it
before installing this.
"""

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

#: Tried in order. The order is "most specific layout first": a project
#: with both `app/main.py` and a top-level `main.py` almost always means
#: the former, and picking the latter would silently extract a smaller,
#: wrong route table.
CANDIDATE_TARGETS = (
    "app.main:app",
    "main:app",
    "app:app",
    "src.main:app",
    "application:app",
    "api.main:app",
    "wsgi:application",
    "asgi:application",
    "config.wsgi:application",
    "app:create_app",
    "main:create_app",
)


@dataclass(frozen=True)
class DiscoveredApp:
    """An application object and how it was found."""

    target: str
    obj: object
    #: `fastapi`, `flask`, `django` or `unknown`. Decides which route
    #: reader runs; `unknown` means none does, and says so.
    framework: str


class DiscoveryError(Exception):
    """No application could be found or imported. Carries the reason."""


def add_root_to_path(root: Path) -> None:
    """Puts the project's own root on `sys.path`.

    An extractor is run with the project root as its working directory,
    but a subprocess does not inherit that as an import root the way a
    plain `python` invocation does. Without this, `app.main` is not
    importable in exactly the projects this is meant to read.
    """
    for candidate in (root, root / "src"):
        entry = str(candidate.resolve())
        if candidate.is_dir() and entry not in sys.path:
            sys.path.insert(0, entry)


def load_app(target: str) -> object:
    """Imports `module:attribute` and returns the attribute.

    A zero-argument callable is called — `app:create_app` is the Flask
    application-factory convention and is as common as a module-level
    app. Anything else is returned as found.
    """
    module_name, _, attribute = target.partition(":")
    if not module_name or not attribute:
        raise DiscoveryError(f"--app {target!r} is not in module:attribute form")
    module = importlib.import_module(module_name)
    try:
        obj = getattr(module, attribute)
    except AttributeError as exc:
        raise DiscoveryError(f"{module_name} has no attribute {attribute!r}") from exc
    if callable(obj) and not _looks_like_app(obj):
        try:
            obj = obj()
        except Exception as exc:  # a user factory may raise anything
            raise DiscoveryError(f"calling {target} raised {type(exc).__name__}: {exc}") from exc
    return obj


def discover(root: Path, explicit: str | None) -> DiscoveredApp:
    """Finds an app, explicitly or by convention."""
    add_root_to_path(root)

    if explicit:
        obj = load_app(explicit)
        framework = classify(obj)
        if framework == "unknown":
            raise DiscoveryError(
                f"{explicit} imported, but is not a FastAPI, Flask or Django application "
                f"(got {type(obj).__module__}.{type(obj).__name__})"
            )
        return DiscoveredApp(target=explicit, obj=obj, framework=framework)

    failures: list[str] = []
    for target in CANDIDATE_TARGETS:
        try:
            obj = load_app(target)
        except ModuleNotFoundError as exc:
            # Two very different things arrive here and only one is
            # noise. "there is no module called `app`" means this layout
            # is simply not the project's — expected, and reporting it
            # for eleven candidates would bury the real answer. "`main`
            # imported and *it* could not find `shared`" is the actual
            # problem, and swallowing it leaves the user staring at an
            # empty report with no idea why.
            if not _is_missing_candidate_itself(target, exc):
                failures.append(f"{target}: {type(exc).__name__}: {exc}")
            continue
        except (DiscoveryError, ImportError) as exc:
            failures.append(f"{target}: {type(exc).__name__}: {exc}")
            continue
        except Exception as exc:  # importing user code
            # A candidate that exists and *raised* is worth reporting:
            # "app.main exists but raised MissingConfigError" is the
            # single most useful line this extractor can print.
            failures.append(f"{target}: {type(exc).__name__}: {exc}")
            continue
        framework = classify(obj)
        if framework != "unknown":
            return DiscoveredApp(target=target, obj=obj, framework=framework)

    detail = ""
    if failures:
        detail = " Candidates that failed to import: " + "; ".join(failures[:3])
    raise DiscoveryError(
        "no FastAPI, Flask or Django application found. Tried "
        + ", ".join(CANDIDATE_TARGETS)
        + f".{detail} Pass --app module:attribute to name it explicitly."
    )


def classify(obj: object) -> str:
    """Names the framework an object belongs to, without importing any.

    Duck-typed against the object's own MRO rather than by
    `isinstance` against imported classes: this extractor must not
    import FastAPI in a Flask project, and importing all three to ask
    would triple its startup cost and fail on whichever is absent.
    """
    for klass in type(obj).__mro__:
        qualified = f"{klass.__module__}.{klass.__name__}"
        if qualified.startswith("fastapi."):
            return "fastapi"
        if qualified.startswith("flask."):
            return "flask"
        if qualified.startswith("django."):
            return "django"
    # A Django WSGI application is a plain function, not a class, so the
    # MRO walk above cannot see it.
    if type(obj).__module__.startswith("django."):
        return "django"
    if getattr(obj, "openapi", None) is not None and getattr(obj, "routes", None) is not None:
        return "fastapi"
    if getattr(obj, "url_map", None) is not None:
        return "flask"
    return "unknown"


def _looks_like_app(obj: object) -> bool:
    """Whether an object is already an app rather than a factory.

    A FastAPI app is itself callable (it is an ASGI application), so
    "callable means factory" would call the app and get an exception
    about missing ASGI scope arguments.
    """
    return classify(obj) != "unknown"


def _is_missing_candidate_itself(target: str, exc: ModuleNotFoundError) -> bool:
    """Whether the missing module is the candidate, not one of its imports.

    `import app.main` failing on `app` means this project does not use
    that layout — expected, and not worth a line in the report.
    `import main` failing on `shared` means the module exists and its own
    imports are broken, which is exactly what the user needs told.
    """
    module_name = target.partition(":")[0]
    missing = exc.name or ""
    return missing == module_name or module_name.startswith(missing + ".")
