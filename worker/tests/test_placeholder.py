def test_worker_settings_imports() -> None:
    from app.main import WorkerSettings
    from app.rag.job import generate_root_cause_narrative

    assert WorkerSettings.functions == [generate_root_cause_narrative]
