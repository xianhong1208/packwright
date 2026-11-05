"""
Unit tests for the pure (non-subprocess) helpers of the Git source mode.
Source: app/services/git_service.py

These functions are the security boundary described in that module's
SECURITY INVARIANTS docstring: URL/ref validation gate every network call,
and token injection/masking decide whether a secret leaks into a log line.
"""

import pytest

from app.services.git_service import (
    GitUrlError,
    _auth_env,
    _git_env,
    mask_token_in_log,
    parse_dependency_groups,
    validate_git_ref,
    validate_git_url,
)

from .conftest import GITLAB_TOKEN, PRIVATE_IP_URL, PUBLIC_REPO_URL


class TestValidateGitUrl:
    """Tests for validate_git_url — the SSRF / scheme gate."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "url",
        [
            "https://gitlab.example.com/group/project.git",
            "http://gitlab.example.com/group/project.git",
            "https://gitlab.example.com:8443/group/project.git",
            "https://93.184.216.34/group/project.git",  # public IP literal
        ],
    )
    def test_tc_git_001_accepts_public_http_urls(self, url):
        """TC-GIT-001: validate_git_url — public http/https URLs accepted."""
        assert validate_git_url(url) is None

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ssh://git@gitlab.example.com/g/p.git",
            "git://gitlab.example.com/g/p.git",
            "ftp://gitlab.example.com/g/p.git",
        ],
    )
    def test_tc_git_002_rejects_non_http_schemes(self, url):
        """TC-GIT-002: validate_git_url — non-http(s) schemes rejected."""
        with pytest.raises(GitUrlError, match="Unsupported URL scheme"):
            validate_git_url(url)

    @pytest.mark.unit
    def test_tc_git_003_rejects_embedded_credentials(self):
        """TC-GIT-003: validate_git_url — userinfo in URL rejected."""
        with pytest.raises(GitUrlError, match="must not contain embedded credentials"):
            validate_git_url("https://user:secret@gitlab.example.com/g/p.git")

    @pytest.mark.unit
    def test_tc_git_004_rejects_missing_host(self):
        """TC-GIT-004: validate_git_url — URL without a host rejected."""
        with pytest.raises(GitUrlError, match="missing a host component"):
            validate_git_url("https:///group/project.git")

    @pytest.mark.unit
    def test_tc_git_005_rejects_dotdot_in_path(self):
        """TC-GIT-005: validate_git_url — '..' path traversal rejected."""
        with pytest.raises(GitUrlError, match="must not contain '\\.\\.'"):
            validate_git_url("https://gitlab.example.com/group/../../etc/p.git")

    @pytest.mark.unit
    @pytest.mark.parametrize("host", ["localhost", "ip6-localhost", "ip6-loopback"])
    def test_tc_git_006_rejects_blocked_hostnames(self, host):
        """TC-GIT-006: validate_git_url — localhost aliases always rejected."""
        with pytest.raises(GitUrlError, match="is not allowed"):
            validate_git_url(f"https://{host}/g/p.git")

    @pytest.mark.unit
    def test_tc_git_007_blocked_hostname_not_overridable_by_allowlist(self):
        """TC-GIT-007: validate_git_url — allowlist cannot re-enable localhost."""
        with pytest.raises(GitUrlError, match="is not allowed"):
            validate_git_url("https://localhost/g/p.git", allowed_hosts=["localhost"])

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/g/p.git",       # loopback
            "https://192.168.1.20/g/p.git",  # private
            "https://10.0.0.5/g/p.git",        # private
            "https://169.254.169.254/g/p.git", # link-local (cloud metadata)
            "https://0.0.0.0/g/p.git",         # unspecified
            "https://224.0.0.1/g/p.git",       # multicast
        ],
    )
    def test_tc_git_008_rejects_non_routable_ips_without_allowlist(self, url):
        """TC-GIT-008: validate_git_url — non-routable IP literals rejected when no allowlist."""
        with pytest.raises(GitUrlError, match="not a routable public address"):
            validate_git_url(url)

    @pytest.mark.unit
    def test_tc_git_009_allowlist_opts_in_private_ip(self):
        """TC-GIT-009: validate_git_url — allowlisted private IP is accepted."""
        assert validate_git_url(PRIVATE_IP_URL, allowed_hosts=["192.168.1.20"]) is None

    @pytest.mark.unit
    def test_tc_git_010_rejects_host_outside_allowlist(self):
        """TC-GIT-010: validate_git_url — host not in allowlist rejected."""
        with pytest.raises(GitUrlError, match="is not in the allowlist"):
            validate_git_url(PUBLIC_REPO_URL, allowed_hosts=["gitlab.internal.corp"])

    @pytest.mark.unit
    @pytest.mark.parametrize("url", ["", None])
    def test_tc_git_011_rejects_empty_url(self, url):
        """TC-GIT-011: validate_git_url — empty/None URL rejected."""
        with pytest.raises(GitUrlError, match="Git URL is required"):
            validate_git_url(url)

    @pytest.mark.unit
    def test_tc_git_012_rejects_overlong_url(self):
        """TC-GIT-012: validate_git_url — URL longer than 2048 chars rejected."""
        with pytest.raises(GitUrlError, match="too long"):
            validate_git_url("https://gitlab.example.com/" + "a" * 2100)

    @pytest.mark.unit
    def test_tc_git_013_host_match_is_case_insensitive(self):
        """TC-GIT-013: validate_git_url — uppercase host matches lowercase allowlist."""
        assert (
            validate_git_url(
                "https://GitLab.Example.COM/g/p.git",
                allowed_hosts=["gitlab.example.com"],
            )
            is None
        )


class TestValidateGitRef:
    """Tests for validate_git_ref — argv-injection defence for branch/tag names."""

    @pytest.mark.unit
    @pytest.mark.parametrize("ref", ["main", "release/1.2.0", "v1.0.0", "feature_x", "1.0"])
    def test_tc_git_020_accepts_normal_refs(self, ref):
        """TC-GIT-020: validate_git_ref — ordinary branch/tag names accepted."""
        assert validate_git_ref(ref) is None

    @pytest.mark.unit
    @pytest.mark.parametrize("ref", ["", None])
    def test_tc_git_021_rejects_empty_ref(self, ref):
        """TC-GIT-021: validate_git_ref — empty/None ref rejected."""
        with pytest.raises(GitUrlError, match="is required"):
            validate_git_ref(ref)

    @pytest.mark.unit
    def test_tc_git_022_rejects_overlong_ref(self):
        """TC-GIT-022: validate_git_ref — ref longer than 255 chars rejected."""
        with pytest.raises(GitUrlError, match="too long"):
            validate_git_ref("a" * 256)

    @pytest.mark.unit
    @pytest.mark.parametrize("ref", ["--upload-pack=touch /tmp/pwn", "-x"])
    def test_tc_git_023_rejects_option_lookalike_ref(self, ref):
        """TC-GIT-023: validate_git_ref — leading '-' rejected (would be a git option)."""
        with pytest.raises(GitUrlError, match="must not start with '-'"):
            validate_git_ref(ref)

    @pytest.mark.unit
    def test_tc_git_024_rejects_dotdot_ref(self):
        """TC-GIT-024: validate_git_ref — '..' rejected."""
        with pytest.raises(GitUrlError, match="must not contain '\\.\\.'"):
            validate_git_ref("main..evil")

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "ref",
        [
            "main branch",   # whitespace
            "main\tx",       # tab
            "main\nrm -rf",  # newline
            "main\x00",      # NUL
            "main~1",
            "main^2",
            "refs:main",
            "main?",
            "main*",
            "main[0]",
            "main\\x",
        ],
    )
    def test_tc_git_025_rejects_forbidden_characters(self, ref):
        """TC-GIT-025: validate_git_ref — whitespace/control/git-special chars rejected."""
        with pytest.raises(GitUrlError, match="forbidden characters"):
            validate_git_ref(ref)


class TestCredentialEnvironment:
    """The token reaches git as a host-scoped extraHeader in the environment.

    In the clone URL it used to be written into every workspace's .git/config
    and was visible in `ps`.
    """

    @pytest.mark.unit
    def test_tc_git_030_header_is_scoped_to_the_repository_host(self):
        """TC-GIT-030: the config key names this origin, so redirects elsewhere get nothing."""
        env = _auth_env(PUBLIC_REPO_URL, GITLAB_TOKEN)
        assert env["GIT_CONFIG_COUNT"] == "1"
        assert env["GIT_CONFIG_KEY_0"] == "http.https://gitlab.example.com/.extraHeader"
        assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
        assert GITLAB_TOKEN not in PUBLIC_REPO_URL

    @pytest.mark.unit
    def test_tc_git_031_preserves_port(self):
        """TC-GIT-031: a non-default port is part of the scoped origin."""
        env = _auth_env("https://gitlab.example.com:8443/g/p.git", GITLAB_TOKEN)
        assert env["GIT_CONFIG_KEY_0"] == "http.https://gitlab.example.com:8443/.extraHeader"

    @pytest.mark.unit
    @pytest.mark.parametrize("token", [None, ""])
    def test_tc_git_032_no_token_adds_no_credential(self, token):
        """TC-GIT-032: falsy token -> no GIT_CONFIG_* at all, prompts still disabled."""
        env = _git_env(PUBLIC_REPO_URL, token)
        assert not any(k.startswith("GIT_CONFIG") for k in env)
        assert env["GIT_TERMINAL_PROMPT"] == "0"


class TestMaskTokenInLog:
    """Tests for mask_token_in_log — last line of defence before git output is logged."""

    @pytest.mark.unit
    def test_tc_git_040_masks_literal_token(self):
        """TC-GIT-040: mask_token_in_log — bare token occurrence replaced with ***."""
        result = mask_token_in_log(f"fatal: auth failed for {GITLAB_TOKEN}", GITLAB_TOKEN)
        assert GITLAB_TOKEN not in result
        assert result == "fatal: auth failed for ***"

    @pytest.mark.unit
    def test_tc_git_041_masks_oauth2_userinfo_without_token_arg(self):
        """TC-GIT-041: mask_token_in_log — oauth2 userinfo masked even when token is unknown."""
        text = "remote: https://oauth2:some-other-secret@gitlab.example.com/g/p.git not found"
        result = mask_token_in_log(text)
        assert "some-other-secret" not in result
        assert "oauth2:***@gitlab.example.com" in result

    @pytest.mark.unit
    def test_tc_git_042_masks_both_forms_in_one_pass(self):
        """TC-GIT-042: mask_token_in_log — literal token inside an oauth2 URL fully masked."""
        text = f"error cloning https://oauth2:{GITLAB_TOKEN}@gitlab.example.com/g/p.git"
        result = mask_token_in_log(text, GITLAB_TOKEN)
        assert GITLAB_TOKEN not in result
        assert result.endswith("https://oauth2:***@gitlab.example.com/g/p.git")

    @pytest.mark.unit
    def test_tc_git_043_leaves_clean_text_unchanged(self):
        """TC-GIT-043: mask_token_in_log — text with no secret is returned as-is."""
        text = "Cloning into 'project'... done."
        assert mask_token_in_log(text, GITLAB_TOKEN) == text

    @pytest.mark.unit
    @pytest.mark.parametrize("text", ["", None])
    def test_tc_git_044_empty_text_short_circuits(self, text):
        """TC-GIT-044: mask_token_in_log — empty/None text returned unchanged."""
        assert mask_token_in_log(text, GITLAB_TOKEN) == text


class TestParseDependencyGroups:
    """Tests for parse_dependency_groups — PEP 735 group picker for the UI."""

    @pytest.mark.unit
    def test_tc_git_050_returns_sorted_group_names(self):
        """TC-GIT-050: parse_dependency_groups — group names returned sorted."""
        toml_text = """
