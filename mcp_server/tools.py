"""The four read-only MCP tools (Phase 24, docs/AI_NATIVE_PLAN.md) a
coding agent can call before making a change. Every tool is a plain SQL
read (via the `mcp-reader` role, granted SELECT only -- see the phase's
own migration) plus, for the two search-flavored tools, one Voyage
`embed_query` call. No business logic beyond what Phase 21/23 already
computed and stored; no LLM call generates a narrative, summary, or
judgment of its own here (invariant 8/CLAUDE.md's "Where the AI must
stay deterministic" section extends to MCP tools, not just hooks).

Every result returned here is a historical/observed fact from this
specific repository's own records -- never a live static analysis of
the current working tree. This matters most for `culprit_coupled_files`
(Known Trap 2): an empty result means "no *declared* coupling," not "safe
to change freely" -- Phase 22's registry is seeded with exactly one pair,
so most real couplings in any given codebase using this system will not
be declared yet.
"""

import os
from typing import Literal

import sqlalchemy as sa
import yaml
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations
from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import literal, select, union_all
from sqlalchemy.dialects.postgresql import JSONB, UUID

# voyageai/__init__.py imports AsyncClient without re-exporting it (no
# __all__), so pyright's reportPrivateImportUsage flags
# `voyageai.AsyncClient` even though it's the SDK's documented public
# entry point -- importing from the submodule directly satisfies the
# type checker without a blanket ignore. Identical reasoning to
# worker/app/rag/embeddings.py's own comment on this exact import.
from voyageai.client_async import AsyncClient

from .config import COUPLED_FILES_YAML
from .server import mcp

# --- Duplicated from worker/app/rag/embeddings.py (Known Trap 1) ---------
# mcp_server and worker are separate uv projects with no path dependency
# between them -- copy, not import. Keep this in sync by hand if
# worker's own embed_query ever changes; promote to
# shared/culprit_shared/ later only if that duplication becomes a real
# maintenance problem, not preemptively.

EMBEDDING_MODEL = "voyage-4"

_voyage_client: AsyncClient | None = None


def _get_voyage_client() -> AsyncClient:
    global _voyage_client
    if _voyage_client is None:
        _voyage_client = AsyncClient(api_key=os.environ["VOYAGE_API_KEY"])
    return _voyage_client


async def _embed_query(text: str) -> list[float]:
    """input_type="query" -- for text used to search the index, not text
    being indexed. Voyage's document/query embeddings are optimized
    asymmetrically even for the same model."""
    result = await _get_voyage_client().embed([text], model=EMBEDDING_MODEL, input_type="query")
    return [float(x) for x in result.embeddings[0]]


# --- Minimal Core table mirrors -------------------------------------------
# Same "only enough shape to SELECT" principle as worker/app/db.py's own
# docstring -- only the columns these four tools actually read.

metadata = sa.MetaData()

postmortems = sa.Table(
    "postmortems",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("title", sa.String(), nullable=False),
    sa.Column("body", sa.String(), nullable=False),
    sa.Column("embedding", Vector(1024), nullable=True),
)

