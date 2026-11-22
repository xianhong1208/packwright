"""
Unit tests for building one exact commit of a Git source.
Source: app/services/git_service (validate_commit_sha, resolve_ref, clone_at_commit),
        app/services/build_dispatcher (_prepare_git_workspace),
        app/schemas/task (TaskCreate.git_commit), app/services/task_manager (create_task)

A commit id reaches git as a positional argument, so its shape is checked before
any git runs; the branch or tag a build names is turned into a commit once, that
commit is recorded on the build, and the checkout is of that commit.
"""

import contextlib

import pytest
from pydantic import ValidationError

from app.schemas.task import BuildConfig, ProjectType, SourceType, TaskCreate
from app.services import build_dispatcher, git_service

SHA1 = "3f2a9c1d4b5e6f708192a3b4c5d6e7f809a1b2c3"
SHA256 = "a" * 64
URL = "https://git.example.com/group/app.git"

BAD_IDS = [
    "3f2a9c1",                       # abbreviated
    SHA1.upper(),                    # upper case
    SHA1 + "0",                      # 41
    "g" * 40,                        # not hex
    "--upload-pack=touch /tmp/x",    # an option
    "-" + SHA1[1:],
    "main",                          # a ref name
    "HEAD~1",
    SHA1 + "\n",
    SHA1 + " --force",
    "$(id)" + SHA1[5:],
    "",
]


@pytest.mark.unit
@pytest.mark.parametrize("sha", [SHA1, SHA256])
def test_tc_git_099_full_commit_ids_are_accepted(sha):
    """TC-GIT-099: validate_commit_sha — 40 and 64 lower-case hex pass."""
    git_service.validate_commit_sha(sha)


@pytest.mark.unit
@pytest.mark.parametrize("sha", BAD_IDS)
def test_tc_git_100_anything_else_is_refused(sha):
    """TC-GIT-100: validate_commit_sha — abbreviations, ref names, options and
    injection-shaped values are refused."""
    with pytest.raises(git_service.GitUrlError):
        git_service.validate_commit_sha(sha)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("sha", ["--upload-pack=touch /tmp/x", "main", SHA1 + "\n"])
async def test_tc_git_101_a_bad_commit_never_reaches_git(sha, tmp_path, mocker):
    """TC-GIT-101: clone_at_commit — a malformed commit is refused before any git runs
    and before the target directory is made."""
    mocker.patch.object(git_service, "_current_allowed_hosts", return_value=[])
    spawn = mocker.patch.object(git_service, "_spawn", mocker.AsyncMock())

    with pytest.raises(git_service.GitUrlError):
        await git_service.clone_at_commit(URL, "main", "branch", sha, tmp_path / "ws", None)
    spawn.assert_not_called()
    assert not (tmp_path / "ws").exists()


