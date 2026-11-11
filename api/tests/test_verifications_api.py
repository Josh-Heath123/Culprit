"""Verifications and outcomes in the control plane (Phase 34 part 2), against
a real database under the real roles: `verification-writer` for the write,
`api-reader` for every read and for the checks the write makes first.

Each verification here is built from an investigation the fault library
recorded from a real walk (tests/data/investigations/), re-run as
`culprit verify` re-runs one, and judged by `culprit_model`'s own `judge()`
— so a payload says only what the rule lets it say, unless a test changes
that on purpose.
"""

import copy
import importlib
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from culprit_model.subjects import build
from culprit_model.verifications import Change, Rerun, judge
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

PROJECT_TOKEN = "test-project-token-not-a-real-secret"
RECORDED = Path(__file__).parent / "data" / "investigations"
TOKEN_FIX = {
    "kind": "config",
    "subject": build("config", component="order-service", key="INVENTORY_TOKEN"),
}
AUDIENCE = build(
    "auth", from_component="order-service", to_component="inventory-service", aspect="audience"
)
EDGE = build("connection", from_component="order-service", to_component="inventory-service")
PROVIDER_KEY = build("config", component="payments-service", key="PAYMENTS_PROVIDER_KEY")
ORDER_SERVICE = build("component", name="order-service")
STOCK_ROUTE = build("http", component="inventory-service", method="GET", path="/stock")


def recorded(name: str) -> dict[str, Any]:
    return json.loads((RECORDED / f"{name}.json").read_text("utf-8"))


def verification_of(
    investigation: dict[str, Any],
    *,
    fixed: bool = True,
    changes: list[dict[str, Any]] | None = None,
    after: timedelta = timedelta(minutes=5),
    number: int = 1,
) -> dict[str, Any]:
    """Every reading of `investigation` re-run twice, `after` its close:
    with `fixed`, what failed now passes. The flags and the verdict are
    judge()'s."""
    closed = datetime.fromisoformat(investigation["closed_at"])
    taken = (closed + after).isoformat()
    reran = []
    for held in investigation["readings"]:
        reading = held["reading"]
        now = "pass" if fixed and reading["verdict"] == "fail" else reading["verdict"]
        run = reading | {"verdict": now, "taken_at": taken, "expires_at": None}
        if now == "pass":
            run["reason"] = None
        reran.append(
            {
                "reading_id": held["id"],
                "was": reading["verdict"],
                "probe_id": reading["probe_id"],
                "target": reading["target"],
                "environment": reading["environment"],
                "runs": [run, copy.deepcopy(run)],
            }
        )
    changes = [TOKEN_FIX] if changes is None else changes
    judged = judge(
        tuple(Rerun.model_validate(r) for r in reran),
        tuple(Change.model_validate(c) for c in changes),
        "cap-before",
        "cap-after",
        (),
    )
    return {
        "id": f"ver-{number:016x}",
        "investigation_id": investigation["id"],
        "environment": investigation["environment"],
        "applied_change": changes,
        "reran": reran,
        "before_capture": "cap-before",
        "after_capture": "cap-after",
        "differences": [],
        "failing_now_passes": judged.failing_now_passes,
        "no_regressions": judged.no_regressions,
        "changes_explained": judged.changes_explained,
        "verdict": judged.verdict.value,
        "reason": f"judged {judged.verdict.value}",
        "verified_at": (closed + after + timedelta(seconds=30)).isoformat(),
    }


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency — see test_registry_api.py
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE verifications DISABLE TRIGGER USER"))
        await conn.execute(text("ALTER TABLE narrations DISABLE TRIGGER USER"))
        await conn.execute(text("TRUNCATE investigations, verifications, narrations CASCADE"))
        await conn.execute(text("ALTER TABLE verifications ENABLE TRIGGER USER"))
        await conn.execute(text("ALTER TABLE narrations ENABLE TRIGGER USER"))

    os.environ["INVESTIGATION_WRITER_DATABASE_URL"] = role_database_url(
        "investigation-writer", "INVESTIGATION_WRITER_DB_PASSWORD"
    )
    os.environ["VERIFICATION_WRITER_DATABASE_URL"] = role_database_url(
        "verification-writer", "VERIFICATION_WRITER_DB_PASSWORD"
    )
    os.environ["CULPRIT_PROJECT_TOKEN"] = PROJECT_TOKEN
    from app.facts import dependencies as facts_dependencies

    importlib.reload(facts_dependencies)
    from app.agents import dependencies as agents_dependencies

    importlib.reload(agents_dependencies)
    from app.investigations import router as investigations_router
    from app.outcomes import router as outcomes_router
    from app.verifications import router as verifications_router

    for module in (investigations_router, verifications_router, outcomes_router):
        importlib.reload(module)
    from app.auth.dependencies import require_auth
    from app.errors import install as install_error_handlers

    engines = {
        "investigation_writer_session_factory": create_async_engine(
            os.environ["INVESTIGATION_WRITER_DATABASE_URL"]
        ),
        "verification_writer_session_factory": create_async_engine(
            os.environ["VERIFICATION_WRITER_DATABASE_URL"]
        ),
        "session_factory": create_async_engine(
            role_database_url("api-reader", "API_READER_PASSWORD")
        ),
    }
    app = FastAPI()
    for name, engine in engines.items():
        setattr(app.state, name, async_sessionmaker(engine, expire_on_commit=False))
    install_error_handlers(app)
    for module in (investigations_router, verifications_router, outcomes_router):
        app.include_router(module.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "tester", "role": "member"}

    with TestClient(app) as test_client:
        yield test_client

    for engine in engines.values():
        await engine.dispose()