architecture_decisions = sa.Table(
    "architecture_decisions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("title", sa.String(), nullable=False),
    sa.Column("body", sa.String(), nullable=False),
    sa.Column("embedding", Vector(1024), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
)

ai_change_records = sa.Table(
    "ai_change_records",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("commit_sha", sa.String(), nullable=False),
    sa.Column("summary", sa.String(), nullable=False),
    sa.Column("files_changed", JSONB(), nullable=False),
    sa.Column("embedding", Vector(1024), nullable=True),
    sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
)

invariant_violations = sa.Table(
    "invariant_violations",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("invariant_name", sa.String(), nullable=False),
    sa.Column("message", sa.String(), nullable=False),
    sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("ai_change_record_id", UUID(as_uuid=True), nullable=True),
)

incident_change_links = sa.Table(
    "incident_change_links",
    metadata,
    sa.Column("incident_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("ai_change_record_id", UUID(as_uuid=True), primary_key=True),
)

incident_candidates = sa.Table(
    "incident_candidates",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
)


# --- culprit_search_memory -------------------------------------------------

RecordType = Literal["postmortem", "decision", "ai_change"]
ALL_RECORD_TYPES: tuple[RecordType, ...] = ("postmortem", "decision", "ai_change")


class SearchMemoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        min_length=1,
        description="Natural-language text to search for, e.g. 'flaky retry loop in order "
        "service'",
    )
    record_types: list[RecordType] = Field(
        default_factory=lambda: list(ALL_RECORD_TYPES),
        description="Which record kinds to search -- postmortem, decision, and/or ai_change. "
        "Defaults to all three.",
    )
    top_k: int = Field(default=5, ge=1, le=50, description="Maximum number of results to return")


class SearchResult(BaseModel):
    type: RecordType
    id: str
    title: str
    summary: str
    similarity: float
    url: str | None = Field(
        default=None,
        description="Relative dashboard path, when this record type has a dedicated page "
        "(postmortems only today)",
    )


def _select_for(record_type: RecordType, query_embedding: list[float]) -> sa.Select:
    """One SELECT per table, shaped identically so union_all can combine
    them -- duplicated from worker/app/rag/retrieval.py::_select_for
    (Known Trap 1), not imported. `ai_change_records` has no `title`
    column; `commit_sha` stands in for one here, matching that module's
    own convention."""
    if record_type == "postmortem":
        table, title_col, body_col = postmortems, postmortems.c.title, postmortems.c.body
    elif record_type == "decision":
        table, title_col, body_col = (
            architecture_decisions,
            architecture_decisions.c.title,
            architecture_decisions.c.body,
        )
    else:
        table, title_col, body_col = (
            ai_change_records,
            ai_change_records.c.commit_sha,
            ai_change_records.c.summary,
        )

    distance = table.c.embedding.cosine_distance(query_embedding)
    return (
        select(
            table.c.id,
            literal(record_type).label("record_type"),
            title_col.label("title"),
            body_col.label("body"),
            (1 - distance).label("similarity"),
        )
        .where(table.c.embedding.is_not(None))
    )


def _result_url(record_type: RecordType, record_id: str) -> str | None:
    if record_type == "postmortem":
        return f"/postmortems/{record_id}"
    return None


@mcp.tool(
    name="culprit_search_memory",
    annotations=ToolAnnotations(
        title="Search Culprit's engineering memory",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def culprit_search_memory(params: SearchMemoryInput, ctx: Context) -> list[SearchResult]:
    """Semantic search over this repository's own postmortems,
    architecture decisions, and AI change records -- a retrieval
    interface over data Culprit already owns, not a live analysis of the
    current working tree. Results are historical/observed facts recorded
    by this specific repository's own Culprit install, ranked by
    similarity to `query`.

    Returns an empty list, not an error, when nothing matches closely
    enough to be in the top `top_k` -- Culprit doesn't apply a
    similarity threshold, so a low-similarity result can still appear if
    nothing better exists; check the `similarity` field yourself before
    treating a result as a strong match.
    """
    if not params.record_types:
        raise ValueError("record_types must name at least one record type")

    engine = ctx.request_context.lifespan_context.engine
    query_embedding = await _embed_query(params.query)

    combined = union_all(
        *(_select_for(rt, query_embedding) for rt in params.record_types)
    ).subquery()

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(combined).order_by(combined.c.similarity.desc()).limit(params.top_k)
            )
        ).all()

    return [
        SearchResult(
            type=row.record_type,
            id=str(row.id),
            title=row.title,
            summary=row.body,
            similarity=row.similarity,
            url=_result_url(row.record_type, str(row.id)),
        )
        for row in rows
    ]


# --- culprit_file_history ---------------------------------------------------


class ViolationSummary(BaseModel):
    invariant_name: str
    message: str
    detected_at: str | None


class LinkedIncidentSummary(BaseModel):
    id: str
    status: str
    opened_at: str


class FileHistoryEntry(BaseModel):
    commit_sha: str
    summary: str
    committed_at: str
    violations: list[ViolationSummary]
    linked_incidents: list[LinkedIncidentSummary]


class FileHistoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    file_path: str = Field(
        ..., min_length=1, description="Repo-relative file path, e.g. 'worker/app/db.py'"
    )
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of commits to return")


@mcp.tool(
    name="culprit_file_history",
    annotations=ToolAnnotations(
        title="Look up a file's AI change history",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def culprit_file_history(params: FileHistoryInput, ctx: Context) -> list[FileHistoryEntry]:
    """AI change records (Phase 21) whose `files_changed` includes
    `file_path` exactly, most recent commit first -- each annotated with
    any Phase 22 invariant violations that commit caused and any Phase 23
    incident links it was judged related to. This is the "has this file
    caused a problem before" answer: an empty `violations` and empty
    `linked_incidents` on every entry means no violation or incident was
    ever recorded against this file's changes, not that the file is safe
    -- Culprit only records what it actually observed.

    Returns an empty list, not an error, when `file_path` has no AI
    change record at all (never touched by a commit made inside a
    Claude Code session with this repo's hook installed).
    """
    engine = ctx.request_context.lifespan_context.engine

    async with engine.connect() as conn:
        change_rows = (
            await conn.execute(
                select(
                    ai_change_records.c.id,
                    ai_change_records.c.commit_sha,
                    ai_change_records.c.summary,
                    ai_change_records.c.committed_at,
                )
                .where(ai_change_records.c.files_changed.contains([params.file_path]))
                .order_by(ai_change_records.c.committed_at.desc())
                .limit(params.limit)
            )
        ).all()

        entries: list[FileHistoryEntry] = []
        for row in change_rows:
            violation_rows = (
                await conn.execute(
                    select(
                        invariant_violations.c.invariant_name,
                        invariant_violations.c.message,
                        invariant_violations.c.detected_at,
                    ).where(invariant_violations.c.ai_change_record_id == row.id)
                )
            ).all()
            incident_rows = (
                await conn.execute(
                    select(
                        incident_candidates.c.id,
                        incident_candidates.c.status,
                        incident_candidates.c.opened_at,
                    )
                    .join(
                        incident_change_links,
                        incident_change_links.c.incident_id == incident_candidates.c.id,
                    )
                    .where(incident_change_links.c.ai_change_record_id == row.id)
                )
            ).all()

            entries.append(
                FileHistoryEntry(
                    commit_sha=row.commit_sha,
                    summary=row.summary,
                    committed_at=row.committed_at.isoformat(),
                    violations=[
                        ViolationSummary(
                            invariant_name=v.invariant_name,
                            message=v.message,
                            detected_at=v.detected_at.isoformat() if v.detected_at else None,
                        )
                        for v in violation_rows
                    ],
                    linked_incidents=[
                        LinkedIncidentSummary(
                            id=str(i.id), status=i.status, opened_at=i.opened_at.isoformat()
                        )
                        for i in incident_rows
                    ],
                )
            )

    return entries


# --- culprit_coupled_files --------------------------------------------------


class CoupledFilesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    file_path: str = Field(
        ..., min_length=1, description="Repo-relative file path, e.g. 'worker/app/db.py'"
    )


def _load_coupled_pairs() -> list[tuple[str, str]]:
    data = yaml.safe_load(COUPLED_FILES_YAML.read_text())
    return [tuple(pair) for pair in data.get("pairs", [])]


@mcp.tool(
    name="culprit_coupled_files",
    annotations=ToolAnnotations(
        title="Look up a file's declared coupled pair",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def culprit_coupled_files(params: CoupledFilesInput) -> list[str]:
    """The other side of any declared "must change together" pairing
    (Phase 22's scripts/coupled_files.yaml) that `file_path` appears in.

    IMPORTANT: an empty list means "no coupling is *declared* for this
    file," not "nothing is coupled to this file." Phase 22's registry is
    seeded with exactly one pair; most real couplings in this or any
    codebase using Culprit will not be declared yet. Do not treat an
    empty result as confirmation that a file is safe to change freely --
    it only reflects what has been explicitly registered, never a live
    analysis of actual code dependencies.
    """
    pairs = _load_coupled_pairs()
    result: list[str] = []
    for a, b in pairs:
        if a == params.file_path:
            result.append(b)
        elif b == params.file_path:
            result.append(a)
    return result


# --- culprit_architecture_decisions -----------------------------------------


class DecisionSummary(BaseModel):
    id: str
    title: str
    body: str
    created_at: str | None


class ArchitectureDecisionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str | None = Field(
        default=None,
        min_length=1,
        description="Optional natural-language search text. Omit to list the most recent "
        "decisions instead.",
    )
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of results to return")


@mcp.tool(
    name="culprit_architecture_decisions",
    annotations=ToolAnnotations(
        title="Search or list architecture decisions",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def culprit_architecture_decisions(
    params: ArchitectureDecisionsInput, ctx: Context
) -> list[DecisionSummary]:
    """Human-written architecture decisions (Phase 21) — either a plain
    recency-ordered list (when `query` is omitted, the common "what's
    been decided recently" call), or a similarity search scoped to
    decisions only (when `query` is present, equivalent to
    culprit_search_memory with record_types=["decision"]).

    Returns an empty list, not an error, when no decision has been
    recorded yet.
    """
    engine = ctx.request_context.lifespan_context.engine

    if params.query is None:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(
                        architecture_decisions.c.id,
                        architecture_decisions.c.title,
                        architecture_decisions.c.body,
                        architecture_decisions.c.created_at,
                    )
                    .order_by(architecture_decisions.c.created_at.desc())
                    .limit(params.limit)
                )
            ).all()
        return [
            DecisionSummary(
                id=str(row.id),
                title=row.title,
                body=row.body,
                created_at=row.created_at.isoformat() if row.created_at else None,
            )
            for row in rows
        ]

    query_embedding = await _embed_query(params.query)
    stmt = (
        _select_for("decision", query_embedding)
        .order_by(sa.literal_column("similarity").desc())
        .limit(params.limit)
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(stmt)).all()
    return [
        DecisionSummary(id=str(row.id), title=row.title, body=row.body, created_at=None)
        for row in rows
    ]
