import importlib.util
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "monitoring"
    / "resolve_channel_feed.py"
)
SPEC = importlib.util.spec_from_file_location("resolve_channel_feed", SCRIPT)
resolver = importlib.util.module_from_spec(SPEC)
sys.modules["resolve_channel_feed"] = resolver
SPEC.loader.exec_module(resolver)

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def candidate(video_id, title, tab, rank, live_status="", duration=None):
    return resolver.Candidate(
        video_id=video_id,
        title=title,
        tab=tab,
        rank=rank,
        live_status=live_status,
        duration=duration,
        published=resolver.parse_title_date(title),
    )


def test_parse_title_date_reads_short_long_and_iso_dates():
    assert resolver.parse_title_date(
        "President Trump Delivers Remarks, Oct. 30, 2026"
    ) == date(2026, 10, 30)
    assert resolver.parse_title_date(
        "President Trump Participates in a Roundtable, October 21, 2026"
    ) == date(2026, 10, 21)
    assert resolver.parse_title_date(
        "Remarks on 2026-10-30"
    ) == date(2026, 10, 30)
    assert resolver.parse_title_date(
        "President Trump Hosts a Celebration, Sept. 9, 2026"
    ) == date(2026, 9, 9)
    assert resolver.parse_title_date("Hello, America") is None
    assert resolver.parse_title_date("Impossible date, Feb. 31, 2026") is None


def test_stream_replay_outranks_an_undated_video_upload():
    """The reported wET2 case: the replay exists only on /streams."""
    candidates = [
        candidate("N464mBP5dmE", "Hello, America", "videos", 0),
        candidate(
            "YZT8jsIJyQU",
            "President Trump Meets with Artemis III Crew at the White House",
            "videos",
            1,
        ),
        candidate(
            "jikmROaDmLU",
            "President Trump Gaggles with Press, Oct. 29, 2026",
            "videos",
            2,
        ),
        candidate(
            "wET2hazuFD4",
            "President Trump Delivers Remarks, Oct. 30, 2026",
            "streams",
            0,
        ),
        candidate(
            "RyCfzP3I4eA",
            "Secretary of the Treasury Holds a Press Conference",
            "streams",
            1,
        ),
    ]

    selected = resolver.choose_candidate(
        candidates,
        processed={"YZT8jsIJyQU"},
        attempts={},
        now=NOW,
    )

    assert selected is not None
    assert selected.video_id == "wET2hazuFD4"


def test_live_processed_and_quarantined_candidates_are_skipped():
    candidates = [
        candidate(
            "wET2hazuFD4",
            "Remarks, Oct. 31, 2026",
            "streams",
            0,
            live_status="is_live",
        ),
        candidate(
            "N464mBP5dmE",
            "Remarks, Oct. 30, 2026",
            "videos",
            0,
        ),
        candidate(
            "jikmROaDmLU",
            "Remarks, Oct. 29, 2026",
            "videos",
            1,
        ),
        candidate(
            "YZT8jsIJyQU",
            "Remarks, Oct. 28, 2026",
            "videos",
            2,
        ),
    ]

    selected = resolver.choose_candidate(
        candidates,
        processed={"N464mBP5dmE"},
        attempts={
            "jikmROaDmLU": {
                "attempts": 3,
                "last_attempt": "2026-10-31T10:00:00Z",
            }
        },
        now=NOW,
    )

    assert selected is not None
    assert selected.video_id == "YZT8jsIJyQU"


def test_duplicate_video_prefers_the_streams_tab():
    candidates = [
        candidate("wET2hazuFD4", "Remarks, Oct. 30, 2026", "videos", 0),
        candidate("wET2hazuFD4", "Remarks, Oct. 30, 2026", "streams", 5),
    ]

    merged = resolver.deduplicate(candidates)

    assert len(merged) == 1
    assert merged[0].tab == "streams"


def test_quarantine_expires_after_the_cooldown():
    record = {
        "attempts": 3,
        "last_attempt": "2026-10-31T09:00:00Z",
    }
    remaining = resolver.quarantine_remaining(
        record,
        now=NOW,
        max_attempts=3,
        cooldown=timedelta(hours=6),
    )
    assert remaining == timedelta(hours=3)

    expired = resolver.quarantine_remaining(
        record,
        now=datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc),
        max_attempts=3,
        cooldown=timedelta(hours=6),
    )
    assert expired is None


