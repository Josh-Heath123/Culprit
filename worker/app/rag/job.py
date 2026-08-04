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
from app.rag.llm import generate_root_cause_analysis
from app.rag.retrieval import retrieve_similar_postmortems

logger = logging.getLogger("rag")


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

    postmortem_id_by_title = {postmortem.title: postmortem.id for postmortem in retrieved}
    evidence = []
    for item in analysis.cited_evidence:
        matched_id = postmortem_id_by_title.get(item.postmortem_title)
        evidence.append(
            {
                "postmortem_id": str(matched_id) if matched_id is not None else None,
                "postmortem_title": item.postmortem_title,
                "passage": item.passage,
            }
        )

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
        "generated root-cause narrative for incident %s: confidence=%s, %d citation(s), "
        "%d retrieved postmortem(s)",
        incident_id,
        analysis.confidence,
        len(evidence),
        len(retrieved),
    )
    return {
        "status": "generated",
        "incident_id": incident_id,
        "confidence": analysis.confidence,
        "retrieved_postmortem_ids": [str(p.id) for p in retrieved],
    }
