"""packwright.toml: a project's build settings kept in its own repository.

A file named ``packwright.toml`` at the root of the source being built (the exact
commit of a Git build, the folder of a local one) sets build settings field by
field. Its shape mirrors the project settings in the console, grouped::

    schema = 1

    [project]
    type = "backend_only"

    [python]
    entry = "src/app.py"
    pack_mode = "external"

    [docker]
    enabled = true
    port = 8080

What wins, field by field: **the file > this build's own changes > the project's
saved settings > what the console detected**. The file never writes into the
saved settings: a value it sets is used for that build only, and the build
records every field's value and where it came from (``history.effective_config``),
which is what the console marks.

The file is checked before anything heavy runs, at the build's "Config" stage.
Anything wrong fails the build there with the key and the line: a TOML syntax
error, an unknown key, a wrong type, an unknown ``schema`` version, a value the
console would refuse, a path outside the project, and anything that does not
belong in a repository (see ``_FORBIDDEN`` and ``looks_secret``).

The JSON Schema for editors is ``docs/packwright.schema.json``, generated from
``PackwrightFile`` by ``scripts/gen_packwright_schema.py`` (a test keeps them equal).
"""

from __future__ import annotations

import math
import re
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.task import BuildConfig

FILE_NAME = "packwright.toml"
SCHEMA_VERSION = 1
# A packwright.toml is a settings file, not a place for data.
MAX_BYTES = 64 * 1024
SCHEMA_URL = "https://raw.githubusercontent.com/xianhong1208/packwright/main/docs/packwright.schema.json"

Origin = Literal["file", "override", "project", "detected"]
ORIGINS: tuple[str, ...] = ("file", "override", "project", "detected")

# Settings that say which build this is rather than how the project is built
# (app/services/projects.PER_BUILD_FIELDS): their origin is "override" when the
# build names one, "project" otherwise.
_PER_BUILD = frozenset({"version"})


# ---------------------------------------------------------------------------
# The file's shape. Strict: "yes" is not a bool and "8080" is not a port, the way
# the console's form would never send them.

Str = Annotated[str, Field(strict=True)]
Bool = Annotated[bool, Field(strict=True)]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProjectSection(_Section):
    """How the project is built as a whole."""

    type: Literal["backend_only", "frontend_only", "fullstack"] | None = Field(
        default=None, description="backend_only (Python), frontend_only, or fullstack"
    )
    version: Str | None = Field(default=None, description="The version being built (1.2.0, v2.0.0-rc.1)")
    output_dir: Str | None = Field(default=None, description="Output directory, relative to the project")


class NuitkaSection(_Section):
    """Nuitka options."""

    jobs: Annotated[int, Field(strict=True, ge=0, le=1024)] | None = Field(
        default=None, description="Parallel C compile jobs; 0 = automatic"
    )
    anti_bloat: Bool | None = Field(default=None, description="Keep Nuitka's anti-bloat plugin on")
    include_package_data: list[Str] | None = Field(
        default=None, description="Packages whose data files are bundled (--include-package-data)"
    )
    report: Bool | None = Field(default=None, description="Write Nuitka's compilation report")


class PythonSection(_Section):
    """The Python backend (backend_only and fullstack)."""

    version: Str | None = Field(default=None, description="Compile-target Python: auto (recommended) or e.g. 3.13")
    entry: Str | None = Field(default=None, description="Entry point, relative to the project")
    output_name: Str | None = Field(default=None, description="Name of the program; empty = from the entry point")
    onefile: Bool | None = Field(default=None, description="A single executable file")
    pack_mode: Literal["external", "full"] | None = Field(
        default=None, description="external: third-party packages beside the program; full: compiled in"
    )
    source_dirs: list[Str] | None = Field(default=None, description="More Python source directories to compile")
    data_dirs: list[Str] | None = Field(default=None, description="Data directories copied beside the program")
    include_packages: list[Str] | None = Field(
        default=None, description="Packages to force-include (dynamic imports Nuitka cannot see)"
    )
    dependency_groups: list[Str] | None = Field(
        default=None, description="PEP 735 dependency groups installed for Git builds"
    )
    nuitka: NuitkaSection | None = None