def test_failure_attempts_accumulate_and_clear(tmp_path):
    path = tmp_path / "attempts.json"

    resolver.record_failure("N464mBP5dmE", path=path, now=NOW)
    resolver.record_failure("N464mBP5dmE", path=path, now=NOW)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["videos"]["N464mBP5dmE"]["attempts"] == 2
    assert payload["videos"]["N464mBP5dmE"]["last_attempt"] == "2026-10-31T12:00:00Z"

    resolver.clear_failure("N464mBP5dmE", path=path, now=NOW)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "N464mBP5dmE" not in payload["videos"]


def test_clear_failure_does_not_rewrite_an_untouched_ledger(tmp_path):
    path = tmp_path / "attempts.json"
    path.write_text('{"version": 1, "videos": {}}', encoding="utf-8")
    before = path.stat().st_mtime_ns

    resolver.clear_failure("wET2hazuFD4", path=path, now=NOW)

    assert path.stat().st_mtime_ns == before


def test_parse_listing_ignores_malformed_lines_and_keeps_pipes():
    stdout = (
        "wET2hazuFD4\tPresident Trump Delivers Remarks, Oct. 30, 2026\twas_live\t735\n"
        "not-a-video\n"
        "N464mBP5dmE\tHello | America\tNA\t138\n"
    )

    candidates = resolver.parse_listing(stdout, "streams")

    assert [item.video_id for item in candidates] == [
        "wET2hazuFD4",
        "N464mBP5dmE",
    ]
    assert candidates[1].title == "Hello | America"
    assert candidates[0].live_status == "was_live"
    assert candidates[0].duration == 735.0


def test_post_live_stream_is_deferred_until_the_replay_is_ready():
    candidates = [
        candidate(
            "wET2hazuFD4",
            "Remarks, Oct. 31, 2026",
            "streams",
            0,
            live_status="post_live",
        ),
        candidate(
            "N464mBP5dmE",
            "Remarks, Oct. 30, 2026",
            "videos",
            0,
        ),
    ]

    selected = resolver.choose_candidate(
        candidates,
        processed=set(),
        attempts={},
        now=NOW,
    )

    assert selected is not None
    assert selected.video_id == "N464mBP5dmE"


def test_force_check_reprocesses_an_already_recorded_video():
    candidates = [
        candidate(
            "wET2hazuFD4",
            "President Trump Delivers Remarks, Oct. 30, 2026",
            "streams",
            0,
        )
    ]

    skipped = resolver.choose_candidate(
        candidates,
        processed={"wET2hazuFD4"},
        attempts={},
        now=NOW,
    )
    forced = resolver.choose_candidate(
        candidates,
        processed={"wET2hazuFD4"},
        attempts={},
        now=NOW,
        force_check=True,
    )

    assert skipped is None
    assert forced is not None
    assert forced.video_id == "wET2hazuFD4"


def test_scan_keeps_the_healthy_tab_when_the_other_one_fails(monkeypatch):
    monkeypatch.setattr(resolver.shutil, "which", lambda name: "/usr/bin/yt-dlp")

    def fake_runner(command, **kwargs):
        if command[-1].endswith("/streams"):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="ERROR: Sign in to confirm you're not a bot.",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="N464mBP5dmE\tHello, America\tNA\t138\n",
            stderr="",
        )

    candidates = resolver.scan(include_streams=True, runner=fake_runner)

    assert [item.video_id for item in candidates] == ["N464mBP5dmE"]


def test_installed_workflow_matches_its_tracked_source():
    root = Path(__file__).parents[1]
    source = root / "scripts" / "monitoring" / "monitor-whitehouse.yml"
    installed = root / ".github" / "workflows" / "monitor-whitehouse.yml"

    assert source.read_text(encoding="utf-8") == installed.read_text(encoding="utf-8")


def test_scan_reads_both_tabs_with_one_client(monkeypatch):
    monkeypatch.setattr(resolver.shutil, "which", lambda name: "/usr/bin/yt-dlp")

    def fake_runner(command, **kwargs):
        url = command[-1]
        if url.endswith("/streams"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "wET2hazuFD4\tPresident Trump Delivers Remarks, Oct. 30, 2026\t"
                    "was_live\t735\n"
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="N464mBP5dmE\tHello, America\tNA\t138\n",
            stderr="",
        )

    candidates = resolver.scan(include_streams=True, runner=fake_runner)

    assert {item.tab for item in candidates} == {"videos", "streams"}
    assert {item.video_id for item in candidates} == {"N464mBP5dmE", "wET2hazuFD4"}
