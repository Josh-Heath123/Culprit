"""`culprit-extract-python` — the Python intent extractor (D3).

Installed as a dev-dependency in the *target* project's own virtualenv,
not in Culprit's. That is the whole design: introspecting a FastAPI app
means importing it, which means having its dependencies importable, and
no external process can do that correctly. So this runs inside the
project, is handed a JSON request on stdin, and writes a JSON response
on stdout (`docs/EXTRACTOR_PROTOCOL.md`).

**What it will not do.** It never fails the run. Every source it cannot
read becomes a `skipped` entry with a reason and the process exits zero,
because a missing answer must degrade a report rather than break it —
and because "I could not import your app, here is the ImportError" is a
more useful line in a CI log than a stack trace.

It also never emits a config *value*. `culprit_model.ValueShape` is a
closed four-field type with nowhere to put one, and `Fact` refuses to be
constructed carrying an ungranted literal. Both guarantees are enforced
by the model, not by this package remembering to behave.

The sources, in the preference order `.claude/rules/model.md` fixes:

1. Runtime introspection (rank 90) — `app.openapi()`, Flask's
   `url_map`, Django's URL resolver, SQLAlchemy's `MetaData`, Alembic's
   `ScriptDirectory`. Dynamic route registration defeats static parsing
   in every one of those frameworks, which is why importing is worth the
   trouble.
2. Static extraction (ranks 60/50) — `os.environ` read sites and test
   status-code assertions, via the `ast` module. Used only for what
   introspection cannot give.
"""

__version__ = "0.1.0"

#: What every Fact's provenance records as its source. `name@version`,
#: so a wrong fact is traceable to the exact build that produced it.
EXTRACTOR_ID = f"culprit-extract-python@{__version__}"
