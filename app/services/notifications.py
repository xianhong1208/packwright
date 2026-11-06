"""Tell a project's channels how its builds ended.

A project lists destinations (app/models/notification): a Discord or Slack
incoming webhook, or any URL that takes a JSON POST. When a build of the project
passes or fails, each destination that wants that outcome gets one message,
sent after the build has finished and outside its build slot. A destination
that stops answering never affects a build; its last delivery is recorded and
shown on the project's settings so it does not fail unnoticed.

The message text comes from build names, versions and failure diagnoses, which
anyone who can build controls. Slack's control sequences are escaped and Discord
is told not to resolve mentions, so a build named "<!channel>" or "@everyone"
cannot page a whole channel.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

Kind = Literal["webhook", "discord", "slack"]
KINDS: tuple[str, ...] = ("webhook", "discord", "slack")
Event = Literal["passed", "failed", "test"]

# Where each service's incoming webhooks live. Checking it catches the usual
# mistake (a channel link pasted instead of the webhook URL) when it is saved,
# rather than as a silent failure after the next build.
_SERVICE_URLS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "discord": (("discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"), ("/api/webhooks/",)),
    "slack": (("hooks.slack.com",), ("/services/", "/triggers/", "/workflows/")),
}

_TIMEOUT = 10.0
_RETRY_DELAY = 2.0
MAX_URL_LENGTH = 2000

PASSED_COLOR = 0x6CC5BF  # the console's teal
FAILED_COLOR = 0xD9634F


class InvalidDestination(ValueError):
    """The URL cannot be a destination of that kind; the message says why."""


def validate_url(kind: str, url: str) -> str:
    """The URL, trimmed, if it can receive this kind of message."""
    if kind not in KINDS:
        raise InvalidDestination(f"Unknown destination type {kind!r}")
    url = url.strip()
    if not url:
        raise InvalidDestination("Enter the webhook URL")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidDestination(f"The URL is longer than {MAX_URL_LENGTH} characters")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise InvalidDestination("The URL must start with https:// (or http://) and name a host")
    if kind in _SERVICE_URLS:
        hosts, paths = _SERVICE_URLS[kind]
        label = "Discord" if kind == "discord" else "Slack"
        if parts.scheme != "https" or parts.hostname.lower() not in hosts or not parts.path.startswith(paths):
            raise InvalidDestination(
                f"This is not a {label} incoming webhook URL (it starts with https://{hosts[0]}{paths[0]})"
            )
    return url


def url_hint(url: str) -> str:
    """What the page shows instead of the URL: its host and last 4 characters."""
    host = urlsplit(url).hostname or "?"
    return f"{host} …{url[-4:]}"


@dataclass(frozen=True)
class BuildOutcome:
    event: Event
    project: str
    version: str | None = None
    task_id: str | None = None
    triggered_by: str | None = None
    duration_seconds: float | None = None
    problem: str | None = None
    suggestion: str | None = None
    link: str | None = None


def build_link(public_url: str, task_id: str | None) -> str | None:
    """The build's page, when PUBLIC_URL says where Packwright is reached."""
    if not public_url.strip() or not task_id:
        return None
    return f"{public_url.strip().rstrip('/')}/history/{task_id}"


def _duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = int(round(seconds))
    if total < 60:
        return f"{total} s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {secs} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def title(o: BuildOutcome) -> str:
    name = f"{o.project} {o.version}" if o.version else o.project
    if o.event == "test":
        return f"Test message from Packwright for {o.project}"
    return f"{name} {'passed' if o.event == 'passed' else 'failed'}"


def _details(o: BuildOutcome) -> list[str]:
    """Plain-text lines under the title."""
    if o.event == "test":
        return ["Build results of this project will arrive here."]
    lines: list[str] = []
    if o.event == "failed" and o.problem:
        lines.append(o.problem)
        if o.suggestion:
            lines.append(o.suggestion)
    who = f"Started by {o.triggered_by}" if o.triggered_by else None
    took = _duration(o.duration_seconds)
    tail = ", ".join(x for x in (who, f"took {took}" if took else None) if x)
    if tail:
        lines.append(tail + ".")
    return lines


