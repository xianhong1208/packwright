"""ApiToken ORM model: personal API tokens for scripts and CI.

A token is shown once, when it is created; only its SHA-256 is stored, so the
table can leak without handing anyone a working token. ``token_prefix`` is the
first few characters (``pwt_`` plus eight), enough to recognise a token in the
console or in a secret scanner's report, and useless for signing in.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiToken(Base):
    """One personal API token. Its scopes are a space-separated list."""

    __tablename__ = "api_tokens"
    # Declared exactly as migration c9d4e1f7a2b6 creates them, so the schema
    # drift test compares like with like.
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
        Index("ix_api_tokens_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # hex SHA-256 of the whole token; the lookup key.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    scopes: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def scope_list(self) -> list[str]:
        return self.scopes.split()

    def expired(self, now: datetime) -> bool:
        # SQLite hands DateTime(timezone=True) back without tzinfo; it was
        # written as UTC.
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires <= now

    def __repr__(self) -> str:
        return f"<ApiToken {self.id} {self.token_prefix}… user={self.user_id}>"