[project]
name = "x"

[dependency-groups]
test = ["pytest"]
dev = ["ruff"]
docs = ["mkdocs"]
"""
        assert parse_dependency_groups(toml_text) == ["dev", "docs", "test"]

    @pytest.mark.unit
    def test_tc_git_051_ignores_optional_dependencies(self):
        """TC-GIT-051: parse_dependency_groups — [project.optional-dependencies] is NOT a group."""
        toml_text = """
[project.optional-dependencies]
dev = ["ruff"]
"""
        assert parse_dependency_groups(toml_text) == []

    @pytest.mark.unit
    def test_tc_git_052_missing_table_returns_empty(self):
        """TC-GIT-052: parse_dependency_groups — absent table yields []."""
        assert parse_dependency_groups('[project]\nname = "x"\n') == []

    @pytest.mark.unit
    def test_tc_git_053_malformed_toml_returns_empty(self):
        """TC-GIT-053: parse_dependency_groups — unparseable TOML yields [] (not an exception)."""
        assert parse_dependency_groups("[dependency-groups\ndev = [") == []

    @pytest.mark.unit
    def test_tc_git_054_non_table_value_returns_empty(self):
        """TC-GIT-054: parse_dependency_groups — non-table dependency-groups yields []."""
        assert parse_dependency_groups('dependency-groups = "dev"\n') == []

    @pytest.mark.unit
    def test_tc_git_055_empty_text_returns_empty(self):
        """TC-GIT-055: parse_dependency_groups — empty input yields []."""
        assert parse_dependency_groups("") == []


class TestPreviewReadsStayInTheClone:
    """A cloned repo may commit symlinks; the preview must not follow them out."""

    @pytest.mark.unit
    def test_tc_git_090_symlinked_env_file_is_not_read(self, tmp_path):
        """TC-GIT-090: .env -> (file outside the clone) is skipped, regular .env read."""
        from app.services.git_service import _read_env_files

        secret = tmp_path / "service.env"
        secret.write_text("JWT_SECRET_KEY=do-not-leak")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".env").symlink_to(secret)
        (repo / ".env.production").write_text("API_URL=https://api.example.com")

        files = _read_env_files(repo, root=repo)

        assert ".env" not in files
        assert files == {".env.production": "API_URL=https://api.example.com"}

    @pytest.mark.unit
    def test_tc_git_091_symlinked_package_json_is_ignored(self, tmp_path):
        """TC-GIT-091: detection does not read a package.json that points outside."""
        from app.services.git_service import _detect_frontend_config

        outside = tmp_path / "pkg.json"
        outside.write_text('{"scripts": {"build": "x"}, "packageManager": "pnpm@9"}')
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "package.json").symlink_to(outside)

        assert _detect_frontend_config(repo, root=repo)["build_command"] is None


class TestSsrfSpellings:
    """Loopback/private targets in spellings the old check did not recognise."""

    @pytest.mark.unit
    @pytest.mark.parametrize("url", [
        "http://127.1/g/p.git",
        "http://2130706433/g/p.git",
        "http://0x7f000001/g/p.git",
        "http://0177.0.0.1/g/p.git",
        "http://localhost./g/p.git",
        "http://foo.localhost/g/p.git",
        "http://[::ffff:127.0.0.1]/g/p.git",
        "http://[::ffff:169.254.169.254]/latest",
    ])
    def test_tc_git_095_alternate_loopback_spellings_are_rejected(self, url):
        """TC-GIT-095: numeric/hex/octal/trailing-dot/*.localhost/mapped forms are refused."""
        with pytest.raises(GitUrlError):
            validate_git_url(url)

    @pytest.mark.unit
    @pytest.mark.parametrize("url", ["https://1e100.net/g/p.git", "https://gitlab.com/g/p.git",
                                     "https://8.8.8.8/g/p.git"])
    def test_tc_git_096_public_names_and_addresses_still_pass(self, url):
        """TC-GIT-096: hostnames that merely look numeric-ish, and public IPs, are allowed."""
        validate_git_url(url)
