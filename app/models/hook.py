"""Incoming webhooks: a project's hooks and what they received.

A hook is one URL a Git forge (GitHub, GitLab, Gitea) or any script posts to,
``/api/hooks/<provider>/<public_id>``. ``public_id`` is random and long, but it is
not the secret: every delivery must also carry a signature or token made with
the hook's own secret, which is stored encrypted (app/services/crypto) and shown
once. A GitLab hook may also hold GitLab's signing token, which GitLab generates
and the person pastes in.

The build a delivery starts runs as the person who created the hook. If that
person can no longer build (deactivated, role changed, account gone) the hook is
disabled with the reason, rather than building as nobody in particular.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProjectHook(Base):
    __tablename__ = "project_hooks"
    # Declared exactly as migration d4f7a9c2e8b1 creates them.
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_project_hooks_public_id"),
        Index("ix_project_hooks_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The random part of the hook's URL.
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # Deleting a project deletes its hooks (and, through them, their deliveries).
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_hooks_project_id"), nullable=False
    )
    # github | gitlab | gitea | generic
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    # Fernet ciphertext of the hook's secret (the HMAC key, GitLab's secret token,
    # or the generic URL's token).
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # GitLab only: the signing token GitLab generated (whsec_…), encrypted. When
    # set, deliveries must be signed with it; the plain token is no longer enough.
    signing_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Glob patterns, one per line, for branch names and tag names that build.
    # Empty means none of that kind builds.
    branches: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    tags: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Why the hook was turned off when Packwright did it (its creator may no
    # longer build); None when a person disabled it or it is enabled.
    disabled_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Whom triggered builds run as. A deleted account leaves NULL, and the next
    # delivery that would build disables the hook with the reason.
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL", name="fk_project_hooks_created_by_id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    secret_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ProjectHook {self.id} {self.provider} project={self.project_id}>"


class HookDelivery(Base):
    """One request a hook received, and what came of it. The newest 50 per hook are kept."""

    __tablename__ = "hook_deliveries"
    __table_args__ = (Index("ix_hook_deliveries_hook_id_delivery_id", "hook_id", "delivery_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hook_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("project_hooks.id", ondelete="CASCADE", name="fk_hook_deliveries_hook_id"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The sender's id for this delivery (X-GitHub-Delivery, webhook-id, …).
    delivery_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # built | ignored | rejected
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # The build it started (history.task_id), for "built".
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