class FrontendSection(_Section):
    """The frontend (frontend_only and fullstack)."""

    dir: Str | None = Field(default=None, description="Frontend directory, relative to the project")
    tool: Literal["npm", "yarn", "pnpm", "bun"] | None = Field(default=None, description="Package manager")
    build_command: Str | None = Field(default=None, description="The package.json script that builds it")
    output_dir: Str | None = Field(default=None, description="Build output, relative to the frontend directory")
    env_file: Str | None = Field(default=None, description="Env file written before the build (.env, .env.production)")
    env: dict[str, Str] | None = Field(
        default=None, description="Build-time variables written to env_file. No secrets: they are refused"
    )


class NginxSection(_Section):
    """nginx in a frontend-only image."""

    client_max_body_size: Str | None = None
    proxy_read_timeout: Str | None = None
    streaming: Bool | None = None
    gzip: Bool | None = None


class DockerSection(_Section):
    """The Docker image."""

    enabled: Bool | None = Field(default=None, description="Package the output as a Docker image")
    image_name: Str | None = None
    base_image: Str | None = None
    port: Annotated[int, Field(strict=True, ge=1, le=65535)] | None = Field(default=None, description="Port to expose")
    env: dict[str, Str] | None = Field(
        default=None, description="ENV in the image. No secrets: they are refused"
    )
    commands: list[Str] | None = Field(default=None, description="RUN commands, one per entry")
    install_node: Bool | None = None
    api_proxy: Str | None = None
    volumes: list[Str] | None = Field(default=None, description="Folders the program keeps its state in")
    run_as_root: Bool | None = Field(default=None, description="Run the program as root inside the image")
    nginx: NginxSection | None = None


class SmokeSection(_Section):
    """The smoke test after a build."""

    enabled: Bool | None = Field(default=None, description="Run the built program (or image) once after the build")


class PackwrightFile(_Section):
    """packwright.toml: build settings kept in the repository. They win over the
    project's settings in Packwright and over one build's changes."""

    model_config = ConfigDict(extra="forbid", strict=True, title="packwright.toml")

    schema_version: Literal[1] = Field(alias="schema", description="The file format version: 1")
    project: ProjectSection | None = None
    python: PythonSection | None = None
    frontend: FrontendSection | None = None
    docker: DockerSection | None = None
    smoke: SmokeSection | None = None


def json_schema() -> dict:
    """The JSON Schema editors use (Taplo / Even Better TOML: ``#:schema <url>``)."""
    schema = PackwrightFile.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = SCHEMA_URL
    return schema


# How each key maps onto a BuildConfig field, and how its value is written there.
#   scalar: as is      csv: a list joined with ", "     list: a list as is
#   lines: a list joined with newlines     env: a table written as KEY=VALUE lines
@dataclass(frozen=True)
class _Key:
    path: tuple[str, ...]
    field: str
    kind: str = "scalar"


KEYS: tuple[_Key, ...] = (
    _Key(("project", "type"), "project_type"),
    _Key(("project", "version"), "version"),
    _Key(("project", "output_dir"), "output_dir"),
    _Key(("python", "version"), "python_version"),
    _Key(("python", "entry"), "entry_point"),
    _Key(("python", "output_name"), "output_name"),
    _Key(("python", "onefile"), "onefile"),
    _Key(("python", "pack_mode"), "pack_mode"),
    _Key(("python", "source_dirs"), "extra_dirs", "csv"),
    _Key(("python", "data_dirs"), "data_dirs", "csv"),
    _Key(("python", "include_packages"), "include_packages", "csv"),
    _Key(("python", "dependency_groups"), "dependency_groups", "list"),
    _Key(("python", "nuitka", "jobs"), "nuitka_jobs"),
    _Key(("python", "nuitka", "anti_bloat"), "enable_anti_bloat"),
    _Key(("python", "nuitka", "include_package_data"), "include_package_data", "csv"),
    _Key(("python", "nuitka", "report"), "generate_report"),
    _Key(("frontend", "dir"), "frontend_dir"),
    _Key(("frontend", "tool"), "frontend_build_tool"),
    _Key(("frontend", "build_command"), "frontend_build_command"),
    _Key(("frontend", "output_dir"), "frontend_output_dir"),
    _Key(("frontend", "env_file"), "frontend_env_filename"),
    _Key(("frontend", "env"), "frontend_env_content", "env"),
    _Key(("docker", "enabled"), "docker_enabled"),
    _Key(("docker", "image_name"), "docker_image_name"),
    _Key(("docker", "base_image"), "docker_base_image"),
    _Key(("docker", "port"), "docker_expose_port"),
    _Key(("docker", "env"), "docker_env_vars", "env"),
    _Key(("docker", "commands"), "docker_custom_commands", "lines"),
    _Key(("docker", "install_node"), "docker_install_node"),
    _Key(("docker", "api_proxy"), "docker_api_proxy"),
    _Key(("docker", "volumes"), "docker_volumes", "csv"),
    _Key(("docker", "run_as_root"), "docker_run_as_root"),
    _Key(("docker", "nginx", "client_max_body_size"), "nginx_client_max_body_size"),
    _Key(("docker", "nginx", "proxy_read_timeout"), "nginx_proxy_read_timeout"),
    _Key(("docker", "nginx", "streaming"), "nginx_streaming"),
    _Key(("docker", "nginx", "gzip"), "nginx_gzip"),
    _Key(("smoke", "enabled"), "verify_after_build"),
)
KEY_FOR_FIELD: dict[str, str] = {k.field: ".".join(k.path) for k in KEYS}

