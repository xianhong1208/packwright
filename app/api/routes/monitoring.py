"""System monitoring API routes."""

import sys
from typing import Annotated

from fastapi import APIRouter, Depends
from datetime import date, datetime, timedelta, timezone
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.system_stats import get_sampler
from app.models.task import Task
from app.services.permission import (
    CurrentUser,
    PermissionCode,
    get_current_user,
    require_any_permission,
)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/stats")
async def get_system_stats(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    """Current system resource usage: one snapshot shared by every viewer
    (app/services/system_stats)."""
    return await get_sampler().get()


def _collect_build_environment() -> dict:
    """Report which compile targets are actually usable right now.

    This exists because the failure it detects is silent. A per-version venv
    is a symlink to a uv-managed interpreter; change the user that runs the
    service, move the machine, or clean uv's cache and the link dangles.
    find_nuitka_python() then correctly refuses it and quietly falls back to
    the service's own interpreter, so users keep picking "3.14" and keep
    getting a 3.13 binary that only fails at their customer's runtime.

    Nothing surfaced that state before: it took reading the history table to
    notice. Surfacing it is the whole point of putting it on a dashboard.
    """
    from app.services.nuitka_worker import _APP_ROOT

    service_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    targets: list[dict] = []
    for venv_dir in sorted(_APP_ROOT.glob(".venv-py3*")):
        compact = venv_dir.name.removeprefix(".venv-py")
        if not compact.isdigit() or len(compact) < 2:
            continue
        python_bin = venv_dir / "bin" / "python"
        # exists() follows the symlink — that is exactly the check that matters.
        usable = python_bin.exists()
        targets.append(
            {
                "version": f"{compact[0]}.{compact[1:]}",
                "venv": venv_dir.name,
                "usable": usable,
                # Show where a broken link points; without it the operator has
                # no idea whether the target moved or the user changed.
                "target": str(python_bin.readlink()) if python_bin.is_symlink() else None,
            }
        )

    return {
        "service_python": service_version,
        "targets": targets,
        "degraded": [t["version"] for t in targets if not t["usable"]],
    }


@router.get("/build-stats")
async def get_build_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    _: None = Depends(
        require_any_permission(
            PermissionCode.HISTORY_VIEW_OWN, PermissionCode.HISTORY_VIEW_ALL
        )
    ),
    days: int = 30,
) -> dict:
    """Aggregate build outcomes for the dashboard.

    Scoped the same way as GET /api/history: holders of history:view_all see
    everyone, everyone else sees only their own builds — so the numbers a user
    reads always match the list they can open.
    """
    scoped = not current_user.has_permission(PermissionCode.HISTORY_VIEW_ALL)
    window_days = max(1, min(days, 365))
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Fetch the window's rows once and aggregate in Python. The window is bounded
    # (<= 365 days), so this stays cheap while remaining portable across SQLite
    # and PostgreSQL — no dialect-specific SQL (FILTER / array_agg / jsonb / casts).
    stmt = select(Task).where(Task.start_time > cutoff)
    if scoped:
        stmt = stmt.where(Task.user_name == current_user.username)
    rows = list((await db.execute(stmt)).scalars().all())

    def _status(t: Task) -> str:
        return (t.status or "").upper()

    def _pass_rate(passed: int, failed: int) -> float | None:
        """Passed out of the builds that reached a verdict. Cancelled and still
        running builds say nothing about whether builds work: counting them as
        failures showed 30% for a week of 12 passes, 6 failures and 22 cancels."""
        finished = passed + failed
        return round(passed / finished * 100, 1) if finished else None

    total = len(rows)
    completed = sum(1 for t in rows if _status(t) == "COMPLETED")
    failed = sum(1 for t in rows if _status(t) == "FAILED")
    cancelled = sum(1 for t in rows if _status(t) == "CANCELLED")

    durations = [
        (t.end_time - t.start_time).total_seconds()
        for t in rows
        if _status(t) == "COMPLETED" and t.end_time is not None and t.start_time is not None
    ]
    avg_seconds = sum(durations) / len(durations) if durations else None

    # Daily totals, keyed by calendar day.
    by_day: dict[date, dict] = defaultdict(lambda: {"total": 0, "completed": 0, "failed": 0})
    for t in rows:
        if t.start_time is None:
            continue
        d = t.start_time.date()
        by_day[d]["total"] += 1
        if _status(t) == "COMPLETED":
            by_day[d]["completed"] += 1
        elif _status(t) == "FAILED":
            by_day[d]["failed"] += 1
    daily = [
        {
            "day": str(d),
            "total": v["total"],
            "completed": v["completed"],
            "failed": v["failed"],
            "success_rate": _pass_rate(v["completed"], v["failed"]),
        }
        for d, v in sorted(by_day.items())
    ]

    # Per-project rollup. `recent` is the last 12 outcomes newest-first so the UI
    # can render a run strip. Every project is listed, not only the failing ones.
    by_project: dict[str, list[Task]] = defaultdict(list)
    for t in rows:
        by_project[t.project_name].append(t)
    projects = []
    for name, tasks in by_project.items():
        tasks.sort(key=lambda t: (t.start_time or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        p_completed = sum(1 for t in tasks if _status(t) == "COMPLETED")
        p_failed = sum(1 for t in tasks if _status(t) == "FAILED")
        last_run = tasks[0].start_time if tasks else None
        projects.append({
            "project_name": name,
            "total": len(tasks),
            "completed": p_completed,
            "failed": p_failed,
            "success_rate": _pass_rate(p_completed, p_failed),
            "last_status": _status(tasks[0]).lower() if tasks else "",
            "last_run": last_run.isoformat() if last_run else None,
            "recent": [_status(t).lower() for t in tasks[:12]],
        })
    projects.sort(key=lambda p: p["last_run"] or "", reverse=True)
    projects = projects[:25]

    # Failure reasons from the diagnosis each build already produced (result JSON).
    problem_counts: dict[str, int] = defaultdict(int)
    for t in rows:
        if _status(t) != "FAILED" or not isinstance(t.result, dict):
            continue
        for d in t.result.get("diagnosis") or []:
            problem = d.get("problem") if isinstance(d, dict) else None
            if problem:
                problem_counts[problem] += 1
    top_failures = sorted(
        ({"problem": k, "count": v} for k, v in problem_counts.items()),
        key=lambda f: f["count"],
        reverse=True,
    )[:8]
    diagnosed = sum(f["count"] for f in top_failures)

    return {
        "window_days": window_days,
        "scope": "own" if scoped else "all",
        "summary": {
            "total": total,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "success_rate": _pass_rate(completed, failed),
            "avg_duration_seconds": round(avg_seconds, 1) if avg_seconds is not None else None,
        },
        "daily": daily,
        "projects": projects,
        "top_failures": top_failures,
        "diagnosis_coverage": round(diagnosed / failed * 100, 1) if failed else None,
        "environment": _collect_build_environment(),
    }