def _auth(token: str | None = PROJECT_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def store(client: TestClient, name: str) -> dict[str, Any]:
    investigation = recorded(name)
    response = client.post("/investigations", json=investigation, headers=_auth())
    assert response.status_code == 201, response.text
    return investigation


def post(client: TestClient, verification: dict[str, Any], source: str = "planted", **kw):
    return client.post(
        f"/investigations/{verification['investigation_id']}/verifications",
        json={"source": source, "verification": verification},
        headers=kw.get("headers", _auth()),
    )


# ---- what is stored, and what is not touched ----------------------------------------


@pytest.mark.asyncio
async def test_a_verification_is_stored_beside_an_investigation_it_never_touches(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    investigation = store(client, "auth-audience")
    snapshot = text(
        "SELECT (SELECT row_to_json(i)::text FROM investigations i WHERE id = :id), "
        "(SELECT json_agg(r ORDER BY r.id)::text FROM investigation_readings r "
        " WHERE investigation_id = :id)"
    )
    async with db_engine.connect() as conn:
        before = (await conn.execute(snapshot, {"id": investigation["id"]})).one()

    verification = verification_of(investigation)
    assert verification["verdict"] == "verified"
    response = post(client, verification)
    assert response.status_code == 201, response.text
    assert response.json() == {"id": verification["id"], "verdict": "verified"}

    async with db_engine.connect() as conn:
        after = (await conn.execute(snapshot, {"id": investigation["id"]})).one()
    assert tuple(after) == tuple(before), "posting a verification changed the investigation"

    listed = client.get(f"/investigations/{investigation['id']}/verifications").json()
    assert [item["verification"]["id"] for item in listed["items"]] == [verification["id"]]
    assert listed["items"][0]["source"] == "planted"
    assert listed["items"][0]["submitted_by"] == "project-token"


def test_verifications_are_listed_newest_first(client: TestClient) -> None:
    investigation = store(client, "auth-audience")
    wrong = verification_of(investigation, fixed=False, number=1)
    right = verification_of(investigation, after=timedelta(minutes=20), number=2)
    assert wrong["verdict"] == "not_resolved" and right["verdict"] == "verified"
    for verification in (wrong, right):
        assert post(client, verification).status_code == 201
    listed = client.get(f"/investigations/{investigation['id']}/verifications").json()
    assert [item["verification"]["verdict"] for item in listed["items"]] == [
        "verified",
        "not_resolved",
    ]


def test_the_same_verification_twice_is_a_409(client: TestClient) -> None:
    verification = verification_of(store(client, "auth-audience"))
    assert post(client, verification).status_code == 201
    assert post(client, verification).status_code == 409


def test_a_verification_needs_the_project_token_or_an_agent(client: TestClient) -> None:
    verification = verification_of(store(client, "auth-audience"))
    assert post(client, verification, headers={}).status_code == 401
    assert post(client, verification, headers=_auth("not-the-token")).status_code == 401


def test_an_unknown_investigation_is_a_404(client: TestClient) -> None:
    verification = verification_of(recorded("auth-audience"))
    assert post(client, verification).status_code == 404


def test_the_source_must_be_said(client: TestClient) -> None:
    verification = verification_of(store(client, "auth-audience"))
    for body in ({"verification": verification}, {"source": "lab", "verification": verification}):
        response = client.post(
            f"/investigations/{verification['investigation_id']}/verifications",
            json=body,
            headers=_auth(),
        )
        assert response.status_code == 422, response.text


# ---- what the API refuses -------------------------------------------------------------


def test_a_verification_whose_runs_predate_the_investigation_is_refused(
    client: TestClient,
) -> None:
    verification = verification_of(store(client, "auth-audience"), after=-timedelta(hours=1))
    response = post(client, verification)
    assert response.status_code == 422, response.text
    assert "before the investigation closed" in response.json()["detail"]


def test_a_verification_whose_runs_are_from_the_future_is_refused(client: TestClient) -> None:
    investigation = store(client, "auth-audience")
    closed = datetime.fromisoformat(investigation["closed_at"])
    ahead = datetime.now(closed.tzinfo) - closed + timedelta(hours=2)
    response = post(client, verification_of(investigation, after=ahead))
    assert response.status_code == 422, response.text
    assert "after now" in response.json()["detail"]


def test_a_verification_cannot_be_judged_before_its_runs_or_after_now(
    client: TestClient,
) -> None:
    investigation = store(client, "auth-audience")
    early = verification_of(investigation)
    early["verified_at"] = investigation["closed_at"]
    response = post(client, early)
    assert response.status_code == 422 and "before its last run" in response.text, response.text
    late = verification_of(investigation)
    late["verified_at"] = "2099-01-01T00:00:00+00:00"
    response = post(client, late)
    assert response.status_code == 422 and "after now" in response.text, response.text


def test_one_investigations_fault_is_planted_or_real_not_both(client: TestClient) -> None:
    investigation = store(client, "auth-audience")
    assert (
        post(client, verification_of(investigation, number=1), source="planted").status_code == 201
    )
    relabelled = post(client, verification_of(investigation, number=2), source="real")
    assert relabelled.status_code == 409, relabelled.text
    assert "cannot also be real" in relabelled.json()["detail"]


def test_a_verification_whose_was_disagrees_with_the_stored_reading_is_refused(
    client: TestClient,
) -> None:
    investigation = store(client, "auth-audience")
    verification = verification_of(investigation)
    # A reading that failed, said to have passed: its re-run is now a
    # regression check, and judge() agrees with the record as written —
    # only the investigation can show it is false.
    target = next(r for r in verification["reran"] if r["was"] == "fail")
    target["was"] = "pass"
    rejudged = judge(
        tuple(Rerun.model_validate(r) for r in verification["reran"]),
        (Change.model_validate(TOKEN_FIX),),
        "cap-before",
        "cap-after",
        (),
    )
    verification |= {
        "failing_now_passes": rejudged.failing_now_passes,
        "no_regressions": rejudged.no_regressions,
        "verdict": rejudged.verdict.value,
    }
    response = post(client, verification)
    assert response.status_code == 422, response.text
    assert f"re-run of {target['reading_id']} says it was pass" in response.json()["detail"]


def test_a_verification_whose_verdict_judge_does_not_reach_is_refused(
    client: TestClient,
) -> None:
    verification = verification_of(store(client, "auth-audience"), fixed=False)
    assert verification["verdict"] == "not_resolved"
    verification |= {"verdict": "verified", "failing_now_passes": True}
    response = post(client, verification)
    assert response.status_code == 422, response.text
    assert "its readings say" in response.text or "its record supports" in response.text


def test_a_verification_of_part_of_the_reading_set_is_refused(client: TestClient) -> None:
    verification = verification_of(store(client, "auth-audience"))
    dropped = verification["reran"].pop()
    response = post(client, verification)
    assert response.status_code == 422, response.text
    assert f"does not re-run {dropped['reading_id']}" in response.json()["detail"]


def test_credentials_in_a_verification_are_redacted_on_the_way_in(client: TestClient) -> None:
    """Invariant 11, at the verification's choke point: every run, the
    reason and an action's words are redacted here, whatever the binary did."""
    investigation = store(client, "auth-audience")
    leaked = "postgresql://svc:hunter2-not-real@db.internal:5432/app"
    verification = verification_of(
        investigation,
        changes=[TOKEN_FIX, {"kind": "action", "description": f"rotated {leaked}"}],
    )
    verification["reason"] = f"judged against {leaked}"
    for run in verification["reran"][0]["runs"]:
        run["measured"] = {"url": leaked}
    assert post(client, verification).status_code == 201
    stored = client.get(f"/investigations/{investigation['id']}/verifications").text
    assert "hunter2-not-real" not in stored


# ---- append-only ------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE verifications SET verdict = 'verified'",
        "DELETE FROM verifications",
        "TRUNCATE verifications",
    ],
)
async def test_no_role_the_owner_included_can_rewrite_a_verification(
    client: TestClient, role_database_url, db_engine: AsyncEngine, statement: str
) -> None:
    assert (
        post(client, verification_of(store(client, "auth-audience"), fixed=False)).status_code
        == 201
    )
    roles = {
        "owner": db_engine,
        "verification-writer": create_async_engine(
            role_database_url("verification-writer", "VERIFICATION_WRITER_DB_PASSWORD")
        ),
        "api-reader": create_async_engine(role_database_url("api-reader", "API_READER_PASSWORD")),
    }
    try:
        for name, engine in roles.items():
            with pytest.raises(DBAPIError, match=r"permission denied|append-only"):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
            assert name  # each role refused in turn
    finally:
        for name, engine in roles.items():
            if name != "owner":
                await engine.dispose()


