"""
packwright.toml: reading it, refusing what does not belong in a repository, putting
its values over a build's settings, and recording where each value came from.
Source: app/services/packwright_toml.py, app/services/build_dispatcher.py (_config_stage,
        _fail_config, _prepare_git_workspace), docs/packwright.schema.json
"""

import json
import os
from pathlib import Path

import pytest

from app.schemas.task import BuildConfig
from app.services import packwright_toml as pt

ROOT = Path(__file__).resolve().parents[3]

FULL = '''#:schema https://example.invalid/packwright.schema.json
schema = 1

[project]
type = "fullstack"
version = "1.2.0"
output_dir = "out"

[python]
version = "3.13"
entry = "src/app.py"
output_name = "app"
onefile = false
pack_mode = "full"
source_dirs = ["src", "lib"]
data_dirs = ["static"]
include_packages = ["uvicorn"]
dependency_groups = ["server"]

[python.nuitka]
jobs = 4
anti_bloat = false
include_package_data = ["certifi"]
report = true

[frontend]
dir = "web"
tool = "pnpm"
build_command = "build:prod"
output_dir = "../static/web"
env_file = ".env.production"
env = { VITE_API = "/api", VITE_TITLE = "Shop" }

[docker]
enabled = true
image_name = "shop"
base_image = "python:3.13-slim"
port = 8080
env = { LOG_LEVEL = "info" }
commands = ["apt-get update", "apt-get install -y curl"]
install_node = true
api_proxy = "http://backend:8000"
volumes = ["data", "logs"]
run_as_root = false

[docker.nginx]
client_max_body_size = "50m"
proxy_read_timeout = "600s"
streaming = false
gzip = false

[smoke]
enabled = false
'''


def _issues(text: str) -> list[pt.Issue]:
    with pytest.raises(pt.ConfigFileError) as exc:
        pt.parse(text)
    return exc.value.issues


def _local(root: Path, **extra) -> BuildConfig:
    return BuildConfig(source_type="local", project_path=str(root), **extra)


@pytest.fixture
def allowed_root(tmp_path, mocker):
    """tmp_path is an allowed local source root."""
    from app.api.routes import tasks

    mocker.patch.object(tasks, "_allowed_path_prefixes", return_value=(str(tmp_path),))
    root = tmp_path / "proj"
    root.mkdir()
    return root


@pytest.mark.unit
def test_tc_pwt_001_every_key_lands_in_its_setting():
    """TC-PWT-001: a file with every key sets every mapped setting, lists joined the way
    the console stores them, and records each key with its line."""
    s = pt.parse(FULL)
    assert set(s.values) == {k.field for k in pt.KEYS}
    v = s.values
    assert v["project_type"] == "fullstack" and v["entry_point"] == "src/app.py" and v["onefile"] is False
    assert v["extra_dirs"] == "src, lib" and v["data_dirs"] == "static" and v["dependency_groups"] == ["server"]
    assert v["nuitka_jobs"] == 4 and v["generate_report"] is True and v["enable_anti_bloat"] is False
    assert v["frontend_env_content"] == "VITE_API=/api\nVITE_TITLE=Shop"
    assert v["docker_env_vars"] == "LOG_LEVEL=info"
    assert v["docker_custom_commands"] == "apt-get update\napt-get install -y curl"
    assert v["docker_volumes"] == "data, logs" and v["verify_after_build"] is False
    assert v["nginx_streaming"] is False and v["docker_expose_port"] == 8080
    lines = FULL.splitlines()
    for name, where in s.keys.items():
        assert where["key"] == pt.KEY_FOR_FIELD[name]
        assert where["key"].split(".")[-1] in lines[where["line"] - 1] or where["line"] and "=" in where["text"]
    assert s.keys["entry_point"] == {"key": "python.entry", "line": 11, "text": 'entry = "src/app.py"'}
    assert s.keys["frontend_env_content"]["line"] == 32
    # Every key maps to a real setting, and none can name where the source comes from.
    assert {k.field for k in pt.KEYS} <= set(BuildConfig.model_fields)
    assert not {k.field for k in pt.KEYS} & pt.NOT_IN_FILE


