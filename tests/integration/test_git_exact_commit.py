"""
Integration test: a Git build checks out exactly one commit, with a real git.
Source: app/services/git_service (resolve_ref, clone_at_commit)

The repositories are served by `git http-backend` over smart HTTP (protocol v0,
as the helper in test_git_credentials_wire passes no GIT_PROTOCOL). Such a
server refuses a commit that no ref advertises unless the repository allows
it, which covers both paths of clone_at_commit: fetching the commit by id, and
falling back to the ref's tip when that is still the commit.
"""

import shutil
import subprocess

import pytest

from app.services import git_service

from .test_git_credentials_wire import _repo_server

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def _repo(root, *, allow_any_commit: bool) -> tuple[str, str, str, str]:
    """A bare repo "app.git" with three commits on main, an annotated tag v1 and a
    lightweight tag v1-light on the first. The second is advertised by no ref.
    Returns (first, second, third, v1's tag object)."""
    src = root / "src"
    _git("init", "-q", "-b", "main", str(src))
    (src / "main.py").write_text("print(1)\n")
    _git("-C", str(src), "add", ".")
    _git("-C", str(src), *_ID, "commit", "-q", "-m", "one")
    first = _git("-C", str(src), "rev-parse", "HEAD")
    _git("-C", str(src), *_ID, "tag", "-a", "v1", "-m", "release 1")
    _git("-C", str(src), "tag", "v1-light")
    tag_object = _git("-C", str(src), "rev-parse", "v1")
    (src / "main.py").write_text("print(2)\n")
    _git("-C", str(src), *_ID, "commit", "-q", "-am", "two")
    second = _git("-C", str(src), "rev-parse", "HEAD")
    (src / "main.py").write_text("print(3)\n")
    _git("-C", str(src), *_ID, "commit", "-q", "-am", "three")
    third = _git("-C", str(src), "rev-parse", "HEAD")
    bare = root / "app.git"
    _git("clone", "-q", "--bare", str(src), str(bare))
    if allow_any_commit:
        _git("-C", str(bare), "config", "uploadpack.allowAnySHA1InWant", "true")
    return first, second, third, tag_object


@pytest.fixture
def served(tmp_path, mocker):
    mocker.patch.object(git_service, "_current_allowed_hosts", return_value=["127.0.0.1"])
    servers = []

    def serve(allow_any_commit: bool):
        commits = _repo(tmp_path, allow_any_commit=allow_any_commit)
        srv = _repo_server(tmp_path, [])
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_port}/app.git", commits

    yield serve
    for srv in servers:
        srv.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tc_int_078_resolve_ref_names_the_commit_and_peels_annotated_tags(served):
    """TC-INT-078: a branch resolves to its tip; an annotated tag to the commit it tags
    (not the tag object); a lightweight tag to its commit; a missing ref is an error."""
    url, (first, _, third, tag_object) = served(allow_any_commit=False)

    assert await git_service.resolve_ref(url, "main", "branch", None) == third
    assert await git_service.resolve_ref(url, "v1", "tag", None) == first
    assert tag_object != first
    assert await git_service.resolve_ref(url, "v1-light", "tag", None) == first
    with pytest.raises(git_service.GitUrlError, match="Branch 'nope' was not found"):
        await git_service.resolve_ref(url, "nope", "branch", None)
    # A tag named like the branch's tail is not the branch: the match is exact.
    with pytest.raises(git_service.GitUrlError, match="Tag 'main' was not found"):
        await git_service.resolve_ref(url, "main", "tag", None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tc_int_079_an_older_commit_is_checked_out_by_id(served, tmp_path):
    """TC-INT-079: a server that serves commits by id gives exactly the commit asked
    for, even when the branch has moved past it; one commit, detached, no remote."""
    url, (_, second, _, _) = served(allow_any_commit=True)
    target = tmp_path / "ws" / "t1"

    anonymous = await git_service.clone_at_commit(url, "main", "branch", second, target, None)

    assert anonymous is False
    assert _git("-C", str(target), "rev-parse", "HEAD") == second
    assert (target / "main.py").read_text() == "print(2)\n"
    assert _git("-C", str(target), "rev-list", "--count", "HEAD") == "1"
    assert _git("-C", str(target), "remote") == ""


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tc_int_080_a_v0_server_serves_tips_and_names_a_moved_ref(served, tmp_path):
    """TC-INT-080: a server that serves only advertised commits still gives the branch
    tip and an annotated tag's commit; an older commit fails, saying where the branch
    points now, and leaves nothing behind."""
    url, (first, second, third, _) = served(allow_any_commit=False)

    await git_service.clone_at_commit(url, "main", "branch", third, tmp_path / "a", None)
    assert _git("-C", str(tmp_path / "a"), "rev-parse", "HEAD") == third

    await git_service.clone_at_commit(url, "v1", "tag", first, tmp_path / "b", None)
    assert _git("-C", str(tmp_path / "b"), "rev-parse", "HEAD") == first

    with pytest.raises(git_service.GitUrlError, match="now points at"):
        await git_service.clone_at_commit(url, "main", "branch", second, tmp_path / "c", None)
    assert not (tmp_path / "c").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tc_int_081_an_unknown_commit_fails_and_cleans_up(served, tmp_path):
    """TC-INT-081: a well-formed id that is not in the repository fails the clone and
    removes the partial checkout."""
    url, _ = served(allow_any_commit=True)
    target = tmp_path / "ws" / "t2"

    with pytest.raises(git_service.GitUrlError):
        await git_service.clone_at_commit(url, "main", "branch", "0" * 40, target, None)
    assert not target.exists()
