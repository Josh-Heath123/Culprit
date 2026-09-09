"""Capture ingestion (Phase 28, docs/DIAGNOSTIC_PLAN.md field 9).

The one write path into the three-plane fact tables. `POST /facts/captures`
accepts a `CaptureBundle` — exactly what `culprit intent` prints — and
persists it as one `captures` row plus its `intent_facts`.

Authenticated with a project token, not a user JWT: the caller is a CI
job, which has no session to log in with. See `dependencies.py`.
"""
