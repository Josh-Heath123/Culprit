def test_worker_settings_imports() -> None:
    from app.main import WorkerSettings
    from app.rag.embed_job import embed_postmortem
    from app.rag.job import generate_root_cause_narrative

    registered = [
        # Phase 18's embed_postmortem is wrapped in arq.func(...) for a
        # higher max_tries (see app/main.py) — unwrap it the same way
        # WorkerSettings itself does, rather than comparing the wrapper.
        fn.coroutine if hasattr(fn, "coroutine") else fn
        for fn in WorkerSettings.functions
    ]
    assert registered == [generate_root_cause_narrative, embed_postmortem]
