"""`GET /probes` and `POST /probes/{id}/run` (Phase 31).

Two things are being held down here.

**The catalogue is a mirror, and a mirror that drifts is worse than no
mirror** — it describes a probe the binary does not have, or omits one it
does. `api/app/readings/catalogue.json` is therefore checked against the
Go source it was copied from, not against itself.

**The run endpoint refuses, and must keep refusing.** Probes execute in
the `culprit` binary; this API has no agent transport until Phase 33.
The failure mode worth a test is not the 503 — it is a future change that
makes the endpoint "work" by synthesising a reading, which would put a
row in the OBSERVED plane that nobody measured. So the assertion is both
halves: the status code, and that the table is untouched.
"""

import importlib
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from app.readings import catalogue
from culprit_model.readings import Cost, Effect, ProbeManifest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PROJECT_TOKEN = "test-project-token-not-a-real-secret"
GO_PROBES = Path(__file__).parents[2] / "cli" / "internal" / "probe"

#: `ID: "probe.net.tcp_connect"` and friends, one per manifest literal.
_GO_ID = re.compile(r'ID:\s*"(probe\.[a-z0-9_.]+)"')
#: `Effect: model.EffectInspect` / `TimeoutMS: 5_000`.
_GO_EFFECT = re.compile(r"Effect:\s*model\.Effect([A-Za-z]+)")
_GO_TIMEOUT = re.compile(r"TimeoutMS:\s*([0-9_]+)")


def _go_manifests() -> dict[str, tuple[str, int]]:
    """`{probe_id: (effect, timeout_ms)}`, read out of the Go source.

    A regex over source text rather than a parse, for the same reason
    `scripts/check_no_llm_imports.py` scans Go by line: this repository
    has no Go parser, and the declarations are single-line struct fields
    that a regex reads exactly. Splitting on the struct literal keeps each
    manifest's fields with their own manifest.
    """
    found: dict[str, tuple[str, int]] = {}
    for path in sorted(GO_PROBES.glob("*_probes.go")):
        source = path.read_text(encoding="utf-8")
        for chunk in source.split("model.ProbeManifest{")[1:]:
            probe_id = _GO_ID.search(chunk)
            effect = _GO_EFFECT.search(chunk)
            timeout = _GO_TIMEOUT.search(chunk)
            assert probe_id and effect and timeout, f"unparsed manifest in {path.name}"
            found[probe_id.group(1)] = (
                effect.group(1).lower(),
                int(timeout.group(1).replace("_", "")),
            )
    return found


def test_the_catalogue_file_parses_as_probe_manifests() -> None:
    """Every entry is a valid `ProbeManifest`, and there are sixteen.

    Validity is not a formality: `ProbeManifest` refuses `effect: mutate`
    and refuses `expected_from: OBSERVED`, so a mirror that parses is a
    mirror that cannot describe a probe which writes, or one that claims a
    reading is its own expectation.
    """
    assert len(catalogue.CATALOGUE) == 16
    for manifest in catalogue.CATALOGUE:
        assert isinstance(manifest, ProbeManifest)
        assert manifest.effect is not Effect.MUTATE
        # One probe sends more than a request or two: the latency probe's
        # fixed 20 or 50 (Phase 36), which is what `metered` says.
        expected = Cost.METERED if manifest.id == "probe.http.latency" else Cost.CHEAP
        assert manifest.cost is expected, manifest.id


def test_the_catalogue_mirrors_the_go_source() -> None:
    """The ids, effects and timeouts the binary compiles in."""
    go = _go_manifests()
    mirrored = {m.id: (str(m.effect), m.timeout_ms) for m in catalogue.CATALOGUE}
    assert mirrored == go


def test_the_catalogue_is_sorted_by_id() -> None:
    """`Catalogue.Manifests()` sorts; so does this. Two descriptions of
    one set should order it the same way, so that diffing the two outputs
    is diffing their content."""
    ids = [manifest.id for manifest in catalogue.CATALOGUE]
    assert ids == sorted(ids)


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency — see test_registry_api.py
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE readings"))

    os.environ["PROBE_WRITER_DATABASE_URL"] = role_database_url(
        "probe-writer", "PROBE_WRITER_DB_PASSWORD"
    )
    os.environ["CULPRIT_PROJECT_TOKEN"] = PROJECT_TOKEN

    from app.facts import dependencies as facts_dependencies
    from app.readings import config as readings_config

    importlib.reload(readings_config)
    importlib.reload(facts_dependencies)
    from app.readings import router as readings_router_module

    importlib.reload(readings_router_module)

    from app.auth.dependencies import require_auth
    from app.errors import install as install_error_handlers
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    writer = create_async_engine(readings_config.PROBE_WRITER_DATABASE_URL)
    app = FastAPI()
    app.state.probe_writer_session_factory = async_sessionmaker(writer, expire_on_commit=False)
    install_error_handlers(app)
    app.include_router(readings_router_module.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "tester", "role": "member"}

    with TestClient(app) as test_client:
        yield test_client
    await writer.dispose()


def test_the_catalogue_is_served(client: TestClient) -> None:
    response = client.get("/probes")
    assert response.status_code == 200, response.text
    probes = response.json()["probes"]
    assert len(probes) == 16
    assert {probe["id"] for probe in probes} == set(_go_manifests())


@pytest.mark.asyncio
async def test_running_a_probe_is_refused_and_writes_nothing(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    response = client.post("/probes/probe.net.dns_resolve/run")
    assert response.status_code == 503, response.text

    body = response.json()
    assert body["probe_id"] == "probe.net.dns_resolve"
    # The useful half: a caller that wanted a measurement can copy this
    # and have one.
    assert body["run_locally"].startswith("culprit probe probe.net.dns_resolve")
    # Not a transient outage. A caller should not retry this forever.
    assert body["available_from"] == "Phase 33"

    async with db_engine.begin() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM readings"))).scalar_one()
    assert count == 0, "a refused probe run must not fabricate a reading"


def test_running_an_unknown_probe_is_a_404(client: TestClient) -> None:
    """A typo should be told it is a typo, not handed the generic
    "no agent connected" answer — which would read as "that probe exists
    and we could not run it"."""
    response = client.post("/probes/probe.net.does_not_exist/run")
    assert response.status_code == 404, response.text