# BuildConfig fields the file can never set: where the source comes from is what
# the file is read from.
NOT_IN_FILE = frozenset({"source_type", "git_url", "git_ref", "git_ref_type", "project_path"})


# ---------------------------------------------------------------------------
# What does not belong in a repository.

# Key names refused anywhere in the file, with why. Matched case-insensitively,
# with '-' read as '_'.
_SOURCE = "where the source comes from is set in Packwright: the file is read from that source"
_SERVER = "the build's user, isolation and environment are the server's to decide (BUILD_ENV_PASSTHROUGH)"
_CONSOLE = "notifications, webhooks, schedules and Git credentials are set in Packwright, not in the repository"
_FORBIDDEN: dict[str, str] = {
    **dict.fromkeys(("source", "source_type", "git", "git_url", "git_ref", "git_ref_type", "project_path", "repository"),
                    _SOURCE),
    **dict.fromkeys(("user", "build_user", "run_as", "uid", "isolation", "sandbox", "env_passthrough",
                     "build_env_passthrough", "passthrough"), _SERVER),
    **dict.fromkeys(("notifications", "notification", "notify", "webhooks", "webhook", "hooks", "hook",
                     "schedules", "schedule", "git_credentials", "credentials"), _CONSOLE),
}

# A key name that says it holds a secret: one of these words as a part of the
# name (API_KEY, db-password, accessToken), split at '_', '-' and '.'.
_SECRET_PARTS = frozenset({"pwd", "pass", "passphrase", "key", "keys", "pat", "salt", "dsn", "cookie", "cookies"})
_SECRET_SUBSTRING_RE = re.compile(
    r"passw|secret|token(?!iz)|credential|api_?key|private_?key|access_?key|signing_?key|encryption_?key", re.I
)


def secret_name(name: str) -> bool:
    """True when a key or variable name says it holds a secret.

    TOKENIZERS_PARALLELISM is not one (a common Hugging Face setting).
    """
    parts = re.split(r"[_.\-]+", name.lower())
    return bool(_SECRET_SUBSTRING_RE.search(name)) or any(p in _SECRET_PARTS for p in parts)


# Values shaped like a credential, whatever the key is called.
_SECRET_PREFIX_RE = re.compile(
    r"(?:ghp_|gho_|ghs_|ghu_|ghr_|github_pat_|glpat-|gldt-|xox[abposr]-|sk-|sk_live_|rk_live_|pk_live_"
    r"|AKIA[0-9A-Z]{12}|ASIA[0-9A-Z]{12}|AIza[0-9A-Za-z_-]{20}|pwt_|hf_[A-Za-z]{20}|npm_[A-Za-z0-9]{20})"
)
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.")
_URL_PASSWORD_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.I)
_HEX_RE = re.compile(r"[0-9a-fA-F]{32,}")
_TOKEN_CHARS_RE = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(c / len(value) * math.log2(c / len(value)) for c in counts.values())


