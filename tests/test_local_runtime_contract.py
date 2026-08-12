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
    assert "Get-RelativeChildPath" in runner
    assert "[IO.Path]::GetRelativePath" not in runner
    assert "+refs/heads/live-data:refs/remotes/origin/live-data" in runner
    assert 'push origin "HEAD:refs/heads/live-data"' in runner
    assert "ls-remote origin refs/heads/live-data" in runner
    assert "remote_verified=true" in runner
    assert "New-TimeSpan -Hours 1" in installer
    assert "-WorkingDirectory $ProjectRoot" in installer
    assert "+refs/heads/live-data:refs/remotes/origin/live-data" in installer


def test_verified_code_checkpoint_is_explicit_and_non_force():
    checkpoint = (ROOT / "scripts" / "checkpoint-main.ps1").read_text(encoding="utf-8")
    promotion = (ROOT / "scripts" / "promote-runtime.ps1").read_text(encoding="utf-8")

    assert "IncludePath" in checkpoint
    assert "pytest -q" in checkpoint
    assert "diff --cached --check" in checkpoint
    assert "+refs/heads/main:refs/remotes/origin/main" in checkpoint
    assert 'push origin "HEAD:refs/heads/main"' in checkpoint
    assert "ls-remote origin refs/heads/main" in checkpoint
    assert "push --force" not in checkpoint
    assert "--force-with-lease" not in checkpoint
    assert "reset --hard" not in checkpoint
    assert "merge --ff-only origin/main" in promotion
    assert "TRZIP X Google Hourly Collector" in promotion
