"""
Unit tests for what a Git credential may be stored under, and its hint.
Source: app/services/git_credentials.py (normalize_host, token_hint)

A credential is found by the clone URL's host name. "https://x.com/",
"localhost" and "a b.com" were accepted, never matched anything, and the page
then said builds clone from https://https://x.com//. A four-character token was
shown whole as its "hint".
"""

import pytest

from app.services.git_credentials import InvalidHostError, normalize_host, token_hint


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("gitlab.example.com", "gitlab.example.com"),
        ("  GitLab.Example.COM. ", "gitlab.example.com"),
        ("git-01.corp_internal.example", "git-01.corp_internal.example"),
        ("github.com", "github.com"),
        ("10.0.0.5", "10.0.0.5"),
        ("[2001:db8::1]", "2001:db8::1"),
    ],
)
def test_tc_gch_001_host_names_and_addresses_are_kept(raw, stored):
    """TC-GCH-001: a host name (any case, trailing dot) or an IP address is stored as
    the clone URL's host would read."""
    assert normalize_host(raw) == stored


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "says"),
    [
        ("https://x.com/", "without https://"),
        ("gitlab.example.com/group", "without https://"),
        ("localhost", "localhost"),
        ("git.localhost", "localhost"),
        ("gitlab.example.com:8443", "port"),
        ("a b.com", "not a valid host name"),
        ("-bad.example.com", "not a valid host name"),
        ("bad..example.com", "not a valid host name"),
        ("ex@mple.com", "not a valid host name"),
        ("a" * 64 + ".com", "not a valid host name"),
    ],
)
def test_tc_gch_002_anything_that_can_never_match_is_refused(raw, says):
    """TC-GCH-002: a URL, a path, localhost, a port, spaces and malformed labels are
    refused with a message that says what to enter instead."""
    with pytest.raises(InvalidHostError) as exc:
        normalize_host(raw)
    assert says in str(exc.value)


@pytest.mark.unit
def test_tc_gch_003_short_tokens_get_no_hint():
    """TC-GCH-003: the last four characters are shown only for a token of 16 or more;
    for a shorter one they would give away most or all of it."""
    assert token_hint("glpat-0123456789abcdef") == "cdef"
    assert token_hint("0123456789abcdef") == "cdef"
    assert token_hint("0123456789abcde") is None
    assert token_hint("abcd") is None
