"""The database URL for the divergence writer.

Reuses `FACT_WRITER_DATABASE_URL` rather than introducing a role of its
own. `.claude/rules/database.md` says to add a role rather than widen
one, and this is the second sanctioned exception in the repository's
history (Phase 21 was the first, extending `postmortem-writer` for
engineering memory).

The reasoning is the same both times. The rule exists so a leaked
credential cannot do more than the job it was issued for. Divergences
are produced by the same CI run, from the same repository, under the
same project token, as the facts they were derived from — the same job,
the same trust domain, the same blast radius. A second role would mean a
second password in every CI configuration, handed to the same process,
for the same purpose: friction with nothing gained, which is how
least-privilege stops being followed at all.

See `api/migrations/versions/b8e0c3d5f214_divergence_history.py`, which
grants INSERT, SELECT and UPDATE on `divergences` and nothing else.
"""

from app.facts.config import FACT_WRITER_DATABASE_URL

DIVERGENCE_WRITER_DATABASE_URL = FACT_WRITER_DATABASE_URL
