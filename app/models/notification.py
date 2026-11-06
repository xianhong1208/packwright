"""Where a project's build results are sent: a Discord or Slack channel, or any
URL that takes a JSON POST.

A webhook URL is a credential (whoever holds a Slack or Discord one can post to
the channel), so it is stored encrypted like a Git token and never sent back to
the browser; `url_hint` (host and last characters) is what the page shows.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProjectNotification(Base):
    __tablename__ = "project_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Deleting a project deletes where it notified.
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_notifications_project_id"),
        nullable=False, index=True,
    )
    # webhook | discord | slack
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    url_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    url_hint: Mapped[str] = mapped_column(String(120), nullable=False)
    on_failed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    on_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # The last delivery, so a URL that stopped working shows up on the page
    # instead of failing silently.
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
