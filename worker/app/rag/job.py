"""arq job: generate_root_cause_narrative — Phase 6, RAG + root-cause.

Event-driven, not a cron job (unlike Phases 4/5's scheduled jobs): this
is enqueued exactly once, directly, by app/correlation/job.py the moment
it creates a NEW incident_candidate — never on every correlation tick,
and never when an existing incident is merely extended with more
anomalies (see app/correlation/job.py::correlate_recent_anomalies).

This module only explains an incident Phase 5 has already decided is
real; it never scores anomalies or decides what's correlated. No imports
from app.anomaly or app.correlation — enforced both directions by the
import-linter contracts in pyproject.toml, per CLAUDE.md's module-
isolation rule.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import incident_candidates
from app.observability import instrument_job
from app.rag.context import build_incident_context, render_embedding_text
from app.rag.embeddings import embed_query
from app.rag.llm import CitedEvidence, generate_root_cause_analysis
from app.rag.retrieval import RetrievedPostmortem, retrieve_similar_postmortems

logger = logging.getLogger("rag")

#: How much of a dropped passage gets logged — enough to recognise which
#: citation was rejected without reprinting a whole postmortem into the
#: worker's log on every rejection.
_LOGGED_PASSAGE_LENGTH = 120


def _normalised(text: str) -> str:
    """Collapses whitespace so a citation is not rejected purely because
    the model re-wrapped a line it quoted correctly.

    This is the only latitude given. Everything else — different words,
    a paraphrase, a plausible-sounding sentence that appears in no
    postmortem at all — fails the check, which is the point.
    """
    return " ".join(text.split())


def _verified_evidence(
    cited_evidence: list[CitedEvidence], retrieved: list[RetrievedPostmortem]
) -> tuple[list[dict], int]:
    """Keeps only citations whose passage really appears in the
    postmortem they are attributed to (Phase 26, docs/DIAGNOSTIC_PLAN.md).

    A citation is the one part of the root-cause narrative that claims to
    be quoted rather than reasoned, and it is the part a reader trusts
    most: "this happened before, here is the line from that postmortem"
    reads as checkable in a way the surrounding hypothesis does not. So
    it has to actually be checkable. Nothing before this verified it —
    a model that invented a quotation, or attributed a real one to the
    wrong postmortem, produced evidence indistinguishable from the real
    thing.

    Two ways a citation fails, both dropped:

    - it names a postmortem that was not retrieved (previously stored
      with a NULL `postmortem_id` and shown to the user anyway), or
    - its passage is not a substring of that postmortem's body.

    Dropping rather than repairing is deliberate. There is no correct
    passage to substitute, and a narrative with fewer citations is
    honest; one with a fabricated citation is not.
    """
    evidence: list[dict] = []
    dropped = 0

    for item in cited_evidence:
        # Every postmortem with this title, not the last one to claim it:
        # `postmortems.title` has no unique constraint and the write path
        # is a free-text field, so two retrieved rows can share one. A
        # dict keyed on title would keep only the last, and a passage
        # genuinely quoted from the other would then be dropped as
        # fabricated -- a false negative in the one mechanism whose job
        # is telling real citations from invented ones.
        candidates = [p for p in retrieved if p.title == item.postmortem_title]
        if not candidates:
            dropped += 1
            logger.warning(
                "dropping citation: no retrieved postmortem titled %r", item.postmortem_title
            )
            continue

        passage = _normalised(item.passage)
        matched = next((p for p in candidates if passage in _normalised(p.body)), None)
        if matched is None:
            dropped += 1
            logger.warning(
                "dropping citation: passage not found in postmortem %r (%s...)",
                item.postmortem_title,
                item.passage[:_LOGGED_PASSAGE_LENGTH],
            )
            continue
        evidence.append(
            {
                "postmortem_id": str(matched.id),
                "postmortem_title": item.postmortem_title,
                "passage": item.passage,
            }
        )

    return evidence, dropped


@instrument_job("generate_root_cause_narrative")
async def generate_root_cause_narrative(ctx: dict, incident_id: str) -> dict:
    engine: AsyncEngine = ctx["rag_engine"]
    incident_uuid = UUID(incident_id)

    async with engine.connect() as conn:
        context = await build_incident_context(conn, incident_uuid)
        if context is None:
            logger.warning("incident %s vanished before root-cause generation ran", incident_id)
            return {"status": "skipped", "reason": "incident_not_found"}

        query_embedding = await embed_query(render_embedding_text(context))
        retrieved = await retrieve_similar_postmortems(conn, query_embedding)

    anomaly_lines = [
        f"{summary.metric_name} on {summary.service_name}: z-score {summary.score:.2f} "
        f"at {summary.detected_at.isoformat()}"
        for summary in context.anomaly_summaries
    ]

    analysis = await generate_root_cause_analysis(
        services=context.services,
        anomaly_lines=anomaly_lines,
        log_messages=context.log_messages,
        retrieved=retrieved,
    )

    evidence, dropped_citations = _verified_evidence(analysis.cited_evidence, retrieved)

    async with engine.begin() as conn:
        await conn.execute(
            update(incident_candidates)
            .where(incident_candidates.c.id == incident_uuid)
            .values(
                root_cause_hypothesis=analysis.hypothesis,
                root_cause_confidence=analysis.confidence,
                root_cause_confidence_reason=analysis.confidence_reason,
                root_cause_evidence=evidence,
                root_cause_generated_at=datetime.now(UTC),
            )
        )

    logger.info(
        "generated root-cause narrative for incident %s: confidence=%s, %d citation(s) "
        "(%d dropped as unverifiable), %d retrieved postmortem(s)",
        incident_id,
        analysis.confidence,
        len(evidence),
        dropped_citations,
        len(retrieved),
    )
    return {
        "status": "generated",
        "incident_id": incident_id,
        "confidence": analysis.confidence,
        "dropped_citations": dropped_citations,
        "retrieved_postmortem_ids": [str(p.id) for p in retrieved],
    }
