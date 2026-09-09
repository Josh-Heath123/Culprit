"""Phase 26: a cited passage must really appear in the postmortem cited.

The defect: `worker/app/rag/job.py` stored whatever `cited_evidence` the
model returned, with `postmortem_id` left NULL when the title matched
nothing retrieved. A fabricated quotation, or a real one attributed to
the wrong postmortem, reached the dashboard looking exactly like a
verified one — and a citation is precisely the part of the narrative a
reader treats as checkable rather than as a hypothesis.
"""

from uuid import uuid4

from app.rag.job import _verified_evidence
from app.rag.llm import CitedEvidence
from app.rag.retrieval import RetrievedPostmortem

BODY = (
    "Inventory service latency spiked after a connection-pool exhaustion.\n"
    "The pool was sized at 5 while the deploy doubled request concurrency."
)


def _postmortem(title: str = "Inventory pool exhaustion") -> RetrievedPostmortem:
    return RetrievedPostmortem(id=uuid4(), title=title, body=BODY, similarity=0.9)


def test_a_real_passage_is_kept_with_its_postmortem_id() -> None:
    postmortem = _postmortem()
    evidence, dropped = _verified_evidence(
        [CitedEvidence(postmortem_title=postmortem.title, passage="connection-pool exhaustion")],
        [postmortem],
    )

    assert dropped == 0
    assert evidence == [
        {
            "postmortem_id": str(postmortem.id),
            "postmortem_title": postmortem.title,
            "passage": "connection-pool exhaustion",
        }
    ]


def test_a_fabricated_passage_is_dropped() -> None:
    postmortem = _postmortem()
    evidence, dropped = _verified_evidence(
        [
            CitedEvidence(
                postmortem_title=postmortem.title,
                passage="the payments provider returned 503s for eleven minutes",
            )
        ],
        [postmortem],
    )

    assert evidence == []
    assert dropped == 1


def test_a_passage_attributed_to_an_unretrieved_postmortem_is_dropped() -> None:
    """This used to be stored with postmortem_id=None and shown anyway."""
    evidence, dropped = _verified_evidence(
        [CitedEvidence(postmortem_title="A postmortem nobody retrieved", passage="anything")],
        [_postmortem()],
    )

    assert evidence == []
    assert dropped == 1


def test_a_real_passage_attributed_to_the_wrong_postmortem_is_dropped() -> None:
    right = _postmortem("Inventory pool exhaustion")
    wrong = RetrievedPostmortem(
        id=uuid4(),
        title="Payments timeout",
        body="Unrelated: the payments provider was slow.",
        similarity=0.8,
    )

    evidence, dropped = _verified_evidence(
        [CitedEvidence(postmortem_title=wrong.title, passage="connection-pool exhaustion")],
        [right, wrong],
    )

    assert evidence == []
    assert dropped == 1


def test_rewrapped_whitespace_does_not_reject_a_genuine_quotation() -> None:
    """The one latitude given: the model may re-wrap a line it quoted
    correctly, and rejecting that would drop real evidence."""
    postmortem = _postmortem()
    evidence, dropped = _verified_evidence(
        [
            CitedEvidence(
                postmortem_title=postmortem.title,
                passage="exhaustion.   The pool\nwas sized at 5",
            )
        ],
        [postmortem],
    )

    assert dropped == 0
    assert len(evidence) == 1


def test_verified_and_fabricated_citations_in_one_response() -> None:
    postmortem = _postmortem()
    evidence, dropped = _verified_evidence(
        [
            CitedEvidence(postmortem_title=postmortem.title, passage="The pool was sized at 5"),
            CitedEvidence(postmortem_title=postmortem.title, passage="an invented sentence"),
        ],
        [postmortem],
    )

    assert dropped == 1
    assert [item["passage"] for item in evidence] == ["The pool was sized at 5"]
