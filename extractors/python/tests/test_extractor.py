"""The Python extractor, against the fixture corpus.

Two of these fixtures were written by other people, in a framework this
repo does not use (`docs/DIAGNOSTIC_PLAN.md` field 13). That is the point
of them, and it paid immediately: the Flask tutorial configures itself
through `app.config.from_mapping` and never touches `os.environ`, so the
config-key reader — which works perfectly against this repo's own
services — finds nothing in it. A corpus of only self-written fixtures
would have reported that reader as complete.

The subprocess tests drive the real `culprit-extract-python` process over
a real pipe, rather than calling `run()` in-process. What is being tested
is the *protocol* — stdin, stdout, the exit code, and the rule that
nothing but the response reaches stdout.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from culprit_extract_python import EXTRACTOR_ID
from culprit_extract_python.cli import run
from culprit_model.subjects import build

FIXTURES = Path(__file__).resolve().parents[3] / "cli" / "testdata" / "fixtures"
FASTAPI_FIXTURE = FIXTURES / "fastapi-orders"
FLASK_FIXTURE = FIXTURES / "third-party" / "flask-tutorial"

#: A value that sits in the fastapi fixture's .env.example and in its
#: config module's defaults. It must never appear in a fact.
LEAKED_DSN = "postgresql://orders:placeholder@localhost:5432/orders"


def request_payload(root: Path, wants: list[str], component: str) -> dict:
    return {
        "protocol": 1,
        "root": str(root),
        "want": wants,
        "environment": None,
        "component": component,
    }


def run_subprocess(root: Path, wants: list[str], component: str, *args: str):
    """Runs the installed console script exactly as the orchestrator does."""
    process = subprocess.run(
        [sys.executable, "-m", "culprit_extract_python.cli", *args],
        input=json.dumps(request_payload(root, wants, component)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, (
        "an extractor must never fail the run "
        f"(exit {process.returncode}, stderr: {process.stderr[:500]})"
    )
    return json.loads(process.stdout), process.stderr


# --- the protocol -------------------------------------------------------


def test_exits_zero_and_writes_one_json_object() -> None:
    response, _ = run_subprocess(FASTAPI_FIXTURE, ["config_keys"], "orders-api")
    assert response["protocol"] == 1
    assert response["extractor"] == EXTRACTOR_ID


def test_garbage_on_stdin_is_a_skip_not_a_crash() -> None:
    process = subprocess.run(
        [sys.executable, "-m", "culprit_extract_python.cli"],
        input="this is not JSON",
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0
    response = json.loads(process.stdout)
    assert response["facts"] == []
    assert response["skipped"], "a failure must be reported, not silent"
    assert "JSON" in response["skipped"][0]["reason"]


def test_a_protocol_it_does_not_understand_is_refused() -> None:
    """Refuse rather than attempt: answering a protocol this build may be
    misreading produces a wrong fact, which is worse than a missing one."""
    process = subprocess.run(
        [sys.executable, "-m", "culprit_extract_python.cli"],
        input=json.dumps({"protocol": 99, "root": str(FASTAPI_FIXTURE), "want": []}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0
    response = json.loads(process.stdout)
    assert response["facts"] == []
    assert "protocol" in response["skipped"][0]["reason"]


def test_an_unsupported_want_is_skipped_with_a_reason() -> None:
    response, _ = run_subprocess(FASTAPI_FIXTURE, ["client_calls"], "orders-api")
    assert response["facts"] == []
    skipped = {skip["want"]: skip["reason"] for skip in response["skipped"]}
    assert "client_calls" in skipped
    assert "does not extract" in skipped["client_calls"]


def test_an_unimportable_app_is_a_skip_naming_the_failure() -> None:
    """The most common real failure, and the one whose reason matters most."""
    response, _ = run_subprocess(
        FASTAPI_FIXTURE, ["http_routes"], "orders-api", "--app", "nope.nothing:app"
    )
    assert response["facts"] == []
    assert response["skipped"]
    reason = response["skipped"][0]["reason"]
    assert "nope.nothing" in reason or "No module named" in reason


# --- config keys --------------------------------------------------------


def test_config_keys_are_found_in_all_three_spellings() -> None:
    response, _ = run_subprocess(FASTAPI_FIXTURE, ["config_keys"], "orders-api")
    subjects = {fact["subject"] for fact in response["facts"]}
    for key in ("DATABASE_URL", "JWT_SECRET_KEY", "PORT", "REQUEST_TIMEOUT"):
        assert build("config", component="orders-api", key=key) in subjects, f"{key} was not found"


def test_a_computed_config_key_is_skipped_not_guessed() -> None:
    """`os.environ.get(_PREFIX + "API_KEY")` is not extractable.

    A subject built from a guess would never match anything and would sit
    in every report as a permanent phantom finding.
    """
    response, _ = run_subprocess(FASTAPI_FIXTURE, ["config_keys"], "orders-api")
    subjects = {fact["subject"] for fact in response["facts"]}
    assert build("config", component="orders-api", key="STRIPE_API_KEY") not in subjects
    assert build("config", component="orders-api", key="API_KEY") not in subjects


def test_a_default_becomes_a_shape_never_a_value() -> None:
    response, _ = run_subprocess(FASTAPI_FIXTURE, ["config_keys"], "orders-api")
    shapes = [
        fact
        for fact in response["facts"]
        if fact["subject"] == build("config", component="orders-api", key="REQUEST_TIMEOUT")
        and fact["predicate"] == "default_shape"
    ]
    assert shapes, "a default was not classified into a shape"
    shape = shapes[0]["value_shape"]
    assert shape["format"] == "duration"
    assert shape["type"] == "string"
    # Phase 30 (Q7): the fifth field, `scheme`. A duration has none, and
    # says so rather than leaving the key out.
    assert set(shape) == {"type", "length_class", "format", "present", "scheme"}
    assert shape["scheme"] == "not_applicable"
    assert shapes[0].get("value") is None


def test_no_config_value_survives_into_any_fact() -> None:
    """Acceptance criterion 3, over a whole real extraction run."""
    response, _ = run_subprocess(
        FASTAPI_FIXTURE, ["config_keys", "test_assertions"], "orders-api"
    )
    serialised = json.dumps(response)
    assert LEAKED_DSN not in serialised
    assert "placeholder" not in serialised


# --- runtime introspection ----------------------------------------------


def test_fastapi_routes_come_from_the_running_app() -> None:
    fastapi = pytest.importorskip("fastapi")
    del fastapi
    response, _ = run_subprocess(
        FASTAPI_FIXTURE, ["http_routes"], "orders-api", "--app", "orders_api.main:app"
    )
    subjects = {fact["subject"] for fact in response["facts"]}
    assert build("http", component="orders-api", method="GET", path="/api/v1/orders") in subjects
    assert build("http", component="orders-api", method="POST", path="/api/v1/orders") in subjects
    # The path parameter is canonicalised, so this compares equal to the
    # React fixture's `/api/v1/orders/${id}` call site.
    assert (
        build("http", component="orders-api", method="GET", path="/api/v1/orders/{id}")
        in subjects
    )
    assert build("http", component="orders-api", method="GET", path="/healthz") in subjects

    ranks = {
        fact["provenance"]["confidence_rank"]
        for fact in response["facts"]
        if fact["predicate"] == "exists"
    }
    assert ranks == {90}, "runtime introspection is rank 90 (§2.4)"


def test_fastapi_request_body_becomes_an_aspect_subject() -> None:
    pytest.importorskip("fastapi")
    response, _ = run_subprocess(
        FASTAPI_FIXTURE, ["http_routes"], "orders-api", "--app", "orders_api.main:app"
    )
    aspects = [
        fact
        for fact in response["facts"]
        if fact["subject"].endswith("#request.body")
    ]
    assert aspects, "no request-body aspect was emitted"
    assert aspects[0]["subject"] == build(
        "http", component="orders-api", method="POST", path="/api/v1/orders",
        aspect="request.body",
    )
    assert aspects[0]["value"]["required"] is True


def test_sqlalchemy_schema_is_read_from_the_imported_models() -> None:
    pytest.importorskip("sqlalchemy")
    response, _ = run_subprocess(
        FASTAPI_FIXTURE, ["db_schema"], "orders-api", "--app", "orders_api.main:app"
    )
    subjects = {fact["subject"] for fact in response["facts"]}
    assert build("schema", database="orders-api-db", table="orders") in subjects
    assert (
        build("schema", database="orders-api-db", table="orders", column="total_cents")
        in subjects
    )
    nullable = [
        fact
        for fact in response["facts"]
        if fact["subject"]
        == build("schema", database="orders-api-db", table="orders", column="cancelled_at")
        and fact["predicate"] == "nullable"
    ]
    assert nullable and nullable[0]["value"] is True


def test_no_import_still_extracts_static_facts() -> None:
    """`--no-import` is the escape hatch for a project whose import has
    side effects nobody wants in CI. It must degrade, not fail."""
    response, _ = run_subprocess(
        FASTAPI_FIXTURE, ["http_routes", "config_keys"], "orders-api", "--no-import"
    )
    assert response["facts"], "static extraction produced nothing"
    reasons = " ".join(skip["reason"] for skip in response["skipped"])
    assert "--no-import" in reasons


# --- a project nobody here wrote ----------------------------------------


def test_flask_tutorial_routes_are_found_through_its_app_factory() -> None:
    """pallets/flask's own tutorial, unmodified, via `create_app`.

    Blueprints with prefixes and `<int:id>` converters — neither of which
    a static parser could resolve, which is exactly why introspection is
    worth importing the app for.
    """
    pytest.importorskip("flask")
    response, _ = run_subprocess(
        FLASK_FIXTURE, ["http_routes"], "flaskr", "--app", "flaskr:create_app"
    )
    subjects = {fact["subject"] for fact in response["facts"]}
    assert build("http", component="flaskr", method="GET", path="/") in subjects
    assert build("http", component="flaskr", method="GET", path="/auth/login") in subjects
    assert build("http", component="flaskr", method="POST", path="/auth/register") in subjects
    # `@bp.route("/<int:id>/update")` on a blueprint with no prefix.
    assert build("http", component="flaskr", method="POST", path="/<int:id>/update") in subjects


def test_flask_tutorial_has_no_environ_reads_and_says_so() -> None:
    """The finding the third-party fixture exists to produce.

    flaskr configures itself with `app.config.from_mapping(SECRET_KEY=...)`
    and never touches `os.environ`. The config-key reader therefore finds
    nothing — a real limitation of that reader, visible only because this
    fixture was not written to suit it. Recorded in docs/LIMITS.md.
    """
    response, _ = run_subprocess(FLASK_FIXTURE, ["config_keys"], "flaskr")
    assert response["facts"] == []
    reasons = {skip["want"]: skip["reason"] for skip in response["skipped"]}
    assert "config_keys" in reasons
    assert "os.environ" in reasons["config_keys"]


def test_flask_tutorial_test_assertions_are_extracted() -> None:
    """Its tests use `client.get('/auth/login')` and assert status codes."""
    response, _ = run_subprocess(FLASK_FIXTURE, ["test_assertions"], "flaskr")
    assert response["facts"], f"no assertions found: {response['skipped']}"
    ranks = {fact["provenance"]["confidence_rank"] for fact in response["facts"]}
    assert ranks == {50}, "a test-derived claim is rank 50 (§2.4)"


# --- in-process, for the paths a subprocess cannot reach ----------------


def test_run_returns_a_response_even_when_everything_fails(tmp_path: Path) -> None:
    from culprit_model.protocol import ExtractorRequest

    response = run(
        ExtractorRequest(
            protocol=1, root=str(tmp_path), want=(), environment=None, component="empty"
        )
    )
    assert response.facts == ()
    assert response.skipped, "an empty directory must still report why it yielded nothing"


def test_a_project_with_no_sqlalchemy_reports_the_gap() -> None:
    """The other half of schema extraction: an honest skip.

    flaskr uses `sqlite3` directly and has no SQLAlchemy metadata to
    read. The extractor must say that rather than emit nothing and let
    the absence read as "this service has no tables".
    """
    pytest.importorskip("flask")
    response, _ = run_subprocess(
        FLASK_FIXTURE, ["db_schema"], "flaskr", "--app", "flaskr:create_app"
    )
    assert response["facts"] == []
    reasons = {skip["want"]: skip["reason"] for skip in response["skipped"]}
    assert "db_schema" in reasons
    assert "SQLAlchemy" in reasons["db_schema"] or "alembic" in reasons["db_schema"]
