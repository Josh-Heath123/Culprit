"""Storing and reading investigations (Phase 32, part 2).

`POST /investigations` takes exactly what `culprit diagnose --format json`
writes, validated by `culprit_model.investigations.Investigation` — the
model the binary's own output is held to by the shared conformance fixture
— and stores it in one transaction. The database holds field 7's rule
underneath (migrations/versions/c4e8a1f2b3d5_investigations.py): a fault
edge with no citation, or citing a reading from another investigation,
cannot be committed however it is inserted.

**Redaction at the same choke point as a reading (standing invariant 11).**
Every reading is passed through `redact_reading` before it is stored — the
function `POST /readings` uses — and the free text an investigation adds
around its readings (hypothesis reasons, the diagnosis statement and
remediation, the symptom description) through `redact_credentials`. The
binary already redacts; this endpoint accepts investigations from outside
that guarantee, so it does not rely on it.

Core inserts with no RETURNING, as app/readings/service.py explains:
`investigation-writer` holds INSERT and nothing else.
"""

from datetime import UTC, datetime
from typing import Any

from culprit_model.investigations import Investigation
from culprit_model.readings import redact_reading
from culprit_model.redaction import redact_credentials
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.investigations import tables


class AlreadyStored(Exception):
    """An investigation with this id is already stored. A record, once
    stored, is not overwritten."""


class RejectedByDatabase(Exception):
    """A row the database refused, named by constraint and never by its
    content — Postgres renders the failing row into its error text, and a
    reading carries `measured` and `evidence`."""

    def __init__(self, exc: Exception) -> None:
        orig = getattr(exc, "orig", None)
        driver = getattr(orig, "__cause__", None) or orig
        self.constraint = str(getattr(driver, "constraint_name", "") or "")
        super().__init__(
            "the investigation was refused by the database"
            + (f" (constraint {self.constraint})" if self.constraint else "")
        )


def _redacted(text: str | None) -> str | None:
    return None if text is None else redact_credentials(text)


def _sanitised(investigation: Investigation) -> Investigation:
    """The investigation as it will be stored: every reading redacted, every
    piece of free text around them too."""
    readings = [
        item.model_copy(update={"reading": redact_reading(item.reading)})
        for item in investigation.readings
    ]
    hypotheses = [
        hypothesis.model_copy(update={"reason": _redacted(hypothesis.reason)})
        for hypothesis in investigation.hypotheses
    ]
    symptom = investigation.symptom
    symptom = symptom.model_copy(
        update={
            "description": _redacted(symptom.description),
            "source": redact_credentials(symptom.source),
            "attestation": symptom.attestation.model_copy(
                update={"reported_by": _redacted(symptom.attestation.reported_by)}
            ),
        }
    )
    diagnosis = investigation.diagnosis
    if diagnosis is not None:
        diagnosis = diagnosis.model_copy(
            update={
                "statement": redact_credentials(diagnosis.statement),
                "remediation": _redacted(diagnosis.remediation),
                # Each criterion's reason is free text too (invariant audit).
                "confidence": diagnosis.confidence.model_copy(
                    update={
                        name: criterion.model_copy(
                            update={"reason": redact_credentials(criterion.reason)}
                        )
                        for name, criterion in diagnosis.confidence
                    }
                ),
            }
        )
    # Rebuilt through the model, so the stored form passes the same rules.
    return Investigation.model_validate(
        investigation.model_copy(
            update={
                "readings": tuple(readings),
                "hypotheses": tuple(hypotheses),
                "symptom": symptom,
                "diagnosis": diagnosis,
            }
        ).model_dump(mode="json")
    )


async def store(session: AsyncSession, investigation: Investigation) -> Investigation:
    clean = _sanitised(investigation)
    diagnosis = clean.diagnosis
    try:
        await session.execute(
            insert(tables.investigations).values(
                id=clean.id,
                opened_at=clean.opened_at,
                closed_at=clean.closed_at,
                environment=clean.environment,
                symptom=clean.symptom.model_dump(mode="json"),
                root_subject=diagnosis.root_subject if diagnosis else None,
                complete=diagnosis.complete if diagnosis else None,
                diagnosis=diagnosis.model_dump(mode="json") if diagnosis else None,
                ingested_at=datetime.now(UTC),
            )
        )
        if clean.readings:
            await session.execute(
                insert(tables.investigation_readings),
                [
                    {
                        "investigation_id": clean.id,
                        "id": item.id,
                        "probe_id": item.reading.probe_id,
                        "target": item.reading.target,
                        "verdict": item.reading.verdict.value,
                        "reading": item.reading.model_dump(mode="json"),
                    }
                    for item in clean.readings
                ],
            )
        if clean.hypotheses:
            await session.execute(
                insert(tables.hypotheses),
                [
                    {
                        "investigation_id": clean.id,
                        "id": h.id,
                        "kind": h.kind,
                        "subject": h.subject,
                        "status": h.status.value,
                        "reason": h.reason,
                        "readings": list(h.readings),
                    }
                    for h in clean.hypotheses
                ],
            )
        if clean.fault_tree:
            await session.execute(
                insert(tables.fault_edges),
                [
                    {
                        "investigation_id": clean.id,
                        "id": index,
                        "from_subject": edge.from_subject,
                        "to_subject": edge.to_subject,
                        "relation": edge.relation.value,
                    }
                    for index, edge in enumerate(clean.fault_tree)
                ],
            )
            await session.execute(
                insert(tables.fault_edge_readings),
                [
                    {"investigation_id": clean.id, "edge_id": index, "reading_id": reading_id}
                    for index, edge in enumerate(clean.fault_tree)
                    for reading_id in edge.established_by
                ],
            )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        orig = getattr(exc, "orig", None)
        driver = getattr(orig, "__cause__", None) or orig
        if str(getattr(driver, "constraint_name", "")) == "investigations_pkey":
            raise AlreadyStored from exc
        raise RejectedByDatabase(exc) from exc
    return clean