@pytest.mark.asyncio
async def test_without_its_trigger_the_owner_could_rewrite_one(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """The red half of the test above: with the trigger dropped (inside a
    transaction that is rolled back), the owner's UPDATE goes through — so
    it is the trigger, and nothing else, that refuses it."""
    assert (
        post(client, verification_of(store(client, "auth-audience"), fixed=False)).status_code
        == 201
    )
    async with db_engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(
                text("DROP TRIGGER verifications_no_update_or_delete ON verifications")
            )
            changed = await conn.execute(text("UPDATE verifications SET verdict = 'inconclusive'"))
            assert changed.rowcount == 1
            gone = await conn.execute(text("DELETE FROM verifications"))
            assert gone.rowcount == 1
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_the_verification_writer_can_only_append(
    client: TestClient, role_database_url
) -> None:
    writer = create_async_engine(
        role_database_url("verification-writer", "VERIFICATION_WRITER_DB_PASSWORD")
    )
    try:
        for statement in (
            "SELECT * FROM verifications",
            "SELECT * FROM investigations",
            "INSERT INTO investigations (id, opened_at, environment, symptom, ingested_at) "
            "VALUES ('inv-x', now(), 'e', '{}', now())",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                async with writer.begin() as conn:
                    await conn.execute(text(statement))
    finally:
        await writer.dispose()


@pytest.mark.asyncio
async def test_the_database_refuses_a_verified_row_with_a_clause_false(
    client: TestClient, role_database_url
) -> None:
    store(client, "auth-audience")
    writer = create_async_engine(
        role_database_url("verification-writer", "VERIFICATION_WRITER_DB_PASSWORD")
    )
    try:
        with pytest.raises(DBAPIError, match="ck_verifications_verified_needs_every_clause"):
            async with writer.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO verifications (id, investigation_id, environment, verdict, "
                        "failing_now_passes, no_regressions, changes_explained, verified_at, "
                        "source, submitted_by, verification, ingested_at) VALUES "
                        "('ver-00000000000000ff', :inv, 'e', 'verified', true, true, false, "
                        "now(), 'real', 'project-token', '{}', now())"
                    ),
                    {"inv": recorded("auth-audience")["id"]},
                )
    finally:
        await writer.dispose()


# ---- outcomes ---------------------------------------------------------------------------


def test_with_nothing_recorded_accuracy_says_so(client: TestClient) -> None:
    body = client.get("/outcomes/accuracy").json()
    assert body["outcomes"] == 0
    assert body["classes"] == []
    assert "No outcomes are recorded" in body["statement"]
    assert "not 0%, and not 100%" in body["statement"]


@pytest.mark.asyncio
async def test_accuracy_gives_exactly_the_numbers_seeded(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """Seeded straight into the tables, so every count is known: per class
    and source, each verdict, the denominator, the inconclusive count —
    from each investigation's latest verification only, and only where the
    diagnosis is complete."""
    rows = [
        # (investigation, complete, root, [(verdict, source, minutes)])
        ("inv-a000000000000001", True, AUDIENCE,
         [("not_resolved", "planted", 1), ("verified", "planted", 2)]),
        ("inv-a000000000000002", True, AUDIENCE,
         [("verified", "planted", 1)]),
        ("inv-a000000000000003", True, AUDIENCE,
         [("inconclusive", "planted", 1)]),
        ("inv-a000000000000004", True, EDGE,
         [("regressed", "planted", 1)]),
        ("inv-a000000000000005", True, EDGE,
         [("verified", "real", 1)]),
        ("inv-a000000000000006", True, PROVIDER_KEY,
         [("changed_underneath", "real", 1), ("not_resolved", "real", 3)]),
        ("inv-a000000000000007", False, ORDER_SERVICE,
         [("inconclusive", "planted", 1)]),
    ]  # fmt: skip
    number = 0
    async with db_engine.begin() as conn:
        for investigation, complete, root, verifications in rows:
            await conn.execute(
                text(
                    "INSERT INTO investigations (id, opened_at, environment, symptom, "
                    "root_subject, complete, ingested_at) "
                    "VALUES (:id, now(), 'e', '{}', :root, :complete, now())"
                ),
                {"id": investigation, "root": root, "complete": complete},
            )
            for verdict, source, minutes in verifications:
                number += 1
                clause = verdict == "verified"
                await conn.execute(
                    text(
                        "INSERT INTO verifications (id, investigation_id, environment, verdict, "
                        "failing_now_passes, no_regressions, changes_explained, verified_at, "
                        "source, submitted_by, verification, ingested_at) VALUES "
                        "(:id, :inv, 'e', :verdict, :c, :c, :c, "
                        "now() + make_interval(mins => :minutes), :source, 'project-token', "
                        "'{}', now())"
                    ),
                    {
                        "id": f"ver-{number:016x}",
                        "inv": investigation,
                        "verdict": verdict,
                        "c": clause,
                        "minutes": minutes,
                        "source": source,
                    },
                )

    body = client.get("/outcomes/accuracy").json()
    assert body["outcomes"] == 6
    assert body["partial_diagnoses_not_counted"] == 1
    assert body["statement"] is None
    zero = dict.fromkeys(
        ("verified", "not_resolved", "regressed", "changed_underneath", "inconclusive"), 0
    )
    assert body["classes"] == [
        {
            "fault_class": "auth",
            "source": "planted",
            "outcomes": 3,
            "verdicts": zero | {"verified": 2, "inconclusive": 1},
            "decided": 2,
            "verified_share": 1.0,
            "inconclusive": 1,
        },
        {
            "fault_class": "connection",
            "source": "planted",
            "outcomes": 1,
            "verdicts": zero | {"regressed": 1},
            "decided": 1,
            "verified_share": 0.0,
            "inconclusive": 0,
        },
        {
            "fault_class": "config",
            "source": "real",
            "outcomes": 1,
            "verdicts": zero | {"not_resolved": 1},
            "decided": 1,
            "verified_share": 0.0,
            "inconclusive": 0,
        },
        {
            "fault_class": "connection",
            "source": "real",
            "outcomes": 1,
            "verdicts": zero | {"verified": 1},
            "decided": 1,
            "verified_share": 1.0,
            "inconclusive": 0,
        },
    ]
    assert "planted on purpose" in body["method"]


def test_a_class_with_only_inconclusive_outcomes_has_no_share() -> None:
    from app.verifications.service import tally

    report = tally(
        [
            {
                "complete": True,
                "root_subject": STOCK_ROUTE,
                "verdict": "inconclusive",
                "source": "planted",
            }
        ]
    )
    assert report["classes"][0]["decided"] == 0
    assert report["classes"][0]["verified_share"] is None
    assert report["classes"][0]["inconclusive"] == 1
