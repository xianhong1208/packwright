"""
Git credential API: hosts that can never match are refused, short tokens get no hint.
Source: app/api/routes/git_credentials.py, app/services/git_credentials.py
"""

import pytest


def _h(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.mark.integration
@pytest.mark.parametrize("host", ["https://x.com/", "localhost", "a b.com", "git.example.com:8443"])
def test_tc_int_073_a_host_that_can_never_match_is_a_400(client, admin_tokens, host):
    """TC-INT-073: creating a credential for a URL, localhost, a name with a space or a
    port is refused with 400 and stores nothing."""
    r = client.post("/api/settings/git-credentials", headers=_h(admin_tokens),
                    json={"provider": "generic", "host": host, "token": "glpat-0123456789abcdef"})

    assert r.status_code == 400, r.text
    assert isinstance(r.json()["detail"], str)
    assert all(c["host"] != host for c in client.get("/api/settings/git-credentials", headers=_h(admin_tokens)).json())


@pytest.mark.integration
def test_tc_int_074_hosts_are_normalised_and_short_tokens_hidden(client, admin_tokens):
    """TC-INT-074: the host is stored as a clone URL's host reads; a short token gets no
    hint on create or on update, a long one shows its last four."""
    r = client.post("/api/settings/git-credentials", headers=_h(admin_tokens),
                    json={"provider": "gitlab", "host": " Git.Example.ORG. ", "token": "abcd"})
    assert r.status_code == 201, r.text
    created = r.json()
    assert (created["host"], created["token_hint"]) == ("git.example.org", None)

    updated = client.put(f"/api/settings/git-credentials/{created['id']}", headers=_h(admin_tokens),
                         json={"token": "glpat-0123456789abcdef"}).json()
    assert updated["token_hint"] == "cdef"
    again = client.put(f"/api/settings/git-credentials/{created['id']}", headers=_h(admin_tokens),
                       json={"token": "short"}).json()
    assert again["token_hint"] is None
    # The default host still applies when none is given.
    gh = client.post("/api/settings/git-credentials", headers=_h(admin_tokens),
                     json={"provider": "github", "token": "ghp_0123456789abcdef0123"})
    assert gh.status_code == 201 and gh.json()["host"] == "github.com"
