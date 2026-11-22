"""Task ORM model for database persistence."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.schemas.task import TaskStatus


class Task(Base):
    """Task model for storing build task history."""

    __tablename__ = "history"
    __table_args__ = (Index("ix_history_project_version", "project_name", "version"),)

    task_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        index=True,
    )
    user_name: Mapped[str] = mapped_column(String(100), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    python_version: Mapped[str] = mapped_column(String(10), nullable=False)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(TaskStatus),
        default=TaskStatus.PENDING,
        nullable=False,
    )
    output_dir: Mapped[str] = mapped_column(String(500), nullable=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Copied out of config so a project's builds can be grouped, and an already-built
    # version found, with an index rather than by reading every config.
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The project this build is a version of (app/models/project). A deleted
    # project leaves its builds in history, unfiled.
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL", name="fk_history_project_id"), nullable=True, index=True
    )
    # Structured build outcome (preflight checks, artifact summary, smoke-test
    # verdict). Added after the table already existed — see init_db()'s
    # idempotent ALTER for the additive migration on existing databases.
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The exact commit a Git build checked out (40 hex, or 64 for a SHA-256
    # repository): the ref it named is only where the branch or tag pointed then.
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # What started the build: console, api, push, tag or schedule
    # (app/schemas/task.BuildTrigger). Rows from before the column are console builds.
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="console", server_default="console")
    # What the build was really made with once packwright.toml was read: the
    # effective settings, each field's origin (file, override, project, detected)
    # and the keys and lines the file set (app/services/packwright_toml.record).
    # config above stays what was submitted: a rebuild starts from it.
    effective_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<Task {self.task_id}: {self.project_name} ({self.status})>"
