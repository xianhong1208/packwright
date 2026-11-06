"""A project: one piece of code the team builds again and again.

Every build used to carry its whole configuration and nothing tied two builds of
the same code together, so a project's builds scattered across names ("app",
"app v1.2 test"). A Project holds the source and the default settings; each build
is a snapshot of them for one version, linked back by history.project_id.

Projects are shared by everyone who may build: anyone with task:create can see one
and build a new version of it. Changing its settings or deleting it is for whoever
created it and holders of project:manage. That is no wider than before — the trust
model already treats task:create as command execution on this machine.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Unique: the name is how people find a project, and how a build is filed
    # under one when it arrives without a project id.
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    project_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # The folder path or Git URL the project builds from.
    source: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Default settings for a new build: a BuildConfig dump.
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Project {self.id}: {self.name}>"
