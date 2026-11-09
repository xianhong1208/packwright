"""
Unit tests for the environment a build step runs with.
Source: app/services/build_env.build_environment, and the build steps that use it
(frontend_worker._run_command, docker_worker._run_docker_command,
nuitka_worker.get_valid_std_libs_for and the Nuitka compile).

A build runs code the person starting it chose: npm scripts, Dockerfile RUN
lines, the project's own Python. It used to get the service's whole os.environ,
which under a systemd EnvironmentFile= or a container `environment:` block holds
JWT_SECRET_KEY and SETTINGS_ENCRYPTION_KEY — enough to sign an admin token and
decrypt every stored Git credential. Nothing fails if this regresses: the build
passes either way, so these tests are the only thing that notices.
"""

import re
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from app.services.build_env import build_environment

SECRETS = {
    "JWT_SECRET_KEY": "signing-key",
    "SETTINGS_ENCRYPTION_KEY": "fernet-key",
    "GITLAB_TOKEN": "glpat-xxxx",
    "DATABASE_URL": "postgresql://u:p@db/packwright",
    "AWS_SECRET_ACCESS_KEY": "aws-secret",
}


@pytest.fixture
def host_env(mocker: MockerFixture):
    """Replace os.environ wholesale so the real one cannot influence a result."""

    def _set(**values: str):
        mocker.patch.dict("app.services.build_env.os.environ", values, clear=True)

    return _set


@pytest.fixture
def passthrough(mocker: MockerFixture):
    """Set BUILD_ENV_PASSTHROUGH for one test."""

    def _set(names: list[str]):
        settings = mocker.Mock(build_env_passthrough_names=names)
        mocker.patch("app.services.build_env.get_settings", return_value=settings)

    return _set


class TestBuildEnvironment:
    @pytest.mark.unit
    def test_tc_benv_001_secrets_and_unlisted_variables_are_dropped(self, host_env, passthrough):
        """TC-BENV-001: build_environment — the service's secrets do not reach a build."""
        passthrough([])
        host_env(PATH="/usr/bin", HOME="/root", **SECRETS)

        assert build_environment() == {"PATH": "/usr/bin", "HOME": "/root"}

    @pytest.mark.unit
    def test_tc_benv_002_proxy_and_ca_settings_pass(self, host_env, passthrough):
        """TC-BENV-002: build_environment — builds behind a proxy or a private CA keep working."""
        passthrough([])
        host_env(
            HTTPS_PROXY="http://proxy:3128", https_proxy="http://proxy:3128", NO_PROXY="localhost",
            NODE_EXTRA_CA_CERTS="/etc/ca.pem", SSL_CERT_FILE="/etc/ca.pem", LANG="C.UTF-8",
        )

        assert build_environment() == {
            "HTTPS_PROXY": "http://proxy:3128", "https_proxy": "http://proxy:3128", "NO_PROXY": "localhost",
            "NODE_EXTRA_CA_CERTS": "/etc/ca.pem", "SSL_CERT_FILE": "/etc/ca.pem", "LANG": "C.UTF-8",
        }

    @pytest.mark.unit
    def test_tc_benv_003_tool_configuration_prefixes_pass(self, host_env, passthrough):
        """TC-BENV-003: build_environment — registry, Docker daemon and cache settings pass by prefix."""
        passthrough([])
        host_env(
            NPM_CONFIG_REGISTRY="https://npm.example", YARN_CACHE_FOLDER="/c", DOCKER_HOST="tcp://d:2375",
            CCACHE_MAXSIZE="5G", NUITKA_CACHE_DIR="/n",
            # Look-alikes: the prefix must start the name.
            MY_DOCKER_TOKEN="x", APP_NPM_CONFIG_SECRET="y",
        )

        assert set(build_environment()) == {
            "NPM_CONFIG_REGISTRY", "YARN_CACHE_FOLDER", "DOCKER_HOST", "CCACHE_MAXSIZE", "NUITKA_CACHE_DIR",
        }

    @pytest.mark.unit
    def test_tc_benv_004_operator_listed_names_pass(self, host_env, passthrough):
        """TC-BENV-004: build_environment — BUILD_ENV_PASSTHROUGH adds exactly the names it lists."""
        passthrough(["SENTRY_AUTH_TOKEN", "ARTIFACTORY_URL"])
        host_env(SENTRY_AUTH_TOKEN="s", ARTIFACTORY_URL="https://a", SENTRY_DSN="not listed", **SECRETS)

        assert build_environment() == {"SENTRY_AUTH_TOKEN": "s", "ARTIFACTORY_URL": "https://a"}

    @pytest.mark.unit
    def test_tc_benv_005_extra_overrides_the_host(self, host_env, passthrough):
        """TC-BENV-005: build_environment — the step's own values win over the host's."""
        passthrough([])
        host_env(TERM="dumb", PATH="/usr/bin")

        assert build_environment({"TERM": "xterm-256color", "CI": "true"}) == {
            "TERM": "xterm-256color", "CI": "true", "PATH": "/usr/bin",
        }

    @pytest.mark.unit
    def test_tc_benv_006_passthrough_setting_is_parsed(self):
        """TC-BENV-006: Settings.build_env_passthrough_names — commas, spaces, empty entries."""
        from app.config import Settings

        assert Settings(build_env_passthrough=" A, B ,,C ").build_env_passthrough_names == ["A", "B", "C"]
        assert Settings(build_env_passthrough="").build_env_passthrough_names == []


