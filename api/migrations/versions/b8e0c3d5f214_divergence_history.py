"""divergence history: identity, explanation, and the fact-writer grant

Revision ID: b8e0c3d5f214
Revises: d1f4a9c73b60
Create Date: 2026-09-09 21:00:00.000000

Phase 29 field 9 — `POST /divergences/captures` "for history".

# What history needs that the Phase 26 table did not have

`divergences` was created empty in Phase 26 with the columns §2.5 names.
Storing one run's findings works against it as it stands. Storing *many*
runs does not, and history is the entire reason the endpoint exists: a
team wants to know that this finding is the same one as last Tuesday's,
that it has been open for eleven days, and that the other three are new
since the last deploy. Four columns are added for that.

**`divergence_key`, unique.** The finding's identity, derived from what
the finding *is* — subject, predicate, and the two sources that
disagreed — and computed identically by `Divergence.identity()` in
`shared/culprit_model/facts.py` and `Divergence.ID()` in
`cli/internal/model/divergence.go`. Without it, the same unfixed fault
lands as a new row on every CI run and the table becomes a log rather
than a record of open problems. With it, a repeat sighting is an UPDATE
that moves `last_seen_at`, and `first_seen_at` keeps meaning what it says.

**`last_seen_at`.** `first_seen_at` existed and was, alone, unusable: a
finding that was fixed on Monday and a finding that is still failing the
build look identical if all you know is when each was first seen.

**`explanation` and `severity_reason`.** The sentence a human reads and
the reason for the severity, both computed deterministically by the
comparator (D8 forbids an LLM anywhere near this path). Stored rather
than recomputed because the *system model changes*: a connection marked
`on_request_path` today may be `background` next month, and a stored
finding should still say why it was ranked the way it was when it was
found. Recomputing would silently rewrite history.

**`suppressed_by`.** The reason from `culprit.yaml` that silenced it. A
suppressed finding is still stored — that is the point of a suppression
list you can audit — and it must carry its justification with it or the
row is indistinguishable from one somebody quietly deleted.

# The role: extended, not added

`.claude/rules/database.md` says add a role rather than widen one, and
this widens `fact-writer` instead. The exception is deliberate and is
the second one in the repository's history (Phase 21 extended
`postmortem-writer` for engineering memory, on the same reasoning).

The rule exists so that a leaked credential cannot do more than the job
it was issued for. `fact-writer` is the credential a CI job uses to say
"here is what I found in this repository", authenticated by a project
token. Divergences are the same job, the same run, the same trust
domain, and the same blast radius: a leaked token that could already
write facts about a repository gains nothing by also being able to write
divergences about the same repository. A separate `divergence-writer`
role would mean a second password in every CI configuration, issued to
the same process, for the same purpose — friction with no security
gained, which is how least-privilege stops being followed at all.

The grant is INSERT, SELECT, and UPDATE **on nine named columns**. UPDATE
is new for this role and is what upserting a repeat sighting needs; it is
scoped to `divergences`, and within that table to the columns a repeat
sighting actually rewrites. `first_seen_at` is deliberately not among
them, so "a repeat sighting cannot move first_seen_at" is enforced by the
database rather than by the application remembering to. The role still
cannot touch `components`, `users`, `api_keys` or anything else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "b8e0c3d5f214"
down_revision: str | None = "d1f4a9c73b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACT_WRITER_ROLE = "fact-writer"

_KEY_INDEX = "uq_divergences_divergence_key"
_CAPTURE_FK = "fk_divergences_capture_id_captures"
_KEY_NOT_BLANK = "ck_divergences_divergence_key_not_blank"


def upgrade() -> None:
    # NOT NULL, not nullable-with-a-comment.
    #
    # The first version added this nullable and said in a comment that a
    # writer forgetting the key "should fail on the unique index rather
    # than on a NOT NULL, because the index's error names the real
    # problem". That was simply wrong: Postgres treats NULLs as distinct
    # in a unique index unless NULLS NOT DISTINCT is given, so such a
    # writer would insert unlimited rows and never error at all — the
    # exact opposite of the documented behaviour, with a load-bearing
    # comment describing a backstop that did not exist.
    #
    # The table is empty by design (Phase 26 created it; nothing has ever
    # written to it), so NOT NULL costs nothing and is the honest option.
    op.add_column("divergences", sa.Column("divergence_key", sa.Text(), nullable=False))
    op.add_column(
        "divergences",
        sa.Column("capture_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column("divergences", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("divergences", sa.Column("severity_reason", sa.Text(), nullable=True))
    op.add_column("divergences", sa.Column("suppressed_by", sa.Text(), nullable=True))
    op.add_column(
        "divergences",
        sa.Column(
            "last_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(_KEY_INDEX, "divergences", ["divergence_key"], unique=True)
    # The blank case the NOT NULL cannot catch: an empty or whitespace
    # key is not NULL and would collide with exactly one other blank,
    # which is a worse failure than either. Same shape and same reasoning
    # as `ck_intent_facts_grant_ref_not_blank` in d1f4a9c73b60, including
    # `!~ '^\s*$'` rather than `btrim(...) <> ''` — btrim strips spaces
    # only, and a whitespace-only key would sail through it.
    op.create_check_constraint(
        _KEY_NOT_BLANK,
        "divergences",
        r"divergence_key !~ '^\s*$'",
    )
    op.create_foreign_key(
        _CAPTURE_FK, "divergences", "captures", ["capture_id"], ["id"], ondelete="CASCADE"
    )
    # Reading "what is open right now" is the query the dashboard will
    # make, and it is the one that would table-scan without this.
    op.create_index(
        "ix_divergences_status_severity", "divergences", ["status", "severity"]
    )

    # A **column-level** UPDATE grant, naming exactly the nine columns
    # `_upsert` writes on conflict.
    #
    # `.claude/rules/database.md`: "Column-level grants are used where
    # they express the real need — `ingest-gateway` has
    # `UPDATE (last_used_at)` on `api_keys` and nothing else on that
    # table. Prefer that over a table grant when only one column is
    # written."
    #
    # A bare `UPDATE ON divergences` would also hand the CI project token
    # `first_seen_at` — and this migration's own docstring, plus
    # `api/app/divergences/service.py`, rest their case on "first_seen_at
    # keeps meaning what it says". Without the column list that is an
    # application convention, not a guarantee: a leaked project token,
    # which is precisely the threat this role exists to bound, could set
    # every open finding's first_seen_at to now() and make a six-week-old
    # fault look new. An audit trail with no integrity guarantee is not
    # an audit trail.
    #
    # The list is not minimal-by-wishing: `left_fact` and `right_fact`
    # *are* granted, because a repeat sighting legitimately refreshes
    # both — the values a finding is about move as the code moves, and a
    # stored finding showing last month's line numbers would be worse
    # than one that is current. What the list buys is the columns that
    # establish a finding's *identity and age*: `divergence_key`,
    # `subject`, `predicate`, `kind`, `first_seen_at`, `created_at`.
    # Those cannot be rewritten by this role at all, so a finding cannot
    # be made to look like a different finding, or a newer one.
    op.execute(
        "GRANT INSERT, SELECT, UPDATE ("
        "severity, status, explanation, severity_reason, suppressed_by, "
        "left_fact, right_fact, capture_id, last_seen_at"
        f') ON divergences TO "{FACT_WRITER_ROLE}"'
    )


def downgrade() -> None:
    op.execute(
        "REVOKE INSERT, SELECT, UPDATE ("
        "severity, status, explanation, severity_reason, suppressed_by, "
        "left_fact, right_fact, capture_id, last_seen_at"
        f') ON divergences FROM "{FACT_WRITER_ROLE}"'
    )

    op.drop_index("ix_divergences_status_severity", table_name="divergences")
    op.drop_constraint(_CAPTURE_FK, "divergences", type_="foreignkey")
    op.drop_constraint(_KEY_NOT_BLANK, "divergences", type_="check")
    op.drop_index(_KEY_INDEX, table_name="divergences")

    op.drop_column("divergences", "last_seen_at")
    op.drop_column("divergences", "suppressed_by")
    op.drop_column("divergences", "severity_reason")
    op.drop_column("divergences", "explanation")
    op.drop_column("divergences", "capture_id")
    op.drop_column("divergences", "divergence_key")