def looks_secret(value: str) -> str | None:
    """Why ``value`` looks like a credential, or None.

    The line: a URL with a password in it; a private key block; a JSON Web Token;
    the prefixes of well-known tokens (GitHub, GitLab, Slack, AWS, Google, OpenAI,
    Stripe, Hugging Face, npm, Packwright); 32 or more hex digits; or 32 or more
    token characters with no spaces that mix upper case, lower case and digits
    at high entropy (a generated key). Ordinary settings (URLs without a
    password, paths, image names, words, numbers) pass.
    """
    v = value.strip()
    if "-----BEGIN" in v:
        return "a private key"
    if _URL_PASSWORD_RE.search(v):
        return "a URL with a password in it"
    if _JWT_RE.search(v):
        return "a JSON Web Token"
    if _SECRET_PREFIX_RE.search(v):
        return "an access token"
    for word in re.split(r"\s+", v):
        if _HEX_RE.fullmatch(word):
            return "a long hex string (a key or hash)"
        if (_TOKEN_CHARS_RE.fullmatch(word) and re.search(r"[A-Z]", word) and re.search(r"[a-z]", word)
                and re.search(r"[0-9]", word) and _entropy(word) >= 4.0):
            return "a generated key"
    return None


# ---------------------------------------------------------------------------
# Errors.

@dataclass
class Issue:
    """One thing wrong with the file: where, and what."""

    key: str | None
    line: int | None
    message: str

    def __str__(self) -> str:
        where = f"{FILE_NAME}:{self.line}" if self.line else FILE_NAME
        return f"{where}: {self.key}: {self.message}" if self.key else f"{where}: {self.message}"


class ConfigFileError(Exception):
    """packwright.toml cannot be used; the build fails at the Config stage."""

    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("; ".join(str(i) for i in issues))


# ---------------------------------------------------------------------------
# Where each key is. tomllib gives values only, so the lines are found by reading
# the file the simple way TOML is written: [table] headers, key = value lines,
# and the keys of an inline { ... } table on the line it sits.

_HEADER_RE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$")
_KEY_RE = re.compile(r"""^\s*((?:[A-Za-z0-9_-]+|"[^"]*"|'[^']*')(?:\s*\.\s*(?:[A-Za-z0-9_-]+|"[^"]*"|'[^']*'))*)\s*=""")
_INLINE_KEY_RE = re.compile(r"""[{,]\s*([A-Za-z0-9_-]+|"[^"]*"|'[^']*')\s*=""")


def _split_key(raw: str) -> tuple[str, ...]:
    parts = re.findall(r"""[A-Za-z0-9_-]+|"[^"]*"|'[^']*'""", raw)
    return tuple(p[1:-1] if p[:1] in "\"'" else p for p in parts)


def locate(text: str) -> dict[tuple[str, ...], int]:
    """Key path -> the 1-based line it is set on."""
    lines: dict[tuple[str, ...], int] = {}
    table: tuple[str, ...] = ()
    in_multiline: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if in_multiline:
            if in_multiline in line:
                in_multiline = None
            continue
        header = _HEADER_RE.match(line)
        if header:
            table = _split_key(header.group(1))
            lines.setdefault(table, number)
            continue
        key = _KEY_RE.match(line)
        if not key:
            continue
        path = table + _split_key(key.group(1))
        lines.setdefault(path, number)
        rest = line[key.end():]
        for quote in ('"""', "'''"):
            if rest.count(quote) == 1:
                in_multiline = quote
        brace = rest.find("{")
        if brace >= 0:
            for inner in _INLINE_KEY_RE.finditer(rest[brace:]):
                lines.setdefault(path + _split_key(inner.group(1)), number)
    return lines


def _line_for(lines: dict[tuple[str, ...], int], path: Iterable[Any]) -> int | None:
    """The line of ``path``, or of the nearest enclosing key that has one."""
    parts = tuple(str(p) for p in path if not isinstance(p, int))
    while parts:
        if parts in lines:
            return lines[parts]
        parts = parts[:-1]
    return None


def _dotted(path: Iterable[Any]) -> str:
    out = ""
    for p in path:
        if isinstance(p, int):
            out += f"[{p}]"
        else:
            name = str(p)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                name = f'"{name}"'
            out += f".{name}" if out else name
    return out


# ---------------------------------------------------------------------------
# Reading the file.

@dataclass
class FileSettings:
    """What a valid packwright.toml sets, as BuildConfig fields."""

    values: dict[str, Any]
    # field -> {"key": "python.entry", "line": 7, "text": 'entry = "app.py"'}
    keys: dict[str, dict] = field(default_factory=dict)


