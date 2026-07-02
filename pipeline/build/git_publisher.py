from __future__ import annotations
import subprocess
from pathlib import Path


def git_publish(skill_output: Path, today: str) -> str:
    """Stage, commit, and push updated skill files. Returns a status message."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=skill_output,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"skipped — {skill_output} is not inside a git repo"

    repo_root = Path(result.stdout.strip())

    subprocess.run(
        ["git", "add", ".claude/", "CLAUDE.md"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )

    diff = subprocess.run(
        ["git", "diff", "--staged", "--quiet"],
        cwd=repo_root,
    )
    if diff.returncode == 0:
        return "nothing to commit — skill files unchanged"

    subprocess.run(
        ["git", "commit", "-m", f"build: update skill files {today}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )

    push = subprocess.run(
        ["git", "push"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {push.stderr.strip()}")

    return f"committed and pushed (build: update skill files {today})"
