"""
Reading schedules: cron expressions, time zones, next run times (DST included) and
what "the same settings" means for skip-unchanged.
Source: app/services/schedules.py
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.schemas.task import BuildConfig
from app.services import schedules

UTC = timezone.utc


def _built(config, effective=None):
    """A history row as _same_settings reads it."""
    return SimpleNamespace(config=config, effective_config=effective)
NY = "America/New_York"


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [
    ("0 2 * * *", "0 2 * * *"),
    ("  */15   *  * * 1-5 ", "*/15 * * * 1-5"),
    ("0 9 * * MON-FRI", "0 9 * * MON-FRI"),
    ("@Daily", "@daily"),
    ("@hourly", "@hourly"),
])
def test_tc_sched_001_valid_expressions_are_tidied(raw, expected):
    """TC-SCHED-001: five fields (spacing collapsed) and the @aliases are accepted."""
    assert schedules.normalise_cron(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize("raw,fragment", [
    ("", "Enter a cron expression"),
    ("61 * * * *", "Invalid cron expression"),
    ("*/0 * * * *", "Invalid cron expression"),
    ("0 0 31 4 *", "Invalid cron expression"),
    ("0 0 * * * *", "has 6"),
    ("* * * *", "has 4"),
    ("@nightly", "Unknown shortcut"),
    ("0 " * 60, "too long"),
])
def test_tc_sched_002_invalid_expressions_say_why(raw, fragment):
    """TC-SCHED-002: a wrong field, a date that never comes, a seconds field, a missing
    field, an unknown shortcut and an overlong expression are refused with the reason."""
    with pytest.raises(schedules.ScheduleError, match=fragment):
        schedules.normalise_cron(raw)


@pytest.mark.unit
def test_tc_sched_003_time_zones_must_be_iana_names():
    """TC-SCHED-003: IANA names pass (trimmed); anything else, paths included, is refused."""
    assert schedules.valid_timezone(" Asia/Taipei ") == "Asia/Taipei"
    assert schedules.valid_timezone("UTC") == "UTC"
    for bad in ("", "Mars/Olympus", "../../etc/passwd", "asia/taipei", "+08:00"):
        with pytest.raises(schedules.ScheduleError, match="Unknown time zone"):
            schedules.valid_timezone(bad)


@pytest.mark.unit
def test_tc_sched_004_next_runs_are_read_in_the_schedules_zone():
    """TC-SCHED-004: "0 2 * * *" in Asia/Taipei is 18:00 UTC the day before; the next runs
    come strictly after the given time, in order, as UTC."""
    after = datetime(2026, 11, 22, 17, 0, tzinfo=UTC)
    runs = schedules.next_runs("0 2 * * *", "Asia/Taipei", after, 3)
    assert runs == [datetime(2026, 11, 22, 18, 0, tzinfo=UTC) + timedelta(days=i) for i in range(3)]
    assert all(r.tzinfo == UTC for r in runs)
    # Exactly on a slot: the next one, not the same one.
    assert schedules.next_run("* * * * *", "UTC", datetime(2026, 1, 1, 0, 0, tzinfo=UTC)) == datetime(
        2026, 1, 1, 0, 1, tzinfo=UTC)
    # A naive time is UTC (that is how SQLite hands stored times back).
    assert schedules.next_run("0 * * * *", "UTC", datetime(2026, 1, 1, 0, 30)) == datetime(2026, 1, 1, 1, 0, tzinfo=UTC)


@pytest.mark.unit
def test_tc_sched_005_spring_forward_runs_a_skipped_slot_once_at_the_jump():
    """TC-SCHED-005: in New York 02:00 jumps to 03:00 on 2026-03-08. A 02:30 job runs once
    that night at 03:00 EDT, then at 02:30 again from the next night."""
    tz = ZoneInfo(NY)
    runs = schedules.next_runs("30 2 * * *", NY, datetime(2026, 3, 7, 12, 0, tzinfo=tz), 3)
    local = [r.astimezone(tz) for r in runs]
    assert [(d.day, d.hour, d.minute) for d in local] == [(8, 3, 0), (9, 2, 30), (10, 2, 30)]


@pytest.mark.unit
def test_tc_sched_006_fall_back_runs_a_fixed_time_once_and_intervals_in_both_hours():
    """TC-SCHED-006: on 2026-11-01 New York repeats 01:00–02:00. A 01:30 job runs once (in the
    first, EDT, copy); a */30 job runs in both copies."""
    tz = ZoneInfo(NY)
    daily = schedules.next_runs("30 1 * * *", NY, datetime(2026, 10, 31, 12, 0, tzinfo=tz), 2)
    assert daily[1] - daily[0] == timedelta(hours=25)  # once on the long day, once the day after
    assert daily[0] == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # 01:30 EDT
    halves = schedules.next_runs("*/30 * * * *", NY, datetime(2026, 11, 1, 0, 40, tzinfo=tz), 4)
    assert [r - halves[0] for r in halves] == [timedelta(minutes=30 * i) for i in range(4)]


@pytest.mark.unit
def test_tc_sched_007_aliases_run_like_their_expressions():
    """TC-SCHED-007: @daily runs at midnight, @hourly on the hour."""
    after = datetime(2026, 5, 5, 10, 15, tzinfo=UTC)
    assert schedules.next_run("@daily", "UTC", after) == datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
    assert schedules.next_run("@hourly", "UTC", after) == datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    assert schedules.describe("0 2 * * *")


@pytest.mark.unit
def test_tc_sched_008_server_timezone_prefers_the_setting_then_falls_back(monkeypatch, mocker):
    """TC-SCHED-008: SCHEDULE_TIMEZONE wins when it is a zone; an unknown one is passed over;
    with nothing usable the default is UTC."""
    settings = mocker.Mock(schedule_timezone="Asia/Taipei")
    mocker.patch.object(schedules, "get_settings", return_value=settings)
    assert schedules.server_timezone() == "Asia/Taipei"
    settings.schedule_timezone = "Nowhere/Land"
    monkeypatch.setenv("TZ", "Europe/Berlin")
    assert schedules.server_timezone() == "Europe/Berlin"
    monkeypatch.setenv("TZ", "Nowhere/Land")
    mocker.patch.object(schedules, "Path", side_effect=OSError)
    mocker.patch.object(schedules.os.path, "realpath", return_value="/nonexistent")
    assert schedules.server_timezone() == "UTC"


def _cfg(**extra) -> BuildConfig:
    return BuildConfig.model_validate({
        "source_type": "git", "git_url": "https://example.com/a.git", "git_ref": "main", **extra,
    })


@pytest.mark.unit
def test_tc_sched_009_settings_fingerprint_is_the_whole_config():
    """TC-SCHED-009: the same settings give the same fingerprint whether stored (a dict with
    a setting missing, which takes its default) or built; any setting, the ref or the
    version changing gives another."""
    base = _cfg()
    stored = base.model_dump(mode="json")
    stored.pop("generate_report")
    assert schedules.settings_fingerprint(stored) == schedules.settings_fingerprint(base)
    assert schedules.settings_fingerprint(_cfg(generate_report=True)) != schedules.settings_fingerprint(base)
    assert schedules.settings_fingerprint(_cfg(git_ref="dev")) != schedules.settings_fingerprint(base)
    assert schedules.settings_fingerprint(_cfg(version="1.0")) != schedules.settings_fingerprint(base)
    assert schedules._same_settings(_built(stored), base)
    assert not schedules._same_settings(_built(None), base)
    assert not schedules._same_settings(_built({"project_type": "no-such-type"}), base)


@pytest.mark.unit
def test_tc_sched_010_unchanged_compares_the_effective_settings_with_the_file():
    """TC-SCHED-010: skip-unchanged compares what was really built, packwright.toml's values
    included. At the same commit (the same file) a saved setting the file overrides changes
    nothing; a setting the file leaves alone still counts; a build that read no file is
    compared on its effective settings too."""
    from app.services import packwright_toml as pt

    submitted = _cfg(entry_point="main.py")
    file = pt.parse('schema = 1\n[python]\nentry = "app.py"\n')
    effective = submitted.model_copy(update=file.values)
    last = _built(submitted.model_dump(mode="json"), pt.record(None, submitted, effective, file))

    # The project's entry point changed since, but the file sets it: the same build.
    assert schedules._same_settings(last, _cfg(entry_point="other.py"))
    assert schedules._same_settings(last, submitted)
    # A setting the file does not set changed: built again.
    assert not schedules._same_settings(last, _cfg(entry_point="main.py", generate_report=True))

    # A build without a packwright.toml: its effective settings are what was submitted.
    plain = _built(submitted.model_dump(mode="json"), pt.record(None, submitted, submitted, None))
    assert schedules._same_settings(plain, submitted)
    assert not schedules._same_settings(plain, _cfg(entry_point="other.py"))
