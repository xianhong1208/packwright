"""
Build statistics on the dashboard: what the success rate is a rate of.
Source: app/api/routes/monitoring.get_build_stats

Cancelled builds were counted as failures: a month of 12 passes, 6 failures and
22 cancels showed a 30% success rate, and a project whose only builds were
cancelled showed a red 0%.
"""

import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _insert(project: str, status: str) -> None:
    db = os.environ["DATABASE_URL"].split(":///", 1)[1]
    start = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    end = (datetime.now(timezone.utc) - timedelta(minutes=59)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db) as con:
        con.execute(
            "INSERT INTO history (task_id, user_name, project_name, python_version, start_time, end_time, status, config)"
            " VALUES (?, 'admin', ?, '3.13', ?, ?, ?, '{}')",
            (str(uuid.uuid4()), project, start, end, status),
        )


def _stats(client, admin_tokens) -> dict:
    r = client.get("/api/monitoring/build-stats", headers={"Authorization": f"Bearer {admin_tokens['access_token']}"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.integration
def test_tc_int_045_cancelled_builds_are_not_failures(client, admin_tokens):
    """TC-INT-045: 2 passed, 1 failed, 3 cancelled is a 66.7% success rate, not 33.3%;
    a project that was only ever cancelled has no rate rather than 0%."""
    for status in ("COMPLETED", "COMPLETED", "FAILED", "CANCELLED", "CANCELLED", "CANCELLED"):
        _insert("rate-mixed", status)
    for _ in range(2):
        _insert("rate-cancelled-only", "CANCELLED")

    stats = _stats(client, admin_tokens)
    projects = {p["project_name"]: p for p in stats["projects"]}

    assert projects["rate-mixed"]["success_rate"] == 66.7
    assert projects["rate-cancelled-only"]["success_rate"] is None

    s = stats["summary"]
    assert s["cancelled"] >= 5
    assert s["success_rate"] == round(s["completed"] / (s["completed"] + s["failed"]) * 100, 1)
    today = [d for d in stats["daily"] if d["total"] >= 8][-1]
    assert today["success_rate"] == round(today["completed"] / (today["completed"] + today["failed"]) * 100, 1)