@pytest.mark.unit
def test_tc_pwt_002_unknown_keys_fail_with_key_and_line():
    """TC-PWT-002: a misspelt key, an unknown table and an unknown nested key each fail
    naming the key path and its line."""
    [issue] = _issues('schema = 1\n\n[python]\nentry = "a.py"\nentyr = "b.py"\n')
    assert issue.key == "python.entyr" and issue.line == 5 and "unknown key" in issue.message
    assert str(issue).startswith("packwright.toml:5: python.entyr:")
    [issue] = _issues('schema = 1\n[pyhton]\nentry = "a.py"\n')
    assert issue.key == "pyhton" and issue.line == 2
    [issue] = _issues('schema = 1\n[docker]\nnginx = { gzipp = true }\n')
    assert issue.key == "docker.nginx.gzipp" and issue.line == 3


@pytest.mark.unit
@pytest.mark.parametrize("body,key,line,fragment", [
    ('[docker]\nport = "8080"\n', "docker.port", 3, "valid integer"),
    ('[python]\nonefile = "yes"\n', "python.onefile", 3, "valid boolean"),
    ('[python]\nsource_dirs = "src"\n', "python.source_dirs", 3, "valid list"),
    ('[project]\ntype = "backend"\n', "project.type", 3, "backend_only"),
    ('[docker]\nport = 70000\n', "docker.port", 3, "65535"),
    ('[python.nuitka]\njobs = -1\n', "python.nuitka.jobs", 3, "greater than or equal"),
    ('[frontend]\nenv = { A = 1 }\n', "frontend.env.A", 3, "valid string"),
])
def test_tc_pwt_003_wrong_types_fail_with_key_and_line(body, key, line, fragment):
    """TC-PWT-003: a value of the wrong type or outside its range fails naming key and line;
    nothing is coerced ("yes" is not true, "8080" is not a port)."""
    [issue] = _issues("schema = 1\n" + body)
    assert issue.key == key and issue.line == line and fragment in issue.message, issue


@pytest.mark.unit
def test_tc_pwt_004_the_schema_version_is_required_and_checked():
    """TC-PWT-004: no schema, schema 2 and schema = true fail with an upgrade message; schema 1 reads."""
    [issue] = _issues('[python]\nentry = "a.py"\n')
    assert issue.key == "schema" and "schema = 1" in issue.message
    [issue] = _issues('# hi\nschema = 2\n')
    assert issue.key == "schema" and issue.line == 2 and "upgrade Packwright" in issue.message
    [issue] = _issues("schema = true\n")
    assert issue.key == "schema"
    assert pt.parse("schema = 1\n").values == {}


@pytest.mark.unit
@pytest.mark.parametrize("text,key", [
    ('schema = 1\npassword = "x"\n', "password"),
    ('schema = 1\n[docker.env]\nDB_PASSWORD = "x"\n', "docker.env.DB_PASSWORD"),
    ('schema = 1\n[frontend]\nenv = { VITE_API_KEY = "x" }\n', "frontend.env.VITE_API_KEY"),
    ('schema = 1\n[docker]\nenv = { accessToken = "x" }\n', "docker.env.accessToken"),
    ('schema = 1\n[docker]\nenv = { SECRET = "x" }\n', "docker.env.SECRET"),
    ('schema = 1\n[git]\nurl = "https://example.com/a.git"\n', "git"),
    ('schema = 1\n[project]\ngit_url = "https://example.com/a.git"\n', "project.git_url"),
    ('schema = 1\n[project]\nname = "other"\n', "project.name"),
    ('schema = 1\n[notifications]\nurl = "https://example.com"\n', "notifications"),
    ('schema = 1\n[webhooks]\nx = 1\n', "webhooks"),
    ('schema = 1\n[schedules]\ncron = "* * * * *"\n', "schedules"),
    ('schema = 1\n[build]\nuser = "root"\n', "build.user"),
    ('schema = 1\nbuild_env_passthrough = ["HOME"]\n', "build_env_passthrough"),
    ('schema = 1\n[git_credentials]\nhost = "x"\n', "git_credentials"),
    ('schema = 1\n[build]\nisolation = "none"\n', "build.isolation"),
])
def test_tc_pwt_005_keys_that_do_not_belong_in_a_repository_are_refused(text, key):
    """TC-PWT-005: secret-named keys (anywhere, env variable names included), the source,
    the project's name, notification/webhook/schedule/credential settings and the build's
    user, isolation and env passthrough are refused by name, with the line."""
    issues = _issues(text)
    assert issues[0].key == key and issues[0].line and "not allowed" in issues[0].message, issues


