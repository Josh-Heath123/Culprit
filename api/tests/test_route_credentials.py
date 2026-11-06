"""Every route, and the credentials it accepts (Phase 33 part 2).

The project token is a single shared bearer credential a CI job holds. After
part 2 it works on exactly the three capture endpoints and
`POST /investigations` — not on `POST /readings`, which takes an agent's
signature and nothing else, and not anywhere new. This test reads the real
application's dependency tree, route by route, so a route that gains the
project token — directly, or through a router-level dependency — turns it
red, whatever its handler says.
"""

from app.agents.dependencies import require_agent, require_project_token_or_agent
from app.auth.dependencies import require_admin, require_auth, require_auth_or_agent
from app.facts.dependencies import require_project_token
from app.main import app
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

PROJECT_TOKEN_ROUTES = {
    "POST /facts/captures",
    "POST /divergences/captures",
    "POST /captures",
    "POST /investigations",
}

#: The credential each dependency stands for.
CREDENTIALS = {
    require_project_token: "project token",
    require_project_token_or_agent: "project token or agent",
    require_agent: "agent",
    require_admin: "admin session",
    require_auth: "user session",
    require_auth_or_agent: "user session or automation token",
}


def _credentials(dependant: Dependant) -> set[str]:
    found: set[str] = set()
    if dependant.call in CREDENTIALS:
        found.add(CREDENTIALS[dependant.call])
    for child in dependant.dependencies:
        found |= _credentials(child)
    return found


def _routes(routes) -> list:
    """Every API route with its full path, methods and merged dependency
    tree. FastAPI 0.141 mounts an included router as one object whose
    `effective_candidates()` are its routes as the app serves them — with
    the prefix and any router-level dependency applied, which is exactly
    what this test must see."""
    found = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "effective_candidates"):
            found.extend(_routes(route.effective_candidates()))
            if hasattr(route, "effective_low_priority_routes"):
                found.extend(_routes(route.effective_low_priority_routes()))
        elif hasattr(route, "dependant") and hasattr(route, "methods"):
            found.append(route)
    return found


def _table() -> dict[str, set[str]]:
    table: dict[str, set[str]] = {}
    for route in _routes(app.routes):
        for method in sorted((route.methods or set()) - {"HEAD"}):
            table[f"{method} {route.path}"] = _credentials(route.dependant)
    assert len(table) > 40, f"only {len(table)} routes found: the walk is missing some"
    return table


def _render(table: dict[str, set[str]]) -> str:
    return "\n".join(
        f"  {route:55} {', '.join(sorted(creds)) or '(none)'}"
        for route, creds in sorted(table.items())
    )


def test_the_project_token_works_on_exactly_the_capture_endpoints_and_investigations() -> None:
    table = _table()
    takes_token = {
        route
        for route, creds in table.items()
        if creds & {"project token", "project token or agent"}
    }
    assert takes_token == PROJECT_TOKEN_ROUTES, (
        "the project token is accepted on a different set of routes than the "
        f"plan allows.\nEvery route and its credentials:\n{_render(table)}"
    )


def test_post_readings_takes_an_agents_signature_only() -> None:
    assert _table()["POST /readings"] == {"agent"}


def test_every_route_an_agent_calls_for_itself_is_signed() -> None:
    table = _table()
    own = {route: creds for route, creds in table.items() if " /agents/me/" in route}
    assert own, "no /agents/me routes found"
    for route, creds in own.items():
        assert creds == {"agent"}, f"{route} accepts {creds}"


def test_every_agent_admin_route_needs_an_admin() -> None:
    table = _table()
    for route, creds in table.items():
        path = route.split(" ", 1)[1]
        if not path.startswith("/agents") or "/agents/me/" in path:
            continue
        if route == "POST /agents/register":
            # Authenticated by the single-use pairing code it spends, and able
            # to do nothing else.
            assert creds == set(), f"{route} accepts {creds}"
            continue
        # require_admin is built on require_auth, so both appear; what
        # matters is that an admin is required and no machine credential is.
        assert creds == {"admin session", "user session"}, f"{route} accepts {creds}"


def test_the_project_token_is_only_checked_where_the_route_table_can_see_it() -> None:
    """The table above identifies a credential by its dependency callable.
    A new dependency that called `require_project_token` inside its own body
    would accept the token on a route the table reads as something else. So
    every reference to it in the application must be a `Depends(...)`
    argument, or inside `require_project_token_or_agent` — the one wrapper
    the table already lists."""
    import ast
    from pathlib import Path

    app_root = Path(__file__).parents[1] / "app"
    offenders: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            named = (isinstance(node, ast.Name) and node.id == "require_project_token") or (
                isinstance(node, ast.Attribute) and node.attr == "require_project_token"
            )
            if not named or isinstance(parents.get(node), ast.ImportFrom):
                continue
            parent, inside = parents.get(node), None
            while parent is not None:
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    inside = parent.name
                    break
                parent = parents.get(parent)
            call = parents.get(node)
            in_depends = (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "Depends"
            )
            if in_depends or inside == "require_project_token_or_agent":
                continue
            line = getattr(node, "lineno", 0)
            offenders.append(f"{path.relative_to(app_root)}:{line} (in {inside})")
    assert offenders == [], (
        "require_project_token is referenced where the route table cannot see it: "
        + ", ".join(offenders)
    )
