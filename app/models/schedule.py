"""Scheduled builds: a project's schedules and what each run came to.

A schedule builds one branch or tag of a Git project on a 5-field cron
expression, read in the schedule's own time zone. The next run is stored
(``next_run_at``, UTC) so it survives a restart; the scheduler claims a run by
moving ``next_run_at`` forward with a conditional UPDATE, so a run fires once
even when two scheduler loops look at the same moment (app/services/schedules).

Like a webhook, a schedule builds as the person who created it, checked again at
every run. If that person can no longer build, the schedule is turned off with
the reason, rather than building as nobody in particular.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProjectSchedule(Base):
    __tablename__ = "project_schedules"
    # Declared exactly as migration e6b2c8d4f1a3 creates them.
    __table_args__ = (
        Index("ix_project_schedules_project_id", "project_id"),
        Index("ix_project_schedules_next_run_at", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Deleting a project deletes its schedules (and, through them, their runs).
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_schedules_project_id"), nullable=False
    )
    # Five fields (minute hour day-of-month month day-of-week) or an @alias.
    cron: Mapped[str] = mapped_column(String(100), nullable=False)
    # IANA name the cron expression is read in, e.g. Asia/Taipei.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # The branch or tag that builds; resolved to a commit when the run fires.
    ref: Mapped[str] = mapped_column(String(255), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(8), nullable=False, default="branch")
    # Skip a run when the commit and the settings equal the last successful build of this ref.
    skip_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Why Packwright turned the schedule off (its creator may no longer build);
    # None when a person turned it off or it is on.
    disabled_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # When the next run is due (UTC); None while the schedule is off.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Whom the builds run as. A deleted account leaves NULL, and the next run
    # turns the schedule off with the reason.
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL", name="fk_project_schedules_created_by_id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<ProjectSchedule {self.id} {self.cron!r} project={self.project_id}>"


class ScheduleRun(Base):
    """One run of a schedule, and what came of it. The newest 50 per schedule are kept."""

    __tablename__ = "schedule_runs"
    __table_args__ = (Index("ix_schedule_runs_schedule_id", "schedule_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("project_schedules.id", ondelete="CASCADE", name="fk_schedule_runs_schedule_id"),
        nullable=False,
    )
    # The slot the run was for, and when it was handled.
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # built | skipped | failed
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # The commit the ref pointed at, when it was resolved.
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The build it started (history.task_id) for "built", or the build it matched
    # ("unchanged") or waited on ("overlap") for "skipped".
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
