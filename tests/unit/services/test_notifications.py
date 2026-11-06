"""
Unit tests for build notifications.
Source: app/services/notifications

What is pinned: which URLs are accepted for each kind (a channel link pasted
instead of a webhook should fail when saved, not after the next build), that
the page only ever sees a hint of the URL, the message bodies (including that
text from a build cannot ping a whole channel), and how delivery handles
errors, retries and redirects.
"""

import httpx
import pytest

from app.services import notifications as n

DISCORD = "https://discord.com/api/webhooks/123/abcDEF"
SLACK = "https://hooks.slack.com/services/T000/B000/XXXXyyyy"
HOOK = "https://ci.example.com/hooks/packwright"


def _failed(**over) -> n.BuildOutcome:
    base = dict(
        event="failed", project="shop", version="1.2.0", task_id="t-1", triggered_by="mei",
        duration_seconds=252.4, problem="A module is missing at runtime", suggestion="Add it under Include packages",
        link="https://pw.example.com/history/t-1",
    )
    return n.BuildOutcome(**{**base, **over})


class TestValidateUrl:
    @pytest.mark.unit
    def test_tc_ntf_001_accepts_each_kinds_own_urls(self):
        """TC-NTF-001: Discord, Slack and any http(s) URL for a plain webhook; whitespace trimmed."""
        assert n.validate_url("discord", f"  {DISCORD} ") == DISCORD
        assert n.validate_url("discord", "https://discordapp.com/api/webhooks/1/x")
        assert n.validate_url("slack", SLACK) == SLACK
        assert n.validate_url("slack", "https://hooks.slack.com/triggers/T0/1/abc")
        assert n.validate_url("webhook", HOOK) == HOOK
        assert n.validate_url("webhook", "http://10.0.0.5:8080/notify")

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("kind", "url", "says"),
        [
            ("discord", "https://discord.com/channels/1/2", "not a Discord incoming webhook"),
            ("discord", "http://discord.com/api/webhooks/1/x", "not a Discord incoming webhook"),
            ("slack", "https://example.slack.com/archives/C01", "not a Slack incoming webhook"),
            ("slack", "https://hooks.slack.com.evil.example/services/x", "not a Slack incoming webhook"),
            ("webhook", "ftp://example.com/x", "must start with https://"),
            ("webhook", "https://", "must start with https://"),
            ("webhook", "   ", "Enter the webhook URL"),
            ("webhook", "https://example.com/" + "a" * 2000, "longer than"),
            ("email", HOOK, "Unknown destination type"),
        ],
    )
    def test_tc_ntf_002_rejects_with_a_reason(self, kind, url, says):
        """TC-NTF-002: a URL that cannot work is refused when saved, saying why."""
        with pytest.raises(n.InvalidDestination, match=says):
            n.validate_url(kind, url)

    @pytest.mark.unit
    def test_tc_ntf_003_hint_never_shows_the_secret_part(self):
        """TC-NTF-003: the hint is the host and the last 4 characters, nothing between."""
        hint = n.url_hint(SLACK)
        assert hint == "hooks.slack.com …yyyy"
        assert "T000" not in hint and "B000" not in hint