@pytest.mark.unit
@pytest.mark.parametrize("value,why", [
    ("postgres://app:hunter2@db:5432/app", "password"),
    ("ghp_" + "a1B2" * 9, "token"),
    ("glpat-" + "x" * 20, "token"),
    ("sk-" + "abc123" * 6, "token"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln", "Web Token"),
    ("-----BEGIN PRIVATE KEY-----", "private key"),
    ("0123456789abcdef0123456789abcdef01234567", "hex"),
    ("q8Zr2LkP0vXy7TbN3mWc5HdJ1sFg9QaE", "generated key"),
    ("pwt_" + "Ab1" * 12, "token"),
])
def test_tc_pwt_006_values_shaped_like_secrets_are_refused(value, why):
    """TC-PWT-006: whatever a variable is called, a URL with a password, known token
    prefixes, a JWT, a private key, 32+ hex digits or a high-entropy generated key is refused."""
    [issue] = _issues(f'schema = 1\n[docker]\nenv = {{ SETTING = "{value}" }}\n')
    assert issue.key == "docker.env.SETTING" and issue.line == 3 and why in issue.message
    # The same in any other string, not only env.
    assert _issues(f'schema = 1\n[docker]\napi_proxy = "{value}"\n')[0].key == "docker.api_proxy"


@pytest.mark.unit
@pytest.mark.parametrize("value", [
    "info", "https://api.example.com/v1", "/var/lib/app/data", "python:3.13-slim", "false", "8080",
    "en_US.UTF-8", "--workers 4 --log-level debug", "postgres://db:5432/app", "Hello World 123",
])
def test_tc_pwt_007_ordinary_values_and_names_pass(value):
    """TC-PWT-007: non-secret env variables are allowed: plain words, URLs without a
    password, paths, image names, flags; and TOKENIZERS_PARALLELISM is not a token."""
    s = pt.parse(f'schema = 1\n[docker]\nenv = {{ SETTING = "{value}", TOKENIZERS_PARALLELISM = "false" }}\n')
    assert s.values["docker_env_vars"] == f"SETTING={value}\nTOKENIZERS_PARALLELISM=false"


@pytest.mark.unit
def test_tc_pwt_008_toml_syntax_errors_name_the_line():
    """TC-PWT-008: a file that is not TOML fails with the line tomllib reports."""
    [issue] = _issues('schema = 1\n\n[python\nentry = "a"\n')
    assert issue.line == 3 and "not valid TOML" in issue.message
    [issue] = _issues('schema = 1\nentry = "unterminated\n')
    assert issue.line == 2


@pytest.mark.unit
def test_tc_pwt_009_lines_are_found_for_headers_dotted_and_inline_keys():
    """TC-PWT-009: the line finder knows [a.b] headers, dotted keys, inline tables, quoted
    keys, and skips the inside of multi-line strings."""
    text = (
        'schema = 1\n'                            # 1
        '[python]\n'                              # 2
        'nuitka.jobs = 2\n'                       # 3
        'entry = """\n'                           # 4
        'fake = 1\n'                              # 5 (inside a string)
        '"""\n'                                   # 6
        '[docker]\n'                              # 7
        'env = { "A B" = "1", C = "2" }\n'        # 8
        '  [docker.nginx]  # comment\n'           # 9
        'gzip = true\n'                           # 10
    )
    lines = pt.locate(text)
    assert lines[("schema",)] == 1 and lines[("python", "nuitka", "jobs")] == 3
    assert lines[("python", "entry")] == 4 and ("python", "fake") not in lines
    assert lines[("docker", "env", "A B")] == 8 and lines[("docker", "env", "C")] == 8
    assert lines[("docker", "nginx")] == 9 and lines[("docker", "nginx", "gzip")] == 10


@pytest.mark.unit
def test_tc_pwt_010_the_file_wins_and_the_result_is_checked_like_the_console(allowed_root):
    """TC-PWT-010: apply() puts the file's values over the build's settings (the file wins
    over everything the build had), and a value the console would refuse is refused with
    the key and line (a build command with shell syntax, a bad version)."""
    (allowed_root / "src").mkdir()
    (allowed_root / "src" / "app.py").write_text("print(1)\n")
    config = _local(allowed_root, entry_point="main.py", nuitka_jobs=8, generate_report=False)
    s = pt.parse('schema = 1\n[python]\nentry = "src/app.py"\n[python.nuitka]\njobs = 2\n')
    effective = pt.apply(config, s, allowed_root)
    assert effective.entry_point == "src/app.py" and effective.nuitka_jobs == 2
    assert effective.generate_report is False and effective.project_path == str(allowed_root)

    with pytest.raises(pt.ConfigFileError) as exc:
        pt.apply(config, pt.parse('schema = 1\n\n[frontend]\nbuild_command = "build; curl x | sh"\n'), allowed_root)
    [issue] = exc.value.issues
    assert issue.key == "frontend.build_command" and issue.line == 4 and "script name" in issue.message
    with pytest.raises(pt.ConfigFileError) as exc:
        pt.apply(config, pt.parse('schema = 1\n[project]\nversion = "../1"\n'), allowed_root)
    assert exc.value.issues[0].key == "project.version" and exc.value.issues[0].line == 3


@pytest.mark.unit
@pytest.mark.parametrize("body,key", [
    ('[python]\nentry = "../outside.py"\n', "python.entry"),
    ('[python]\nentry = "/etc/passwd"\n', "python.entry"),
    ('[python]\ndata_dirs = ["static", "../../etc"]\n', "python.data_dirs"),
    ('[python]\nsource_dirs = ["/srv"]\n', "python.source_dirs"),
    ('[project]\noutput_dir = "../out"\n', "project.output_dir"),
    ('[frontend]\ndir = "../web"\n', "frontend.dir"),
    ('[frontend]\noutput_dir = "../../../x"\n', "frontend.output_dir"),
    ('[python]\nentry = "link/app.py"\n', "python.entry"),
])
def test_tc_pwt_011_paths_must_stay_inside_the_project(allowed_root, tmp_path, body, key):
    """TC-PWT-011: a path the file sets that leaves the project (.., absolute, or through a
    link pointing outside) fails naming the key; a path inside passes."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "app.py").write_text("x")
    os.symlink(outside, allowed_root / "link")
    config = _local(allowed_root, project_type="fullstack")
    with pytest.raises(pt.ConfigFileError) as exc:
        pt.apply(config, pt.parse("schema = 1\n" + body), allowed_root)
    assert exc.value.issues[0].key == key and exc.value.issues[0].line == 3, exc.value.issues
    # A Git build's clone is checked on disk too: the console's own check of a Git
    # source is lexical only (the clone does not exist when the build is filed).
    git = BuildConfig(source_type="git", git_url="https://git.example.com/a.git", git_ref="main",
                      project_type="fullstack")
    with pytest.raises(pt.ConfigFileError) as exc:
        pt.apply(git, pt.parse("schema = 1\n" + body), allowed_root)
    assert exc.value.issues[0].key == key, exc.value.issues
    # Inside is fine, including a frontend output beside the backend.
    (allowed_root / "web").mkdir()
    ok = pt.parse('schema = 1\n[frontend]\ndir = "web"\noutput_dir = "../static/web"\n[python]\ndata_dirs = ["static"]\n')
    assert pt.apply(config, ok, allowed_root).frontend_output_dir == "../static/web"


@pytest.mark.unit
def test_tc_pwt_012_origins_before_the_file():
    """TC-PWT-012: a project build's named changes are overrides and the rest is the
    project's; without a list, what differs from the saved settings is an override; a
    first build is all the project's; detection is recorded where it set a new value;
    the version is per build."""
    stored = BuildConfig(entry_point="main.py", nuitka_jobs=0).model_dump(mode="json")
    config = BuildConfig(entry_point="app.py", nuitka_jobs=0, version="1.0")

    named = pt.base_origins(config, stored, overrides={"entry_point"})
    assert named["entry_point"] == "override" and named["nuitka_jobs"] == "project" and named["version"] == "override"
    compared = pt.base_origins(config, stored)
    assert compared["entry_point"] == "override" and compared["nuitka_jobs"] == "project"
    assert set(compared) == set(BuildConfig.model_fields)
    first = pt.base_origins(config, None, detected=["entry_point", "nuitka_jobs"])
    assert first["entry_point"] == "detected" and first["nuitka_jobs"] == "detected" and first["onefile"] == "project"
    again = pt.base_origins(config, stored, detected=["entry_point", "nuitka_jobs"])
    # Detected but equal to what the project has: the project's.
    assert again["entry_point"] == "detected" and again["nuitka_jobs"] == "project"
    assert pt.base_origins(BuildConfig(), stored)["version"] == "project"


@pytest.mark.unit
def test_tc_pwt_013_the_record_marks_file_values_and_what_they_replaced():
    """TC-PWT-013: record() keeps the effective settings, marks every file key as "file"
    (over an override too) with key, line and value, and keeps the replaced value and its
    origin; file_values/built_config read it back; without a file nothing is "file"."""
    submitted = BuildConfig(entry_point="mine.py", nuitka_jobs=3)
    origins = pt.base_origins(submitted, BuildConfig().model_dump(mode="json"), overrides={"entry_point"})
    s = pt.parse('schema = 1\n[python]\nentry = "app.py"\nnuitka = { jobs = 3 }\n')
    effective = submitted.model_copy(update=s.values)
    rec = pt.record(origins, submitted, effective, s)
    assert rec["config"]["entry_point"] == "app.py" and rec["origins"]["entry_point"] == "file"
    assert rec["origins"]["nuitka_jobs"] == "file" and rec["origins"]["onefile"] == "project"
    entry = rec["file"]["fields"]["entry_point"]
    assert entry["key"] == "python.entry" and entry["line"] == 3 and entry["value"] == "app.py"
    assert entry["replaced"] == {"origin": "override", "value": "mine.py"}
    assert "replaced" not in rec["file"]["fields"]["nuitka_jobs"]  # the same value
    assert pt.file_values(rec) == {"entry_point": "app.py", "nuitka_jobs": 3}
    assert pt.built_config(rec, {"entry_point": "mine.py"})["entry_point"] == "app.py"

    plain = pt.record(origins, submitted, submitted, None)
    assert plain["file"] is None and "file" not in plain["origins"].values() and pt.file_values(plain) == {}
    assert pt.file_values({"origins": {}}) is None and pt.file_values(None) is None
    assert pt.built_config({"origins": {}}, {"a": 1}) == {"a": 1}


@pytest.mark.unit
def test_tc_pwt_014_read_takes_only_the_repositorys_own_file(tmp_path):
    """TC-PWT-014: no file is None; a symlink, a folder, non-UTF-8 and an oversized file
    are refused; preview reports values or errors without raising."""
    assert pt.read(tmp_path) is None and pt.preview_dir(tmp_path) is None
    target = tmp_path / "real.toml"
    target.write_text("schema = 1\n")
    (tmp_path / pt.FILE_NAME).symlink_to(target)
    with pytest.raises(pt.ConfigFileError, match="not a link"):
        pt.read(tmp_path)
    assert pt.preview_dir(tmp_path)["errors"]
    (tmp_path / pt.FILE_NAME).unlink()
    (tmp_path / pt.FILE_NAME).write_bytes(b"schema = 1\n# \xff\n")
    with pytest.raises(pt.ConfigFileError, match="UTF-8"):
        pt.read(tmp_path)
    (tmp_path / pt.FILE_NAME).write_text("schema = 1\n#" + "x" * pt.MAX_BYTES + "\n")
    with pytest.raises(pt.ConfigFileError, match="larger"):
        pt.read(tmp_path)
    (tmp_path / pt.FILE_NAME).write_text('schema = 1\n[python]\nentry = "a.py"\n')
    assert pt.preview_dir(tmp_path) == {
        "values": {"entry_point": "a.py"},
        "keys": {"entry_point": {"key": "python.entry", "line": 3, "text": 'entry = "a.py"'}},
        "errors": [],
    }
    assert pt.preview("schema = 3\n")["errors"][0].startswith("packwright.toml:1: schema:")


@pytest.mark.unit
def test_tc_pwt_015_the_published_json_schema_is_the_models():
    """TC-PWT-015: docs/packwright.schema.json is what PackwrightFile generates (regenerate
    with scripts/gen_packwright_schema.py), and it forbids unknown keys at every level."""
    committed = json.loads((ROOT / "docs" / "packwright.schema.json").read_text())
    assert committed == pt.json_schema()
    assert committed["additionalProperties"] is False and committed["required"] == ["schema"]
    for name, sub in committed["$defs"].items():
        assert sub["additionalProperties"] is False, name


@pytest.mark.unit
def test_tc_pwt_016_list_entries_and_env_names_are_checked():
    """TC-PWT-016: a list entry with a comma or empty, a command spanning lines, an env name
    that is not a variable name and a value with a line break are refused with the key."""
    assert _issues('schema = 1\n[python]\ndata_dirs = ["a,b"]\n')[0].key == "python.data_dirs[0]"
    assert _issues('schema = 1\n[python]\nsource_dirs = [""]\n')[0].key == "python.source_dirs[0]"
    assert _issues('schema = 1\n[docker]\ncommands = ["ok", "two\\nlines"]\n')[0].key == "docker.commands[1]"
    assert _issues('schema = 1\n[docker]\nenv = { "1A" = "x" }\n')[0].key == "docker.env.1A"
    assert _issues('schema = 1\n[docker]\nenv = { "A-B" = "x" }\n')[0].key == "docker.env.A-B"
    assert _issues('schema = 1\n[docker]\nenv = { A = "x\\ny" }\n')[0].key == "docker.env.A"


# ---------- the Config stage in the build ----------


@pytest.fixture
def stage(mocker):
    """The task store as the Config stage uses it, recorded."""
    import contextlib
    from types import SimpleNamespace

    from app.schemas.task import TaskStatus
    from app.services import build_dispatcher

    tm = build_dispatcher.task_manager
    calls = SimpleNamespace(logs=[], effective=None, results={}, updates={})

    async def append_log(tid, line):
        calls.logs.append(line)

    async def set_effective(tid, record):
        calls.effective = record

    async def update_task(tid, key, value, db=None):
        calls.updates[key] = value

    async def merge_result(tid, patch, db=None):
        calls.results.update(patch)

    mocker.patch.object(tm, "append_log", side_effect=append_log)
    mocker.patch.object(tm, "set_effective", side_effect=set_effective)
    mocker.patch.object(tm, "update_task", side_effect=update_task)
    mocker.patch.object(tm, "merge_result", side_effect=merge_result)
    async def set_stage(tid, name):
        calls.updates["stage"] = name

    mocker.patch.object(tm, "set_stage", side_effect=set_stage)
    mocker.patch.object(tm, "get_logs", mocker.AsyncMock(return_value=[]))
    mocker.patch.object(tm, "get_task", mocker.AsyncMock(
        side_effect=lambda tid: SimpleNamespace(status=calls.updates.get("status", TaskStatus.RUNNING), result=None,
                                                stage=calls.updates.get("stage"))))
    calls.origins = None
    mocker.patch.object(tm, "origins_of", side_effect=lambda tid: calls.origins)

    @contextlib.asynccontextmanager
    async def session():
        yield mocker.MagicMock()

    mocker.patch("app.database.async_session", session)
    calls.dispatch = mocker.patch.object(build_dispatcher, "dispatch_build", mocker.AsyncMock())
    mocker.patch.object(build_dispatcher, "_record_duration", mocker.AsyncMock())
    calls.notify = mocker.patch.object(build_dispatcher.notifications, "notify_build_soon")
    return calls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_pwt_017_the_config_stage_applies_and_records_the_file(allowed_root, stage):
    """TC-PWT-017: _config_stage reads the folder's packwright.toml at stage "config",
    returns the settings with the file's values on top, records origins (the file over
    this build's own change) and logs which value the file replaced."""
    from app.services import build_dispatcher

    (allowed_root / "app.py").write_text("x")
    (allowed_root / pt.FILE_NAME).write_text('schema = 1\n[python]\nentry = "app.py"\n')
    config = _local(allowed_root, entry_point="mine.py")
    stage.origins = pt.base_origins(config, BuildConfig().model_dump(mode="json"), overrides={"entry_point"})

    effective = await build_dispatcher._config_stage("t", config, allowed_root)
    assert effective.entry_point == "app.py" and stage.updates["stage"] == "config"
    assert stage.effective["origins"]["entry_point"] == "file"
    assert stage.effective["file"]["fields"]["entry_point"]["replaced"] == {"origin": "override", "value": "mine.py"}
    assert any("python.entry = 'app.py' (line 3), instead of this build's 'mine.py'" in line for line in stage.logs)

    (allowed_root / pt.FILE_NAME).unlink()
    plain = await build_dispatcher._config_stage("t", config, allowed_root)
    assert plain == config and stage.effective["file"] is None and stage.effective["config"]["entry_point"] == "mine.py"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_pwt_018_a_bad_file_fails_the_build_at_the_config_stage(allowed_root, stage):
    """TC-PWT-018: start_build_task — an unusable packwright.toml fails the build before it
    is dispatched: status failed, failed_stage "config", the key and line in the diagnosis
    and error lines, and the outcome is announced."""
    from app.schemas.task import TaskStatus
    from app.services import build_dispatcher

    (allowed_root / pt.FILE_NAME).write_text('schema = 1\n\n[python]\nentyr = "app.py"\n')
    await build_dispatcher.start_build_task("t", _local(allowed_root))

    stage.dispatch.assert_not_awaited()
    assert stage.updates["status"] == TaskStatus.FAILED and stage.results["failed_stage"] == "config"
    assert stage.results["error_lines"] == ["packwright.toml:4: python.entyr: unknown key (check the spelling; "
                                            "see the documented keys)"]
    [diag] = stage.results["diagnosis"]
    assert "(line 4)" in diag["problem"] and "python.entyr" in diag["evidence"]
    assert "packwright.toml:4" in stage.updates["status_msg"]
    stage.notify.assert_called_once_with("t")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_pwt_019_git_builds_read_the_file_from_the_clone_before_the_venv(stage, mocker, tmp_path):
    """TC-PWT-019: _prepare_git_workspace reads packwright.toml from the commit it checked
    out, before the venv bootstrap, which gets the file's Python version and groups; the
    returned settings point at the clone; a bad file removes the clone and is reported at
    the Config stage."""
    from app.schemas.task import TaskStatus
    from app.services import build_dispatcher, git_service, workspace_cleanup

    mocker.patch.object(build_dispatcher.task_manager, "set_commit", mocker.AsyncMock())
    mocker.patch("app.services.git_credentials.resolve_for_url", mocker.AsyncMock(return_value=(None, "generic")))
    mocker.patch("app.config.get_settings", return_value=mocker.Mock(git_workspace_dir=str(tmp_path),
                                                                     git_clone_timeout=60))
    mocker.patch.object(git_service, "resolve_ref", mocker.AsyncMock(return_value="a" * 40))
    toml = {"text": 'schema = 1\n[python]\nversion = "3.14"\ndependency_groups = ["server"]\n'}

    async def clone(**kw):
        kw["target_dir"].mkdir(parents=True)
        (kw["target_dir"] / pt.FILE_NAME).write_text(toml["text"])
        return False

    mocker.patch.object(git_service, "clone_at_commit", side_effect=clone)
    venv = mocker.patch.object(build_dispatcher, "_prepare_venv", mocker.AsyncMock())
    dropped = mocker.patch.object(workspace_cleanup, "delete_one_workspace")
    config = BuildConfig(source_type="git", git_url="https://git.example.com/a.git", git_ref="main")

    effective = await build_dispatcher._prepare_git_workspace("t-g", config)
    seen = venv.await_args.args[2]
    assert seen.python_version == "3.14" and seen.dependency_groups == ["server"]
    assert effective.project_path == str(tmp_path / "t-g") and effective.python_version == "3.14"
    assert stage.effective["config"]["project_path"] == ""  # the record keeps the source, not the clone
    dropped.assert_not_called()

    toml["text"] = 'schema = 1\n[python]\nversion = 3.14\n'
    venv.reset_mock()
    await build_dispatcher.start_build_task("t-h", config)
    venv.assert_not_awaited()
    dropped.assert_called_once_with("t-h")
    assert stage.updates["status"] == TaskStatus.FAILED and stage.results["failed_stage"] == "config"
    assert stage.results["error_lines"][0].startswith("packwright.toml:3: python.version:")
