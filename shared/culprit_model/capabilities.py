"""The §2.7 capability vocabulary — the Python half of `cli/internal/capability`.

Phase 30. The Go CLI parses grants from `culprit.yaml` and enforces them;
this is the same closed set on the control-plane side, so that a grant
list arriving in a capture (`CaptureBundle.grants`), a refusal, a
`grant_ref`, and the `environments:` section `apply-model` accepts all
mean one thing. The Phase 30 invariant audit found the Python side
accepting free strings — a capture listing `db.schema.write` was stored
and served back as a grant it "ran under", and `apply-model` accepted
`config.read.values: true` — while `docs/PERMISSIONS.md` promised both
were validation errors. True in Go only is not true.

Held to the Go set by `shared/tests/capability_conformance.json`, which
both languages read. **No `*.write` member exists**, and adding one is a
design decision requiring its own plan document (docs/HANDOFF.md §2), not
an enum edit.

Deterministic and dependency-free (`.claude/rules/determinism.md`).
"""

from enum import StrEnum


class Capability(StrEnum):
    MODEL_READ = "model.read"
    REPO_READ = "repo.read"
    CONFIG_READ_NAMES = "config.read.names"
    CONFIG_READ_VALUES = "config.read.values"
    DB_METADATA_READ = "db.metadata.read"
    DB_ROWS_READ = "db.rows.read"
    NET_DNS_RESOLVE = "net.dns.resolve"
    NET_TCP_CONNECT = "net.tcp.connect"
    NET_TLS_INSPECT = "net.tls.inspect"
    NET_HTTP_OUTBOUND = "net.http.outbound"
    TELEMETRY_LOGS_READ = "telemetry.logs.read"
    TELEMETRY_METRICS_READ = "telemetry.metrics.read"
    TELEMETRY_TRACES_READ = "telemetry.traces.read"
    DEPLOY_METADATA_READ = "deploy.metadata.read"
    PROCESS_EXEC_ALLOWLIST = "process.exec.allowlist"


#: Granted per item — a list, never `true`. A blanket grant is exactly
#: what the per-item rule exists to prevent.
ALLOWLISTED: frozenset[Capability] = frozenset(
    {
        Capability.CONFIG_READ_VALUES,
        Capability.DB_ROWS_READ,
        Capability.PROCESS_EXEC_ALLOWLIST,
    }
)