def _walk(node: Any, path: tuple) -> Iterable[tuple[tuple, Any, bool]]:
    """(path, value, is_key) for every key and every string value in the document."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield path + (k,), None, True
            yield from _walk(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, path + (i,))
    elif isinstance(node, str):
        yield path, node, False


def _refused(doc: dict, lines: dict) -> list[Issue]:
    """Keys and values that do not belong in a repository, wherever they are."""
    issues: list[Issue] = []
    for path, value, is_key in _walk(doc, ()):
        line = _line_for(lines, path)
        if is_key:
            name = str(path[-1]).lower().replace("-", "_")
            if name in _FORBIDDEN:
                issues.append(Issue(_dotted(path), line, f"not allowed in {FILE_NAME}: {_FORBIDDEN[name]}"))
            elif path[:2] == ("project", "name") and len(path) == 2:
                issues.append(Issue(_dotted(path), line,
                                    "not allowed: the project's name is set in Packwright"))
            elif secret_name(name):
                issues.append(Issue(_dotted(path), line,
                                    "not allowed: the name says it holds a secret. Secrets never go in the "
                                    "repository; set them in Packwright's project settings"))
            continue
        why = looks_secret(value)
        if why:
            issues.append(Issue(_dotted(path), line,
                                f"not allowed: the value looks like {why}. Secrets never go in the "
                                "repository; set them in Packwright's project settings"))
    return issues


def _type_message(err: dict) -> str:
    if err["type"] == "extra_forbidden":
        return "unknown key (check the spelling; see the documented keys)"
    if err["type"] == "missing":
        return "required"
    msg = err["msg"]
    got = type(err.get("input")).__name__ if "input" in err else None
    names = {"str": "a string", "int": "an integer", "bool": "true or false", "list": "a list",
             "dict": "a table", "float": "a number"}
    if got in names and err["type"].endswith("_type"):
        return f"{msg} (got {names[got]})"
    return msg


def _env_lines(path: tuple, env: dict[str, str], lines: dict) -> tuple[str, list[Issue]]:
    out, issues = [], []
    for name, value in env.items():
        where = path + (name,)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            issues.append(Issue(_dotted(where), _line_for(lines, where),
                                "a variable name uses letters, digits and '_' and does not start with a digit"))
        elif "\n" in value or "\r" in value:
            issues.append(Issue(_dotted(where), _line_for(lines, where), "the value must be one line"))
        else:
            out.append(f"{name}={value}")
    return "\n".join(out), issues


def _to_field(key: _Key, value: Any, lines: dict) -> tuple[Any, list[Issue]]:
    where = key.path
    if key.kind == "csv":
        bad = [i for i, v in enumerate(value) if "," in v or "\n" in v or not v.strip()]
        if bad:
            return None, [Issue(_dotted(where + (bad[0],)), _line_for(lines, where),
                                "an entry must be a non-empty name without ',' or a line break")]
        return ", ".join(v.strip() for v in value), []
    if key.kind == "lines":
        bad = [i for i, v in enumerate(value) if "\n" in v or "\r" in v or not v.strip()]
        if bad:
            return None, [Issue(_dotted(where + (bad[0],)), _line_for(lines, where),
                                "each command is one non-empty line")]
        return "\n".join(v.strip() for v in value), []
    if key.kind == "env":
        return _env_lines(where, value, lines)
    return value, []


def _dig(doc: dict, path: tuple[str, ...]) -> tuple[bool, Any]:
    node: Any = doc
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def parse(text: str) -> FileSettings:
    """Read packwright.toml's text; raise ConfigFileError naming every problem."""
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise ConfigFileError([Issue(None, None, f"the file is larger than {MAX_BYTES // 1024} KiB")])
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        m = re.search(r"\(at line (\d+), column (\d+)\)", str(exc))
        line = int(m.group(1)) if m else getattr(exc, "lineno", None)
        message = re.sub(r"\s*\(at line \d+, column \d+\)", "", str(exc))
        raise ConfigFileError([Issue(None, line, f"not valid TOML: {message}")]) from None
    lines = locate(text)

    issues = _refused(doc, lines)
    if issues:
        raise ConfigFileError(issues)

    version = doc.get("schema")
    if version is None:
        raise ConfigFileError([Issue("schema", None, f"required: start the file with 'schema = {SCHEMA_VERSION}'")])
    if version != SCHEMA_VERSION or isinstance(version, bool):
        raise ConfigFileError([Issue(
            "schema", _line_for(lines, ("schema",)),
            f"this Packwright reads schema {SCHEMA_VERSION}, the file says {version!r}: upgrade Packwright, "
            f"or write schema = {SCHEMA_VERSION}",
        )])

    try:
        PackwrightFile.model_validate(doc)
    except ValidationError as exc:
        raise ConfigFileError([
            Issue(_dotted(e["loc"]), _line_for(lines, e["loc"]), _type_message(e))
            for e in exc.errors(include_url=False)
        ]) from None

    text_lines = text.splitlines()
    values: dict[str, Any] = {}
    keys: dict[str, dict] = {}
    for key in KEYS:
        present, value = _dig(doc, key.path)
        if not present:
            continue
        converted, problems = _to_field(key, value, lines)
        issues.extend(problems)
        if problems:
            continue
        values[key.field] = converted
        line = _line_for(lines, key.path)
        keys[key.field] = {
            "key": ".".join(key.path),
            "line": line,
            "text": text_lines[line - 1].strip()[:200] if line else "",
        }
    if issues:
        raise ConfigFileError(issues)
    return FileSettings(values=values, keys=keys)


