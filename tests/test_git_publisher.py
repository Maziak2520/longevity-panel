import subprocess
from pathlib import Path
import pytest
from pipeline.build.git_publisher import git_publish


def _init_repo(path: Path) -> None:
    """Create a minimal git repo with an initial commit."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_git_publish_commits_changes(tmp_path):
    repo = tmp_path / "health-panel"
    repo.mkdir()
    _init_repo(repo)

    # Simulate the skill output directory structure
    skill_dir = repo / ".claude" / "skills" / "health-panel"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: health-panel\n---\ncontent")
    (repo / "CLAUDE.md").write_text("docs")

    # Add a remote pointing to a local bare repo so push works
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=bare, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)

    status = git_publish(skill_dir, "2026-07-02")

    assert "committed and pushed" in status
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True)
    assert "build: update skill files 2026-07-02" in log.stdout


def test_git_publish_no_changes(tmp_path):
    repo = tmp_path / "health-panel"
    repo.mkdir()
    _init_repo(repo)

    skill_dir = repo / ".claude" / "skills" / "health-panel"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("content")
    (repo / "CLAUDE.md").write_text("docs")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add skill"], cwd=repo, check=True, capture_output=True)

    # No changes since last commit
    status = git_publish(skill_dir, "2026-07-02")

    assert "nothing to commit" in status


def test_git_publish_not_a_repo(tmp_path):
    skill_dir = tmp_path / ".claude" / "skills" / "health-panel"
    skill_dir.mkdir(parents=True)

    status = git_publish(skill_dir, "2026-07-02")

    assert "not inside a git repo" in status


def test_git_publish_push_failure_raises(tmp_path):
    repo = tmp_path / "health-panel"
    repo.mkdir()
    _init_repo(repo)

    skill_dir = repo / ".claude" / "skills" / "health-panel"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("content")
    (repo / "CLAUDE.md").write_text("docs")
    # No remote configured — push will fail

    with pytest.raises(RuntimeError, match="git push failed"):
        git_publish(skill_dir, "2026-07-02")