async def list_investigations(
    session: AsyncSession, limit: int, offset: int
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(tables.investigations)
            .order_by(tables.investigations.c.opened_at.desc(), tables.investigations.c.id)
            .limit(limit)
            .offset(offset)
        )
    ).mappings()
    return [
        {
            "id": row["id"],
            "opened_at": row["opened_at"],
            "environment": row["environment"],
            "symptom_subject": row["symptom"]["subject"],
            "attestation": row["symptom"]["attestation"]["kind"],
            "root_subject": row["root_subject"],
            "complete": row["complete"],
        }
        for row in rows
    ]


async def load(session: AsyncSession, investigation_id: str) -> Investigation | None:
    """The investigation as stored, rebuilt through the model — so a read
    passes the same rules a write did."""
    row = (
        (
            await session.execute(
                select(tables.investigations).where(tables.investigations.c.id == investigation_id)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    where = {"investigation_id": investigation_id}

    def scoped(table):
        return select(table).filter_by(**where)

    readings = (
        await session.execute(scoped(tables.investigation_readings).order_by("id"))
    ).mappings()
    hypotheses = (await session.execute(scoped(tables.hypotheses))).mappings()
    edges = (await session.execute(scoped(tables.fault_edges).order_by("id"))).mappings()
    links = (await session.execute(scoped(tables.fault_edge_readings))).mappings()

    cited: dict[int, list[str]] = {}
    for link in links:
        cited.setdefault(link["edge_id"], []).append(link["reading_id"])

    def numbered(identifier: str) -> tuple[int, str]:
        digits = "".join(ch for ch in identifier if ch.isdigit())
        return (int(digits) if digits else 0, identifier)

    reading_rows = sorted(readings, key=lambda r: numbered(r["id"]))
    hypothesis_rows = sorted(hypotheses, key=lambda h: numbered(h["id"]))
    return Investigation.model_validate(
        {
            "id": row["id"],
            "opened_at": row["opened_at"],
            "closed_at": row["closed_at"],
            "environment": row["environment"],
            "symptom": row["symptom"],
            "hypotheses": [
                {
                    "id": h["id"],
                    "kind": h["kind"],
                    "subject": h["subject"],
                    "status": h["status"],
                    "reason": h["reason"],
                    "readings": list(h["readings"]),
                }
                for h in hypothesis_rows
            ],
            "readings": [{"id": r["id"], "reading": r["reading"]} for r in reading_rows],
            "fault_tree": [
                {
                    "from_subject": e["from_subject"],
                    "to_subject": e["to_subject"],
                    "relation": e["relation"],
                    "established_by": sorted(cited.get(e["id"], []), key=numbered),
                }
                for e in edges
            ],
            "diagnosis": row["diagnosis"],
        }
    )


def tree(investigation: Investigation) -> dict[str, Any]:
    """The view's shape: every edge carries the readings that established
    it, the rubric stays four booleans, and hypotheses are grouped so that
    untested (open) and unexplored are never shown as one thing."""
    by_id = {item.id: item.reading for item in investigation.readings}
    groups: dict[str, list[dict[str, Any]]] = {
        "supported": [],
        "ruled_out": [],
        "unexplored": [],
        "untested": [],
    }
    for hypothesis in investigation.hypotheses:
        key = "untested" if hypothesis.status.value == "open" else hypothesis.status.value
        groups[key].append(hypothesis.model_dump(mode="json"))
    return {
        "id": investigation.id,
        "environment": investigation.environment,
        "opened_at": investigation.opened_at,
        "symptom": investigation.symptom.model_dump(mode="json"),
        "diagnosis": (
            investigation.diagnosis.model_dump(mode="json") if investigation.diagnosis else None
        ),
        "fault_tree": [
            {
                **edge.model_dump(mode="json"),
                "readings": [
                    {"id": reading_id, "reading": by_id[reading_id].model_dump(mode="json")}
                    for reading_id in edge.established_by
                ],
            }
            for edge in investigation.fault_tree
        ],
        "hypotheses": groups,
    }