def _slack_escape(text: str) -> str:
    # Slack reads <...> as links and mentions (<!channel>, <@U123>); & starts an entity.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def payload(kind: str, o: BuildOutcome) -> dict[str, Any]:
    """The JSON body for one destination."""
    if kind == "discord":
        embed: dict[str, Any] = {
            "title": title(o)[:256],
            "description": "\n".join(_details(o))[:4000],
            "color": FAILED_COLOR if o.event == "failed" else PASSED_COLOR,
        }
        if o.link:
            embed["url"] = o.link
        # No mention in a build's text may ping anyone.
        return {"username": "Packwright", "embeds": [embed], "allowed_mentions": {"parse": []}}
    if kind == "slack":
        head = _slack_escape(title(o))
        head = f"<{o.link}|{head}>" if o.link else head
        body = "\n".join(_slack_escape(line) for line in _details(o))
        return {"text": f"*{head}*" + (f"\n{body}" if body else "")}
    return {
        "event": o.event,
        "project": o.project,
        "version": o.version,
        "build_id": o.task_id,
        "status": {"passed": "completed", "failed": "failed"}.get(o.event, "test"),
        "triggered_by": o.triggered_by,
        "duration_seconds": o.duration_seconds,
        "diagnosis": {"problem": o.problem, "suggestion": o.suggestion} if o.problem else None,
        "url": o.link,
        "title": title(o),
    }


async def deliver(url: str, body: dict[str, Any], *, client: httpx.AsyncClient | None = None) -> tuple[bool, str | None]:
    """POST the body; (True, None) on a 2xx. A network error, 429 or 5xx is tried
    once more. Redirects are not followed: a webhook that moves is reported."""
    own = client is None
    http = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
    try:
        error = "not sent"
        for attempt in (1, 2):
            try:
                response = await http.post(url, json=body)
            except httpx.HTTPError as exc:
                error = f"Could not reach {urlsplit(url).hostname}: {type(exc).__name__}"
            else:
                if 200 <= response.status_code < 300:
                    return True, None
                error = f"{urlsplit(url).hostname} answered HTTP {response.status_code}"
                if response.status_code != 429 and response.status_code < 500:
                    return False, error
            if attempt == 1:
                await asyncio.sleep(_RETRY_DELAY)
        return False, error
    finally:
        if own:
            await http.aclose()


def wants(destination: Any, event: Event) -> bool:
    """Whether a destination asked for this outcome; a test always goes."""
    if event == "test":
        return True
    return bool(destination.on_passed if event == "passed" else destination.on_failed)


async def send_to(destination: Any, outcome: BuildOutcome) -> tuple[bool, str | None]:
    """Send one message and record how it went on the destination row (the
    caller commits)."""
    from app.services.crypto import DecryptionError, decrypt_secret

    try:
        url = decrypt_secret(destination.url_encrypted)
    except DecryptionError:
        ok, error = False, "The stored URL could not be decrypted (SETTINGS_ENCRYPTION_KEY changed); enter it again"
    else:
        ok, error = await deliver(url, payload(destination.kind, outcome))
    destination.last_sent_at = datetime.now(timezone.utc)
    destination.last_ok = ok
    destination.last_error = None if ok else (error or "failed")[:300]
    return ok, error


async def notify_build(task_id: str) -> None:
    """Send a finished build's outcome to its project's destinations. Never raises:
    a notification problem is logged, not turned into a build problem."""
    from sqlalchemy import select

    from app.config import get_settings
    from app.database import async_session
    from app.models.notification import ProjectNotification
    from app.models.project import Project
    from app.models.task import Task

    try:
        async with async_session() as db:
            task = (await db.execute(select(Task).where(Task.task_id == task_id))).scalar_one_or_none()
            if task is None or task.project_id is None:
                return
            status = str(task.status).lower().rsplit(".", 1)[-1]
            if status not in ("completed", "failed"):
                return
            event: Event = "passed" if status == "completed" else "failed"
            destinations = [
                d for d in (await db.execute(
                    select(ProjectNotification).where(ProjectNotification.project_id == task.project_id)
                )).scalars().all()
                if wants(d, event)
            ]
            if not destinations:
                return
            project = await db.get(Project, task.project_id)
            result = task.result if isinstance(task.result, dict) else {}
            diagnosis = (result.get("diagnosis") or [{}])[0] if event == "failed" else {}
            outcome = BuildOutcome(
                event=event,
                project=project.name if project else task.project_name,
                version=task.version,
                task_id=task.task_id,
                triggered_by=task.user_name,
                duration_seconds=result.get("duration_seconds"),
                problem=diagnosis.get("problem") if isinstance(diagnosis, dict) else None,
                suggestion=diagnosis.get("suggestion") if isinstance(diagnosis, dict) else None,
                link=build_link(get_settings().public_url, task.task_id),
            )
            for destination in destinations:
                ok, error = await send_to(destination, outcome)
                if not ok:
                    logger.warning("Notification %s for build %s not delivered: %s", destination.id, task_id, error)
            await db.commit()
    except Exception:
        logger.exception("Notifications for build %s were not sent", task_id)


# Running sends, referenced so they are not garbage-collected half way.
_pending: set[asyncio.Task[None]] = set()


def notify_build_soon(task_id: str) -> None:
    """Start notify_build in the background, so a slow or dead webhook neither
    holds the build slot nor delays the next queued build."""
    task = asyncio.create_task(notify_build(task_id))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