def read(root: Path) -> FileSettings | None:
    """The packwright.toml at the root of ``root``; None when there is none.

    A symlink is refused, as for env files read out of a repository
    (git_service._repo_file): the file must be the repository's own.
    """
    path = Path(root) / FILE_NAME
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise ConfigFileError([Issue(None, None, "must be a regular file in the project, not a link or a folder")])
    try:
        text = path.read_bytes()[: MAX_BYTES + 1].decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigFileError([Issue(None, None, "is not UTF-8 text")]) from None
    return parse(text)


# ---------------------------------------------------------------------------
# Applying the file to a build.

_PATH_FIELDS = ("output_dir", "extra_dirs", "data_dirs", "frontend_dir", "entry_point")


def _inside(root: Path, name: str) -> bool:
    from app.services.paths import is_safe_relative

    name = (name or "").strip()
    if not name:
        return True
    if not is_safe_relative(name):
        return False
    base = root.resolve()
    return (base / name).resolve().is_relative_to(base)


# Checks BuildConfig makes across fields (model validators report no field):
# which settings each one is about, the first named the most likely culprit.
_ACROSS_FIELDS = (("frontend output directory", ("frontend_output_dir", "frontend_dir")),)


def _issue_for(settings: FileSettings, field_name: str, message: str) -> Issue:
    names = [field_name] if field_name else []
    if not field_name:
        for words, related in _ACROSS_FIELDS:
            if words in message.lower():
                names = [n for n in related if n in settings.keys]
    for name in names:
        where = settings.keys.get(name)
        if where:
            return Issue(where["key"], where["line"], message)
    return Issue(None, None, f"{field_name}: {message}" if field_name else message)


def apply(config: BuildConfig, settings: FileSettings, root: Path) -> BuildConfig:
    """``config`` with the file's values on top, checked as the console checks a
    build, plus: every path the file sets stays inside ``root`` (symlinks
    followed). Raises ConfigFileError naming the key and line."""
    merged = {**config.model_dump(), **settings.values}
    try:
        effective = BuildConfig.model_validate(merged)
    except ValidationError as exc:
        issues = []
        for e in exc.errors(include_url=False, include_context=False):
            name = str(e["loc"][0]) if e["loc"] else ""
            issues.append(_issue_for(settings, name, e["msg"].removeprefix("Value error, ")))
        raise ConfigFileError(issues) from None

    root = Path(root)
    issues = []
    for name in _PATH_FIELDS:
        if name not in settings.values:
            continue
        for part in str(settings.values[name]).split(","):
            if not _inside(root, part):
                issues.append(_issue_for(settings, name,
                                         f"'{part.strip()}' points outside the project: paths are relative to "
                                         "the project, without '..', absolute paths or links that leave it"))
    if "frontend_output_dir" in settings.values or "frontend_dir" in settings.values:
        combined = f"{effective.frontend_dir or '.'}/{effective.frontend_output_dir or ''}"
        if not _inside(root, combined):
            issues.append(_issue_for(settings, "frontend_output_dir",
                                     f"'{effective.frontend_output_dir}' points outside the project"))
    if issues:
        raise ConfigFileError(issues)

    from fastapi import HTTPException

    from app.api.routes.tasks import _validate_build_config_paths

    try:
        _validate_build_config_paths(effective)
    except HTTPException as exc:
        raise ConfigFileError([Issue(None, None, str(exc.detail))]) from None
    return effective


