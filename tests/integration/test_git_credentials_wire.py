"""
Integration test: what a real git binary sends with the credential environment.
Source: app/services/git_service (_git_env / _auth_env)

Runs `git ls-remote` against local HTTP servers that record request headers.
Proves the token reaches git through the environment (never argv or a URL)
and that it is scoped to the repository's origin: another host never gets it,
whether git is pointed there directly (submodules, a second remote) or
redirected (libcurl also drops it on a cross-origin redirect; the scope does
not depend on that).
"""

import base64
import http.server
import shutil
import subprocess
import threading

import pytest

from app.services.git_service import _git_env

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _server(seen: list, redirect_to: str | None = None):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            if redirect_to:
                self.send_response(302)
                self.send_header("Location", redirect_to + self.path)
            else:
                self.send_response(404)
            self.end_headers()

        def log_message(self, *_):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.integration
def test_tc_int_030_token_is_sent_as_scoped_header_only_to_its_host():
    """TC-INT-030: the repo host gets the Basic header; a redirect target does not."""
    other_seen: list = []
    other = _server(other_seen)
    repo_seen: list = []
    repo = _server(repo_seen, redirect_to=f"http://127.0.0.1:{other.server_port}")
    url = f"http://127.0.0.1:{repo.server_port}/g/p.git"
    try:
        result = subprocess.run(["git", "ls-remote", url], env=_git_env(url, "SECRET-TOK", "gitlab"),
                                capture_output=True, text=True, timeout=30)
    finally:
        repo.shutdown()
        other.shutdown()

    expected = "Basic " + base64.b64encode(b"oauth2:SECRET-TOK").decode()
    assert expected in repo_seen
    assert all(h is None for h in other_seen)
    assert "SECRET-TOK" not in result.stderr


@pytest.mark.integration
def test_tc_int_031_credential_built_for_one_host_is_not_sent_to_another():
    """TC-INT-031: env built for repo A, git talking to host B -> no header at B.

    This is what the http.<origin>/.extraHeader key buys over a bare
    http.extraHeader, which would be attached to every request git makes.
    """
    a_seen: list = []
    a = _server(a_seen)
    b_seen: list = []
    b = _server(b_seen)
    try:
        env = _git_env(f"http://127.0.0.1:{a.server_port}/g/p.git", "SECRET-TOK", "gitlab")
        subprocess.run(["git", "ls-remote", f"http://127.0.0.1:{b.server_port}/other.git"],
                       env=env, capture_output=True, text=True, timeout=30)
    finally:
        a.shutdown()
        b.shutdown()

    assert b_seen and all(h is None for h in b_seen)