class TestMessages:
    @pytest.mark.unit
    def test_tc_ntf_004_discord_failure(self):
        """TC-NTF-004: a red embed with the diagnosis, linked, mentions disabled."""
        body = n.payload("discord", _failed())
        embed = body["embeds"][0]
        assert embed["title"] == "shop 1.2.0 failed"
        assert embed["url"] == "https://pw.example.com/history/t-1"
        assert embed["color"] == n.FAILED_COLOR
        assert embed["description"].splitlines() == [
            "A module is missing at runtime", "Add it under Include packages", "Started by mei, took 4 min 12 s.",
        ]
        assert body["allowed_mentions"] == {"parse": []}

    @pytest.mark.unit
    def test_tc_ntf_005_slack_text_cannot_ping_or_inject_links(self):
        """TC-NTF-005: <!channel>, <@U1> and & in a build's text are escaped for Slack."""
        body = n.payload("slack", _failed(project="<!channel> shop", problem="a <@U1> & b", link=None))
        assert body["text"].startswith("*&lt;!channel&gt; shop 1.2.0 failed*")
        assert "a &lt;@U1&gt; &amp; b" in body["text"]
        assert "<!channel>" not in body["text"]

    @pytest.mark.unit
    def test_tc_ntf_006_slack_title_links_to_the_build(self):
        """TC-NTF-006: with PUBLIC_URL the title is a link to the build's page."""
        body = n.payload("slack", _failed(event="passed", problem=None, suggestion=None))
        assert body["text"].splitlines()[0] == "*<https://pw.example.com/history/t-1|shop 1.2.0 passed>*"

    @pytest.mark.unit
    def test_tc_ntf_007_generic_webhook_body(self):
        """TC-NTF-007: the JSON body names the event, the build and the diagnosis."""
        body = n.payload("webhook", _failed())
        assert body == {
            "event": "failed", "project": "shop", "version": "1.2.0", "build_id": "t-1", "status": "failed",
            "triggered_by": "mei", "duration_seconds": 252.4,
            "diagnosis": {"problem": "A module is missing at runtime", "suggestion": "Add it under Include packages"},
            "url": "https://pw.example.com/history/t-1", "title": "shop 1.2.0 failed",
        }
        passed = n.payload("webhook", _failed(event="passed", problem=None, suggestion=None))
        assert passed["status"] == "completed" and passed["diagnosis"] is None

    @pytest.mark.unit
    def test_tc_ntf_008_passed_build_without_version_or_link(self):
        """TC-NTF-008: no version, no link: the message still reads."""
        o = n.BuildOutcome(event="passed", project="shop", triggered_by="mei", duration_seconds=8)
        embed = n.payload("discord", o)["embeds"][0]
        assert embed["title"] == "shop passed" and "url" not in embed
        assert embed["color"] == n.PASSED_COLOR and embed["description"] == "Started by mei, took 8 s."

    @pytest.mark.unit
    def test_tc_ntf_009_link_needs_public_url(self):
        """TC-NTF-009: the build link exists only when PUBLIC_URL is set."""
        assert n.build_link("https://pw.example.com/", "t-1") == "https://pw.example.com/history/t-1"
        assert n.build_link("  ", "t-1") is None

    @pytest.mark.unit
    def test_tc_ntf_010_which_outcomes_a_destination_gets(self):
        """TC-NTF-010: passed and failed follow the switches; a test always goes."""

        class D:
            on_passed, on_failed = False, True

        assert n.wants(D, "failed") and not n.wants(D, "passed") and n.wants(D, "test")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


class TestDeliver:
    @pytest.fixture(autouse=True)
    def no_wait(self, monkeypatch):
        monkeypatch.setattr(n, "_RETRY_DELAY", 0)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_ntf_011_posts_json_and_accepts_2xx(self):
        """TC-NTF-011: one POST with the JSON body; 204 (Discord's answer) is success."""
        seen = []

        def handler(request):
            seen.append((request.method, request.headers["content-type"], request.content))
            return httpx.Response(204)

        async with _client(handler) as c:
            assert await n.deliver(DISCORD, {"a": 1}, client=c) == (True, None)
        assert seen == [("POST", "application/json", b'{"a":1}')]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_ntf_012_a_rejected_request_is_not_retried(self):
        """TC-NTF-012: 4xx means the URL or body is wrong; asking again will not help."""
        calls = []

        async with _client(lambda r: calls.append(r) or httpx.Response(404)) as c:
            assert await n.deliver(SLACK, {}, client=c) == (False, "hooks.slack.com answered HTTP 404")
        assert len(calls) == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [429, 502])
    async def test_tc_ntf_013_busy_or_broken_server_gets_one_retry(self, status):
        """TC-NTF-013: 429 and 5xx are tried once more."""
        answers = iter([httpx.Response(status), httpx.Response(200)])
        async with _client(lambda r: next(answers)) as c:
            assert await n.deliver(HOOK, {}, client=c) == (True, None)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_ntf_014_unreachable_after_retry(self):
        """TC-NTF-014: a network error is retried, then reported by host, not by URL."""
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.ConnectError("refused")

        async with _client(handler) as c:
            ok, error = await n.deliver(HOOK, {}, client=c)
        assert (ok, len(calls)) == (False, 2)
        assert error == "Could not reach ci.example.com: ConnectError"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tc_ntf_015_redirects_are_not_followed(self):
        """TC-NTF-015: a webhook that redirects is reported, not followed somewhere else."""
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

        async with _client(handler) as c:
            assert await n.deliver(HOOK, {}, client=c) == (False, "ci.example.com answered HTTP 302")
        assert calls == [HOOK]