# ---------------------------------------------------------------------------
# Where each value came from.

def base_origins(
    config: BuildConfig,
    stored: dict | None,
    *,
    overrides: Iterable[str] | None = None,
    detected: Iterable[str] = (),
) -> dict[str, str]:
    """Every field's origin before the file is read.

    ``overrides`` names the fields this build changed (a project build, a hook or
    schedule's branch); without it, a field is this build's own change when it
    differs from the project's saved ``stored`` settings. ``stored`` is None for
    the build that creates the project. ``detected`` names the fields the console
    filled in by looking at the source; they are "detected" unless they equal what
    the project already had.
    """
    dump = config.model_dump(mode="json")
    defaults = BuildConfig.model_construct().model_dump(mode="json")
    changed = set(overrides) if overrides is not None else None
    detected = set(detected)
    origins: dict[str, str] = {}
    for name in BuildConfig.model_fields:
        if name in _PER_BUILD:
            origin = "override" if dump.get(name) else "project"
        elif changed is not None:
            origin = "override" if name in changed else "project"
        elif stored is None:
            origin = "project"
        else:
            origin = "override" if stored.get(name, defaults.get(name)) != dump.get(name) else "project"
        if name in detected and (stored is None or stored.get(name, defaults.get(name)) != dump.get(name)):
            origin = "detected"
        origins[name] = origin
    return origins


def record(
    origins: dict[str, str] | None,
    submitted: BuildConfig,
    effective: BuildConfig,
    settings: FileSettings | None,
) -> dict:
    """What history.effective_config keeps for a build once its Config stage ran.

    ``config`` is what was built; ``origins`` where each field came from; ``file``
    the keys the file set (key, line, text, value) and, for a field this build had
    changed itself, the value the file replaced.
    """
    origins = dict(origins or {n: "project" for n in BuildConfig.model_fields})
    file_part = None
    if settings is not None:
        submitted_dump = submitted.model_dump(mode="json")
        effective_dump = effective.model_dump(mode="json")
        fields: dict[str, dict] = {}
        for name, where in settings.keys.items():
            entry = {**where, "value": effective_dump.get(name)}
            before = origins.get(name, "project")
            if submitted_dump.get(name) != effective_dump.get(name):
                entry["replaced"] = {"origin": before, "value": submitted_dump.get(name)}
            fields[name] = entry
            origins[name] = "file"
        file_part = {"path": FILE_NAME, "fields": fields}
    return {"config": effective.model_dump(mode="json"), "origins": origins, "file": file_part}


def built_config(effective_record: dict | None, submitted: dict | None) -> dict | None:
    """The settings a build was made with: the effective ones once its Config stage
    ran, the submitted ones before (and for builds older than packwright.toml)."""
    if effective_record and isinstance(effective_record.get("config"), dict):
        return effective_record["config"]
    return submitted


def file_values(effective_record: dict | None) -> dict[str, Any] | None:
    """The values a build took from its packwright.toml; None when it never read one
    (it had none, or its Config stage did not run)."""
    if not effective_record or "config" not in effective_record:
        return None
    part = effective_record.get("file")
    if not part:
        return {}
    return {name: entry.get("value") for name, entry in (part.get("fields") or {}).items()}


def preview(text: str | None) -> dict | None:
    """What New build shows about a source's packwright.toml: the values it sets
    (with key and line), or what is wrong with it. None when there is none."""
    if text is None:
        return None
    try:
        settings = parse(text)
    except ConfigFileError as exc:
        return {"values": {}, "keys": {}, "errors": [str(i) for i in exc.issues]}
    return {"values": settings.values, "keys": settings.keys, "errors": []}


def preview_dir(root: Path) -> dict | None:
    """preview() of the packwright.toml in a local folder, never raising."""
    path = Path(root) / FILE_NAME
    if not path.exists() and not path.is_symlink():
        return None
    try:
        read(root)
    except ConfigFileError as exc:
        return {"values": {}, "keys": {}, "errors": [str(i) for i in exc.issues]}
    except OSError as exc:
        return {"values": {}, "keys": {}, "errors": [f"{FILE_NAME}: could not be read ({exc.strerror})"]}
    return preview(path.read_text(encoding="utf-8"))