class TestBuildStepsUseIt:
    """Each step that runs the project's code gets build_environment(), not os.environ."""

    @pytest.fixture
    def secret_host(self, mocker: MockerFixture, passthrough):
        passthrough([])
        mocker.patch.dict("app.services.build_env.os.environ", {"PATH": "/usr/bin", **SECRETS}, clear=True)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_benv_010_frontend_commands(self, mocker: MockerFixture, secret_host, tmp_path: Path):
        """TC-BENV-010: frontend_worker._run_command — npm/yarn/pnpm scripts get the build environment."""
        from app.services import frontend_worker

        run = mocker.patch.object(frontend_worker, "run_step", mocker.AsyncMock(return_value=mocker.Mock(ok=True)))
        await frontend_worker._run_command("t1", ["npm", "run", "build"], tmp_path)

        env = run.call_args.kwargs["env"]
        assert env == {"PATH": "/usr/bin", "TERM": "xterm-256color", "CI": "true"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_benv_011_docker_build(self, mocker: MockerFixture, secret_host, tmp_path: Path):
        """TC-BENV-011: docker_worker._run_docker_command — RUN lines get the build environment."""
        from app.services import docker_worker

        run = mocker.patch.object(docker_worker, "run_step", mocker.AsyncMock(return_value=mocker.Mock(ok=True)))
        await docker_worker._run_docker_command("t1", ["docker", "build", "."], tmp_path)

        env = run.call_args.kwargs["env"]
        assert env == {"PATH": "/usr/bin", "TERM": "xterm-256color", "DOCKER_BUILDKIT": "1"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_benv_012_project_python_probe(self, mocker: MockerFixture, secret_host):
        """TC-BENV-012: get_valid_std_libs_for — the project's interpreter is started with the build environment."""
        from app.services import nuitka_worker

        proc = mocker.Mock(returncode=0)
        proc.communicate = mocker.AsyncMock(return_value=(b'{"libs": [], "packages": []}', b""))
        spawn = mocker.patch.object(nuitka_worker.asyncio, "create_subprocess_exec", mocker.AsyncMock(return_value=proc))
        await nuitka_worker.get_valid_std_libs_for("/project/.venv/bin/python")

        assert spawn.call_args.kwargs["env"] == {"PATH": "/usr/bin"}


@pytest.mark.unit
def test_tc_benv_020_no_build_step_passes_the_host_environment_whole():
    """TC-BENV-020: app/services — nothing hands os.environ to a subprocess whole.

    Covers the Nuitka compile, which the unit tests cannot drive. db_backup runs
    pg_dump, not project code, and is the one exception.
    """
    services = Path(__file__).resolve().parents[3] / "app" / "services"
    whole = re.compile(r"\*\*os\.environ|os\.environ\.copy\(\)|dict\(os\.environ\)|build_environment\(os\.environ")
    offenders = [
        f"{path.name}:{n}"
        for path in sorted(services.glob("*.py")) if path.name != "db_backup.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if whole.search(line)
    ]
    assert offenders == []
