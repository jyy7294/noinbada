from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hourly_github_action_is_removed():
    assert not (ROOT / ".github" / "workflows" / "hourly-collection.yml").exists()


def test_x_paid_api_is_absent_from_runtime_code():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "trzip").glob("*.py")
    )
    assert "api.x.com" not in source
    assert "X_BEARER_TOKEN" not in source


def test_windows_task_runs_full_local_publication_pipeline():
    runner = (ROOT / "scripts" / "collect-hourly.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "scripts" / "install-hourly-task.ps1").read_text(encoding="utf-8")
    assert "trzip.local_pipeline" in runner
    assert "live-data" in runner
    assert "Global\\TRZIP-NOINBADA-HOURLY-V1" in runner
    assert "New-TimeSpan -Hours 1" in installer
    assert "-WorkingDirectory $ProjectRoot" in installer
    assert "+refs/heads/live-data:refs/remotes/origin/live-data" in installer
