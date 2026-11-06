"""
What the Builds list returns for each build.
Source: app/api/routes/tasks (get_history, _result_summary)

The list left the result out, so the home page and the Builds list could not say
how big an output was or whether its smoke test passed without opening each build.
"""

import json
import os
import sqlite3
import uuid

import pytest

RESULT_PASSED = {
    "preflight": [{"label": "Project path", "passed": True}],
    "artifact": {"path": "dist/app", "size_bytes": 39636172, "size_human": "37.8 MB", "file_count": 1},
    "verify": {"status": "pass", "detail": "exited 0"},
    "duration_seconds": 31.5,
    "diagnosis": [],
    "error_lines": [],
}
RESULT_FAILED = {
    "diagnosis": [
        {"problem": "No package.json in the frontend directory", "suggestion": "Check it."},
        {"problem": "Second guess", "suggestion": "Maybe."},
    ],
    "error_lines": [f"npm error line {i}" for i in range(40)],
    "failed_stage": "frontend",
}


def _insert(status: str, result: dict | None) -> str:
    task_id = str(uuid.uuid4())
    db = os.environ["DATABASE_URL"].split(":///", 1)[1]
    with sqlite3.connect(db) as con:
        con.execute(
            "INSERT INTO history (task_id, user_name, project_name, python_version, start_time, status, config, result)"
            " VALUES (?, 'admin', 'listed', '3.13', '2026-11-05 00:00:00', ?, '{}', ?)",
            (task_id, status, json.dumps(result) if result is not None else None),
        )
    return task_id


def _row(client, admin_tokens, task_id: str) -> dict:
    r = client.get("/api/history", headers={"Authorization": f"Bearer {admin_tokens['access_token']}"})
    assert r.status_code == 200, r.text
    return next(row for row in r.json() if row["task_id"] == task_id)


@pytest.mark.integration
def test_tc_int_043_list_rows_carry_the_outcome(client, admin_tokens):
    """TC-INT-043: a passed build's row has its size and smoke test; a failed one its
    stage and first diagnosis."""
    passed = _row(client, admin_tokens, _insert("COMPLETED", RESULT_PASSED))
    assert passed["result"]["artifact"]["size_human"] == "37.8 MB"
    assert passed["result"]["verify"]["status"] == "pass"

    failed = _row(client, admin_tokens, _insert("FAILED", RESULT_FAILED))
    assert failed["result"]["failed_stage"] == "frontend"
    assert [d["problem"] for d in failed["result"]["diagnosis"]] == ["No package.json in the frontend directory"]


@pytest.mark.integration
def test_tc_int_044_list_rows_leave_the_detail_out(client, admin_tokens):
    """TC-INT-044: preflight checks and error lines stay on the detail page — the list
    returns up to 1000 rows — and a stored result that no longer validates lists as
    none instead of failing the whole list."""
    failed = _row(client, admin_tokens, _insert("FAILED", RESULT_FAILED))
    assert failed["result"]["error_lines"] == [] and failed["result"]["preflight"] == []

    broken = _row(client, admin_tokens, _insert("COMPLETED", {"verify": {"status": "exploded"}}))
    assert broken["result"] is None

    # A preflight entry from an older schema is not shown in the list, so it must
    # not cost the row its size.
    old_preflight = dict(RESULT_PASSED, preflight=[{"key": "path", "status": "pass"}])
    assert _row(client, admin_tokens, _insert("COMPLETED", old_preflight))["result"]["artifact"]["size_human"] == "37.8 MB"

    detail = client.get(f"/api/history/{_insert('FAILED', RESULT_FAILED)}",
                        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"}).json()
    assert len(detail["result"]["error_lines"]) == 40
