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



def _bare_repo(root, name: str) -> None:
    """A one-commit bare repository served over git's dumb HTTP protocol."""
    src = root / f"{name}-src"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "main.py").write_text("print('hi')\n")
    subprocess.run(["git", "-C", str(src), "add", "."], check=True)
    subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(root / f"{name}.git")], check=True)
    subprocess.run(["git", "-C", str(root / f"{name}.git"), "update-server-info"], check=True)


def _repo_server(root, seen: list, private_login: str | None = None):
    """Serves the bare repositories under ``root`` through `git http-backend` (smart
    HTTP, so shallow clones work). /private.git admits only ``private_login``; any
    other repository is public but, like GitHub, refuses a request that carries a
    credential it does not accept."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def _serve(self):
            auth = self.headers.get("Authorization")
            seen.append(auth)
            path, _, query = self.path.partition("?")
            allowed = auth == private_login if path.startswith("/private.git") else auth is None
            if not allowed:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="git"')
                self.end_headers()
                return
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            cgi = subprocess.run(
                ["git", "http-backend"], input=body, capture_output=True, check=False,
                env={"GIT_PROJECT_ROOT": str(root), "GIT_HTTP_EXPORT_ALL": "1", "PATH_INFO": path,
                     "QUERY_STRING": query, "REQUEST_METHOD": self.command,
                     "CONTENT_TYPE": self.headers.get("Content-Type", ""), "PATH": "/usr/bin:/bin"},
            )
            head, _, payload = cgi.stdout.partition(b"\r\n\r\n")
            headers = [line.split(":", 1) for line in head.decode().split("\r\n") if ":" in line]
            status = next((v.strip() for k, v in headers if k.lower() == "status"), "200")
            self.send_response(int(status.split()[0]))
            for k, v in headers:
                if k.lower() != "status":
                    self.send_header(k, v.strip())
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = _serve

        def log_message(self, *_):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.integration
def test_tc_int_069_the_hosts_own_git_login_is_never_used(tmp_path, monkeypatch):
    """TC-INT-069: a credential helper in the service account's ~/.gitconfig and a
    ~/.netrc entry are not consulted: the server sees no credential, and the helper is
    neither asked ("get") nor told to forget one ("erase")."""
    home = tmp_path / "home"
    home.mkdir()
    helper_log = tmp_path / "helper.log"
    (home / ".gitconfig").write_text(
        "[credential]\n"
        f"\thelper = \"!f() {{ echo \\\"$1\\\" >> {helper_log}; echo username=host-user; echo password=HOST-SECRET; }}; f\"\n"
    )
    (home / ".netrc").write_text("machine 127.0.0.1 login netrc-user password NETRC-SECRET\n")
    (home / ".netrc").chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    _bare_repo(tmp_path, "private")
    seen: list = []
    host_login = "Basic " + base64.b64encode(b"host-user:HOST-SECRET").decode()
    srv = _repo_server(tmp_path, seen, private_login=host_login)
    url = f"http://127.0.0.1:{srv.server_port}/private.git"
    try:
        result = subprocess.run(["git", "ls-remote", url], env=_git_env(url, None),
                                capture_output=True, text=True, timeout=30)
    finally:
        srv.shutdown()

    # git's own empty answer from GIT_ASKPASS=/bin/true is all that is ever sent.
    empty = "Basic " + base64.b64encode(b":").decode()
    assert result.returncode != 0
    assert seen and all(h in (None, empty) for h in seen)
    assert not helper_log.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tc_int_070_a_refused_stored_credential_falls_back_to_anonymous(tmp_path, mocker):
    """TC-INT-070: a stale stored token no longer blocks a public repository: the clone
    is retried without it (and says so); a private repository still fails, naming the
    refused login."""
    from app.services import git_service

    mocker.patch.object(git_service, "_current_allowed_hosts", return_value=["127.0.0.1"])
    _bare_repo(tmp_path, "public")
    _bare_repo(tmp_path, "private")
    seen: list = []
    srv = _repo_server(tmp_path, seen, private_login="Basic " + base64.b64encode(b"oauth2:current").decode())
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        anonymous = await git_service.clone_repo(f"{base}/public.git", "main", "branch",
                                                 tmp_path / "clone", "stale-token", provider="generic")
        refs = await git_service.list_refs(f"{base}/public.git", "stale-token", provider="generic")
        with pytest.raises(git_service.GitUrlError) as exc:
            await git_service.clone_repo(f"{base}/private.git", "main", "branch",
                                         tmp_path / "clone2", "stale-token", provider="generic")
    finally:
        srv.shutdown()

    assert anonymous is True
    assert (tmp_path / "clone" / "main.py").exists()
    assert refs["branches"] == ["main"]
    assert any(h is not None for h in seen) and None in seen  # tried with, then without
    assert "Authentication failed" in str(exc.value)
    assert "stale-token" not in str(exc.value)
    assert not (tmp_path / "clone2").exists()