def _fake_git(mocker, responses):
    """Replace _run_git; each call pops (rc, stdout) in order and is recorded."""
    calls = []

    async def run(cmd, env, timeout, what, cwd=None):
        calls.append((cmd, env))
        rc, out = responses.pop(0)
        return rc, out.encode(), b"not our ref" if rc else b""

    mocker.patch.object(git_service, "_run_git", side_effect=run)
    return calls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_git_102_every_git_call_is_isolated_and_argv_only(tmp_path, mocker):
    """TC-GIT-102: clone_at_commit — init, fetch by id, checkout and rev-parse all run
    with the isolated git environment; the token travels only in it; the commit is
    the last argument of the fetch."""
    mocker.patch.object(git_service, "_current_allowed_hosts", return_value=[])
    calls = _fake_git(mocker, [(0, ""), (0, ""), (0, ""), (0, SHA1 + "\n")])

    await git_service.clone_at_commit(URL, "main", "branch", SHA1, tmp_path / "ws", "TOKEN-123")

    fetch = next(cmd for cmd, _ in calls if "fetch" in cmd)
    assert fetch[-2:] == [URL, SHA1] and "--depth" in fetch
    for cmd, env in calls:
        assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_TERMINAL_PROMPT"] == "0"
        assert all("TOKEN-123" not in part for part in cmd)
        # The credential header goes to the fetch only; local steps get none.
        has_header = any(v.endswith(".extraHeader") for k, v in env.items() if k.startswith("GIT_CONFIG_KEY_"))
        assert has_header == ("fetch" in cmd)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_git_103_head_must_be_the_commit(tmp_path, mocker):
    """TC-GIT-103: clone_at_commit — a checkout whose HEAD is another commit fails and
    is removed."""
    mocker.patch.object(git_service, "_current_allowed_hosts", return_value=[])
    _fake_git(mocker, [(0, ""), (0, ""), (0, ""), (0, "b" * 40 + "\n")])

    with pytest.raises(git_service.GitUrlError, match="instead of"):
        await git_service.clone_at_commit(URL, "main", "branch", SHA1, tmp_path / "ws", None)
    assert not (tmp_path / "ws").exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_git_104_a_moved_ref_on_a_v0_server_names_where_it_points(tmp_path, mocker):
    """TC-GIT-104: clone_at_commit — the commit cannot be fetched by id and the branch
    now points elsewhere: the error says where, nothing is built from the new tip."""
    mocker.patch.object(git_service, "_current_allowed_hosts", return_value=[])
    _fake_git(mocker, [(0, ""), (1, ""), (0, f"{'c' * 40}\trefs/heads/main\n")])

    with pytest.raises(git_service.GitUrlError, match="now points at cccccccccccc, not 3f2a9c1d4b5e"):
        await git_service.clone_at_commit(URL, "main", "branch", SHA1, tmp_path / "ws", None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_git_105_resolve_ref_refuses_a_malformed_answer(mocker):
    """TC-GIT-105: resolve_ref — what the server answers is validated like any commit
    id before it is used; another ref ending in the same name is not taken."""
    mocker.patch.object(git_service, "_current_allowed_hosts", return_value=[])
    _fake_git(mocker, [(0, "--upload-pack=x\trefs/heads/main\n")])
    with pytest.raises(git_service.GitUrlError):
        await git_service.resolve_ref(URL, "main", "branch", None)

    _fake_git(mocker, [(0, f"{SHA1}\trefs/heads/feature/refs/heads/main\n")])
    with pytest.raises(git_service.GitUrlError, match="not found"):
        await git_service.resolve_ref(URL, "main", "branch", None)


# ---------- the build path ----------


def _git_config(**extra) -> BuildConfig:
    return BuildConfig(project_type=ProjectType.BACKEND_ONLY, source_type=SourceType.GIT, git_url=URL,
                       git_ref="main", **extra)


@pytest.fixture
def prepare(mocker, tmp_path):
    """_prepare_git_workspace with credentials, settings, task store and git replaced."""
    tm = build_dispatcher.task_manager
    mocker.patch.object(tm, "append_log", mocker.AsyncMock())
    set_commit = mocker.patch.object(tm, "set_commit", mocker.AsyncMock())

    @contextlib.asynccontextmanager
    async def session():
        yield mocker.MagicMock()

    mocker.patch("app.database.async_session", session)
    mocker.patch("app.services.git_credentials.resolve_for_url", mocker.AsyncMock(return_value=(None, "generic")))
    settings = mocker.Mock(git_workspace_dir=str(tmp_path), git_clone_timeout=60)
    mocker.patch("app.config.get_settings", return_value=settings)
    resolve = mocker.patch.object(git_service, "resolve_ref", mocker.AsyncMock(return_value=SHA1))
    clone = mocker.patch.object(git_service, "clone_at_commit", mocker.AsyncMock(return_value=False))
    mocker.patch.object(build_dispatcher, "_prepare_venv", mocker.AsyncMock())
    # The Config stage (packwright.toml) has its own tests (test_packwright_toml).
    mocker.patch.object(build_dispatcher, "_config_stage", mocker.AsyncMock(side_effect=lambda tid, cfg, root: cfg))
    return resolve, clone, set_commit


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_cmt_001_the_ref_is_resolved_recorded_and_checked_out(prepare):
    """TC-CMT-001: _prepare_git_workspace — without a commit, the ref is resolved once,
    recorded on the build, and exactly that commit is checked out."""
    resolve, clone, set_commit = prepare
    await build_dispatcher._prepare_git_workspace("t-1", _git_config())

    resolve.assert_awaited_once()
    set_commit.assert_awaited_once_with("t-1", SHA1)
    assert clone.await_args.kwargs["commit"] == SHA1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_cmt_002_a_given_commit_is_built_as_is(prepare):
    """TC-CMT-002: _prepare_git_workspace — a commit given with the build (a pushed
    commit) is not re-resolved: the branch may have moved since."""
    resolve, clone, set_commit = prepare
    given = "b" * 40
    await build_dispatcher._prepare_git_workspace("t-2", _git_config(), given)

    resolve.assert_not_awaited()
    set_commit.assert_awaited_once_with("t-2", given)
    assert clone.await_args.kwargs["commit"] == given


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_cmt_003_a_malformed_given_commit_stops_before_git(prepare):
    """TC-CMT-003: _prepare_git_workspace — a malformed commit fails the clone step and
    is neither recorded nor passed on."""
    resolve, clone, set_commit = prepare
    with pytest.raises(git_service.GitUrlError):
        await build_dispatcher._prepare_git_workspace("t-3", _git_config(), "--upload-pack=x")
    set_commit.assert_not_awaited()
    clone.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.parametrize("sha", BAD_IDS[:-1])
def test_tc_cmt_004_the_rest_field_takes_only_a_full_id(sha):
    """TC-CMT-004: TaskCreate.git_commit — only a full commit id is accepted."""
    with pytest.raises(ValidationError):
        TaskCreate(project_name="a", config=_git_config(), git_commit=sha)
    assert TaskCreate(project_name="a", config=_git_config(), git_commit=SHA1).git_commit == SHA1
    assert TaskCreate(project_name="a", config=_git_config(), git_commit="").git_commit is None


@pytest.mark.unit
def test_tc_cmt_005_a_commit_needs_a_git_source():
    """TC-CMT-005: TaskCreate — a commit for a Local source is refused."""
    local = BuildConfig(project_type=ProjectType.BACKEND_ONLY, project_path="/srv/app")
    with pytest.raises(ValidationError, match="only to Git sources"):
        TaskCreate(project_name="a", config=local, git_commit=SHA1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_cmt_006_an_unknown_trigger_is_refused(mocker):
    """TC-CMT-006: task_manager.create_task — a trigger outside the known set is a bug
    in the caller and is refused before anything is stored."""
    from app.services.task_manager import TaskManager

    db = mocker.AsyncMock()
    with pytest.raises(ValueError, match="Unknown build trigger"):
        await TaskManager().create_task(TaskCreate(project_name="a", config=_git_config()), db, trigger="webhook")
    db.add.assert_not_called()
