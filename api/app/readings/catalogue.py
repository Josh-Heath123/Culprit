"""The probe catalogue, mirrored from the Go binary.

**The catalogue lives in `cli/internal/probe`, not here.** A probe is
code: a manifest plus the procedure that runs it, registered in
`probe.BuiltIn()`. This API cannot run any of them (Phase 31 field 3 —
probes execute in the `culprit` binary), so it holds no procedures, only
the descriptions.

It has to hold those, though. The control plane must be able to *describe*
a probe without executing one: `GET /probes` is what a dashboard reads to
explain a stored reading — what `probe.db.schema_conformance` measures,
which capability it needs, which plane supplies its expectation — and
that question arrives long after the run that produced the reading, from
a browser that has no `culprit` binary anywhere near it. Answering it by
shelling out to a binary would make a read-only description depend on an
executable being installed next to the API, on the API being allowed to
spawn processes, and on the two versions matching anyway.

So the manifests are a committed JSON file, loaded and validated through
`culprit_model.readings.ProbeManifest` — the same model the Go side is
held to by `shared/tests/reading_conformance.json`. The field names in
`catalogue.json` are the Go struct's own JSON tags, so the mirror is the
same bytes the binary would emit, not a translation of them.

The copy is kept honest by `api/tests/test_probes_api.py`, which parses
every entry through the model and asserts the id set matches the thirteen
`builtIn()` registers. A manifest that drifts is a manifest that fails
that test; a manifest that is *invalid* fails at import, here, rather
than at the first request.
"""

import json
from pathlib import Path

from culprit_model.readings import ProbeManifest

CATALOGUE_PATH = Path(__file__).with_name("catalogue.json")


def _load() -> tuple[ProbeManifest, ...]:
    raw = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    # Sorted by id, matching `Catalogue.Manifests()` in Go: two sources
    # describing the same set should also order it the same way, so a
    # diff of the two outputs is a diff of their content.
    return tuple(sorted((ProbeManifest(**entry) for entry in raw), key=lambda m: m.id))


#: Validated at import. A broken mirror is a deployment-time failure with
#: a pydantic traceback naming the field, not a 500 on the first read.
CATALOGUE: tuple[ProbeManifest, ...] = _load()

_BY_ID: dict[str, ProbeManifest] = {manifest.id: manifest for manifest in CATALOGUE}


def get(probe_id: str) -> ProbeManifest | None:
    """The manifest for `probe_id`, or None if no probe has that id."""
    return _BY_ID.get(probe_id)
