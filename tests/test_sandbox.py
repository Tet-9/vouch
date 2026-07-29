from __future__ import annotations

import os
from pathlib import Path

import pytest

from vouch import auto_pr as ap
from vouch import sandbox


class FakeRunner:
    def __init__(self, result: ap.RunResult | None = None):
        self.result = result or ap.RunResult(0, "", "")
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, cwd: str | None = None,
            stdin: str | None = None, timeout: int | None = None) -> ap.RunResult:
        self.calls.append(argv)
        return self.result


def test_docker_agent_runner_passes_non_agent_commands_through(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    fr = FakeRunner()
    runner = sandbox.DockerAgentRunner(repo_root=repo, runner=fr, host_home=tmp_path)
    try:
        runner.run(["git", "status"], cwd=str(repo))
    finally:
        runner.close()

    assert fr.calls == [["git", "status"]]


def test_docker_agent_runner_wraps_agent_with_worktree_and_home_mounts(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    worktree = tmp_path / "worktree"
    home = tmp_path / "home"
    cred = home / ".codex" / "auth.json"
    git_dir.mkdir(parents=True)
    worktree.mkdir()
    cred.parent.mkdir(parents=True)
    cred.write_text('{"OPENAI_API_KEY":"sk-test"}')

    fr = FakeRunner()
    runner = sandbox.DockerAgentRunner(
        repo_root=repo, runner=fr, image="agent-img", host_home=home)
    try:
        runner.run(["codex", "exec", "fix"], cwd=str(worktree))
        argv = fr.calls[0]
        assert argv[:3] == ["docker", "run", "--rm"]
        assert "--entrypoint" in argv and "" in argv
        # match sandbox._docker_argv: both must be callable, not merely present.
        uid_ok = callable(getattr(os, "getuid", None))
        gid_ok = callable(getattr(os, "getgid", None))
        if uid_ok and gid_ok:
            assert "--user" in argv
            assert f"{os.getuid()}:{os.getgid()}" in argv
        else:
            assert "--user" not in argv
        assert "-w" in argv and str(worktree.resolve()) in argv
        assert "-e" in argv
        assert f"HOME={sandbox.CONTAINER_HOME}" in argv
        assert "-v" in argv
        assert f"{worktree.resolve()}:{worktree.resolve()}" in argv
        assert f"{git_dir.resolve()}:{git_dir.resolve()}" in argv
        assert f"{runner.sandbox_home}:{sandbox.CONTAINER_HOME}" in argv
        assert (runner.sandbox_home / ".codex" / "auth.json").read_text() == (
            '{"OPENAI_API_KEY":"sk-test"}'
        )
        assert "agent-img" in argv
        assert argv[-3:] == ["codex", "exec", "fix"]
    finally:
        runner.close()


@pytest.mark.parametrize(
    "break_uid,break_gid",
    [
        pytest.param(True, False, id="getuid-missing"),
        pytest.param(False, True, id="getgid-missing"),
        pytest.param(True, True, id="both-missing"),
        pytest.param("noncallable", False, id="getuid-noncallable"),
        pytest.param(False, "noncallable", id="getgid-noncallable"),
    ],
)
def test_docker_argv_omits_user_when_uid_gid_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    break_uid: bool | str,
    break_gid: bool | str,
) -> None:
    """Regression for #582: omit --user unless both getuid and getgid are callable."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def _break(attr: str, how: bool | str) -> None:
        if how is False:
            return
        if how == "noncallable":
            monkeypatch.setattr(sandbox.os, attr, object(), raising=False)
        else:
            monkeypatch.delattr(sandbox.os, attr, raising=False)

    _break("getuid", break_uid)
    _break("getgid", break_gid)

    fr = FakeRunner()
    runner = sandbox.DockerAgentRunner(
        repo_root=repo, runner=fr, image="agent-img", host_home=tmp_path,
    )
    try:
        runner.run(["claude", "-p", "hi"], cwd=str(repo))
        argv = fr.calls[0]
        assert argv[:3] == ["docker", "run", "--rm"]
        assert "--user" not in argv
        assert "agent-img" in argv
    finally:
        runner.close()


def test_require_docker_sandbox_reports_missing_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    fr = FakeRunner(ap.RunResult(1, "", "no such image"))

    with pytest.raises(RuntimeError, match="sandbox image"):
        sandbox.require_docker_sandbox("missing:latest", runner=fr)

    assert fr.calls == [["docker", "image", "inspect", "missing:latest"]]


def test_require_docker_sandbox_reports_missing_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="docker on PATH"):
        sandbox.require_docker_sandbox("agent-img", runner=FakeRunner())
