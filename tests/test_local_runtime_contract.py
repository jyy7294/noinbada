import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hourly_github_action_is_removed():
    assert not (ROOT / ".github" / "workflows" / "hourly-collection.yml").exists()


def test_legacy_windows_scheduler_and_x_extension_are_removed():
    assert not (ROOT / "scripts" / "install-hourly-task.ps1").exists()
    assert not (ROOT / "scripts" / "setup-x-chrome.ps1").exists()
    extension = ROOT / "chrome-extension" / "trzip-x-current-session"
    assert not (extension / "manifest.json").exists()
    assert not (extension / "service-worker.js").exists()


def test_x_paid_api_is_absent_from_runtime_code():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "trzip").glob("*.py")
    )
    assert "api.x.com" not in source
    assert "X_BEARER_TOKEN" not in source


def test_codex_automation_runs_full_local_publication_pipeline():
    runner = (ROOT / "scripts" / "collect-hourly.ps1").read_text(encoding="utf-8")
    setup = (ROOT / "scripts" / "setup-local-runtime.ps1").read_text(encoding="utf-8")
    assert "trzip.local_pipeline" in runner
    assert "validate_frontend_delivery" in runner
    assert "frontend delivery manifest validation failed" in runner
    assert "live-data" in runner
    assert "Global\\TRZIP-NOINBADA-HOURLY-V1" in runner
    assert "Get-RelativeChildPath" in runner
    assert "[IO.Path]::GetRelativePath" not in runner
    assert "+refs/heads/live-data:refs/remotes/origin/live-data" in runner
    assert 'push origin "HEAD:refs/heads/live-data"' in runner
    assert "ls-remote origin refs/heads/live-data" in runner
    assert "remote_verified=true" in runner
    assert "scripts\\audit-runtime.py" in runner
    assert "runtime quality audit failed; publication was not pushed" in runner
    assert 'Write-RunLog -Phase "audit"' in runner
    assert "Register-ScheduledTask" not in setup
    assert "Disable-ScheduledTask" in setup
    assert "+refs/heads/live-data:refs/remotes/origin/live-data" in setup


def test_verified_code_checkpoint_is_explicit_and_non_force():
    checkpoint = (ROOT / "scripts" / "checkpoint-main.ps1").read_text(encoding="utf-8")
    promotion = (ROOT / "scripts" / "promote-runtime.ps1").read_text(encoding="utf-8")
    state_schema = json.loads(
        (ROOT / "schemas" / "current-state-v1.schema.json").read_text(encoding="utf-8")
    )

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
    assert ".codex\\automations\\trzip\\automation.toml" in promotion
    assert 'status\\s*=\\s*"ACTIVE"' in promotion
    assert "FREQ=HOURLY;INTERVAL=1;BYMINUTE=0" in promotion
    assert "codex_hourly_automation" in promotion
    assert "Get-ScheduledTask" not in promotion
    assert 'scheduler = "codex_hourly_automation"' in checkpoint
    assert (
        state_schema["properties"]["runtime_contract"]["properties"]["scheduler"]["const"]
        == "codex_hourly_automation"
    )
