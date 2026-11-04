def test_worker_settings_imports() -> None:
    from app.main import WorkerSettings
    from app.rag.embed_job import (
        embed_ai_change_record,
        embed_architecture_decision,
        embed_postmortem,
    )

    registered = [
        # Phase 18's embed_postmortem (and Phase 21's two siblings) are
        # wrapped in arq.func(...) for a higher max_tries (see
        # app/main.py) — unwrap it the same way WorkerSettings itself
        # does, rather than comparing the wrapper.
        fn.coroutine if hasattr(fn, "coroutine") else fn
        for fn in WorkerSettings.functions
    ]
    assert registered == [
        embed_postmortem,
        embed_architecture_decision,
        embed_ai_change_record,
    ]


def test_every_engine_a_job_reads_is_one_startup_creates() -> None:
    """A job that reads `ctx["x"]` from a key startup() no longer sets fails
    with KeyError on its first run, in production, and no unit test sees it
    because each builds its own ctx. Phase 32 part 2 nearly shipped exactly
    that: removing the correlation engine took the engines that the
    change-link job and the postmortem embed job still run on."""
    import re
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "app"
    key = re.compile(r'ctx\["([a-z_]+)"\]')
    startup = (app / "main.py").read_text(encoding="utf-8")
    created = set(re.findall(r'ctx\["([a-z_]+)"\]\s*=', startup))
    read: dict[str, set[str]] = {}
    for path in app.rglob("*.py"):
        if path.name == "main.py":
            continue
        for name in key.findall(path.read_text(encoding="utf-8")):
            read.setdefault(name, set()).add(str(path.relative_to(app)))
    # arq's own keys, set by the worker rather than by startup().
    missing = {k: v for k, v in read.items() if k not in created and k not in {"job_try", "redis"}}
    assert missing == {}, f"jobs read ctx keys startup() never sets: {missing}"
