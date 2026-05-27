"""
Tests for the pre-commit secret-scan hook (Phase 5 / task 12.5).

Validates:
- Real-looking key in a staged .env* file -> hook rejects (exit 1)
- REPLACE_WITH_* placeholder in a staged .env* file -> hook accepts (exit 0)

Notes:
- These tests run the hook script in an *isolated* git repo created in a tempdir
  so we don't pollute the real repo's commit history.
- The hook is a POSIX sh script. On Windows it's invoked through `bash` which is
  shipped with Git for Windows. We skip if `bash` is not on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = REPO_ROOT / "scripts" / "hooks" / "pre-commit"

# `bash` is provided by Git for Windows. If unavailable we skip rather than fail.
BASH = shutil.which("bash") or next(
    (
        p
        for p in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            "/bin/bash",
            "/usr/bin/bash",
        )
        if os.path.exists(p)
    ),
    None,
)


def _make_repo(tmp_path: Path, hook_dst: Path) -> None:
    """Create a throwaway git repo with the hook installed."""
    subprocess.check_call(["git", "init", "-q"], cwd=tmp_path)
    # Some defaults to keep `git commit` happy.
    subprocess.check_call(["git", "config", "user.email", "t@t.t"], cwd=tmp_path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=tmp_path)
    hook_dst.parent.mkdir(parents=True, exist_ok=True)
    hook_dst.write_text(HOOK_PATH.read_text(), newline="\n")
    hook_dst.chmod(0o755)


def _run_hook(repo: Path) -> subprocess.CompletedProcess:
    """Invoke the staged-files hook from inside `repo`."""
    return subprocess.run(
        [BASH, ".git/hooks/pre-commit"],
        cwd=repo,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not BASH, reason="bash not on PATH (need Git for Windows)")
@pytest.mark.skipif(not HOOK_PATH.exists(), reason="pre-commit hook missing")
def test_hook_rejects_real_looking_key(tmp_path):
    """A staged real-looking sk- token MUST cause the hook to exit 1."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_repo(repo, repo / ".git" / "hooks" / "pre-commit")

    env_file = repo / ".env.example"
    # Construct the suspicious value at runtime so this test file itself
    # doesn't trip the pre-commit hook (which scans staged content for
    # the same regex). Using a real-looking token literal here would
    # block this very file from being committed.
    fake_token = "sk-" + "fake" * 6 + "FAKE"
    env_file.write_text(f"LLM_API_KEY={fake_token}\n")
    subprocess.check_call(["git", "add", ".env.example"], cwd=repo)

    result = _run_hook(repo)
    assert result.returncode == 1, (
        f"hook should have rejected real-looking key but exited "
        f"{result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "secret" in (result.stdout + result.stderr).lower()


@pytest.mark.skipif(not BASH, reason="bash not on PATH (need Git for Windows)")
@pytest.mark.skipif(not HOOK_PATH.exists(), reason="pre-commit hook missing")
def test_hook_allows_placeholder(tmp_path):
    """A staged REPLACE_WITH_* placeholder MUST pass the hook (exit 0)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_repo(repo, repo / ".git" / "hooks" / "pre-commit")

    env_file = repo / ".env.example"
    env_file.write_text("LLM_API_KEY=sk-REPLACE_WITH_YOUR_GATEWAY_TOKEN\n")
    subprocess.check_call(["git", "add", ".env.example"], cwd=repo)

    result = _run_hook(repo)
    assert result.returncode == 0, (
        f"hook should have allowed placeholder but exited "
        f"{result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
