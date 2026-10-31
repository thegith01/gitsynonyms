import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "monitoring" / "time_verification.py"
SPEC = importlib.util.spec_from_file_location("time_verification", SCRIPT)
tv = importlib.util.module_from_spec(SPEC)
sys.modules["time_verification"] = tv
SPEC.loader.exec_module(tv)

NOW = datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc)


def reading(operator, *, seconds=0, status="ok", independent=True):
    return tv.ClockReading(
        source=operator,
        operator=operator,
        kind="test",
        status=status,
        utc=datetime.fromtimestamp(NOW.timestamp() + seconds, timezone.utc),
        uncertainty_ms=50,
        independent=independent,
    )


def evidence():
    return {
        "event_id": "white-house-halloween-2026",
        "timezone": "America/New_York",
        "videos": [
            {
                "id": "tcTeKoKBR6Q",
                "source": "The White House",
                "url": "https://www.youtube.com/watch?v=tcTeKoKBR6Q",
                "live_status": "was_live",
                "started_at": "2026-10-29T17:12:17-04:00",
                "duration_s": 4170,
            },
            {
                "id": "rZMVdU4nC-4",
                "source": "RSBN",
                "url": "https://www.youtube.com/watch?v=rZMVdU4nC-4",
                "live_status": "was_live",
                "description_time": "2026-10-29T17:00:00-04:00",
                "overlay_readings": [
                    {"clock": "2026-10-29T17:09:00-04:00", "frame": "maxres1"},
                    {"clock": "2026-10-29T17:18:00-04:00", "frame": "maxres2"},
                ],
            },
        ],
        "schedules": [
            {
                "source": "White House Press Pool",
                "url": "https://x.com/WHPressPool/status/1",
                "time": "2026-10-29T17:30:00-04:00",
            },
            {
                "source": "DVIDS",
                "url": "https://www.dvidshub.net/webcast/38646",
                "time": "2026-10-29T17:20:00-04:00",
            },
            {
                "source": "The Hill",
                "url": "https://thehill.com/video-clips/1",
                "time": "2026-10-29T17:30:00-04:00",
            },
            {
                "source": "Factbase reprint",
                "url": "https://rollcall.com/factbase/trump/calendar/",
                "time": "2026-10-29T17:30:00-04:00",
                "independent": False,
            },
        ],
        "articles": [
            {
                "source": "PBS / AP",
                "url": "https://www.pbs.org/newshour/politics/watch",
                "published": "2026-10-29T19:53:45-04:00",
            }
        ],
    }


def consensus(*readings, required=3):
    return tv.consensus(list(readings), required=required)


def test_three_independent_operators_are_required():
    result = consensus(reading("google"), reading("cloudflare"))
    assert result["status"] == "unverified"
    assert result["channels_ok"] == 2


def test_three_agreeing_operators_verify():
    result = consensus(reading("google"), reading("cloudflare"), reading("github"))
    assert result["status"] == "verified"
    assert result["channels_ok"] == 3
    assert len(result["operators"]) == 3


def test_same_operator_does_not_count_twice():
    result = consensus(
        reading("google"),
        tv.ClockReading("google-ntp", "google", "ntp", "ok", NOW, 10),
        reading("cloudflare"),
    )
    assert result["status"] == "unverified"
    assert result["channels_ok"] == 2


def test_one_bad_clock_is_rejected_not_averaged_in():
    result = consensus(
        reading("google"),
        reading("cloudflare"),
        reading("github"),
        reading("apple", seconds=60),
    )
    assert result["status"] == "verified"
    assert result["channels_ok"] == 3
    assert result["spread_ms"] < 5000


def test_system_clock_is_never_independent():
    result = consensus(
        tv.ClockReading("system", "local", "system", "ok", NOW, 10, independent=False),
        reading("google"),
        reading("cloudflare"),
    )
    assert result["status"] == "unverified"


def test_parse_clock_accepts_eastern_advisory_time():
    moment = tv.parse_clock("Thursday, October 29, 2026, at 5:30 PM ET")
    assert tv.iso_et(moment) == "2026-10-29T17:30:00-04:00"


def test_parse_clock_requires_a_clock_not_just_a_date():
    try:
        tv.parse_clock("2026-10-29")
    except ValueError as error:
        assert "without a clock" in str(error)
    else:
        raise AssertionError("date-only value must be rejected")


def test_live_replay_title_does_not_override_platform_metadata():
    verdict = tv.live_status({"live_status": "was_live", "title": "LIVE REPLAY: Halloween"})
    assert verdict["status"] == "ended_live"
    assert verdict["was_live"] is True
    assert verdict["at_verification_live"] is False


def test_live_title_alone_is_not_proof():
    verdict = tv.live_status({"title": "LIVE: Halloween"})
    assert verdict["status"] == "unknown"
    assert verdict["authoritative"] is False


def test_verify_event_confirms_eastern_time_and_reports_unknown_latency():
    clocks = consensus(
        reading("google"), reading("cloudflare"), reading("github"),
        required=3,
    )
    report = tv.verify_event(evidence(), {"status": "verified", "channels_ok": 3,
                                          "consensus_utc": tv.iso(NOW),
                                          "uncertainty_ms": 100,
                                          "sources": clocks["sources"]})
    assert report["absolute_time"]["event_start_et"] == "2026-10-29T17:30:00-04:00"
    assert report["absolute_time"]["status"] == "confirmed"
    assert report["absolute_time"]["source_count"] == 3
    assert report["live_status"]["at_verification"] == "ended_live"
    assert report["live_status"]["was_live"] is True
    assert report["delay"]["stream_latency_s"] is None
    assert report["delay"]["latency_status"] == "unknown"
    assert report["delay"]["schedule_lead_s"] == 1800
    assert report["checks"]["three_clock_channels"] is True


def test_verify_event_stays_unverified_when_clock_channels_are_short():
    report = tv.verify_event(
        evidence(),
        {"status": "unverified", "channels_ok": 2, "consensus_utc": tv.iso(NOW),
         "uncertainty_ms": 0, "sources": []},
    )
    assert report["absolute_time"]["status"] == "unverified"
    assert report["confidence"] == "low"


def test_markdown_renders_unknown_latency_without_inventing_a_number():
    clocks = consensus(reading("google"), reading("cloudflare"), reading("github"))
    report = tv.verify_event(evidence(), {
        "status": "verified", "channels_ok": 3, "consensus_utc": tv.iso(NOW),
        "uncertainty_ms": 100, "sources": clocks["sources"],
    })
    markdown = tv.render_markdown(report)
    assert "2026-10-29T17:30:00-04:00" in markdown
    assert "流媒体延迟：**unknown**" in markdown
    assert "直播状态：**ended_live**" in markdown
