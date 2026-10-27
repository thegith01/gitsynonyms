import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "footage_quality.py"
SPEC = importlib.util.spec_from_file_location("footage_quality", SCRIPT)
footage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = footage
SPEC.loader.exec_module(footage)


def test_a_long_clean_multi_angle_clip_scores_one_hundred():
    result = footage.score_footage(5400, 0.0, 0.0, 20, 3)

    assert result["total"] == 100
    assert result["passes_threshold"] is True


def test_a_frozen_clip_fails_even_when_it_is_long_and_trusted():
    result = footage.score_footage(5400, 0.80, 0.0, 20, 3)

    assert result["motion"] == 0
    assert result["passes_threshold"] is False


def test_a_black_clip_fails_the_clean_criterion():
    result = footage.score_footage(5400, 0.0, 0.50, 20, 3)

    assert result["clean"] == 0
    assert result["passes_threshold"] is False


def test_a_short_single_angle_clip_cannot_reach_the_pass_mark():
    result = footage.score_footage(120, 0.0, 0.0, 12, 1)

    assert result["total"] < footage.PASS_MARK
    assert result["passes_threshold"] is False


def test_angle_points_are_graduated():
    assert footage.score_footage(5400, 0, 0, 20, 3)["angles"] == 15
    assert footage.score_footage(5400, 0, 0, 20, 2)["angles"] == 12
    assert footage.score_footage(5400, 0, 0, 20, 1)["angles"] == 6


def test_parse_durations_sums_every_event():
    log_text = (
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_start: 1.5\n"
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_duration: 2.25\n"
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_end: 3.75\n"
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_duration: 1.75\n"
    )

    assert footage.parse_durations(log_text, "freeze_duration") == 4.0


def test_parse_scene_count_counts_metadata_blocks():
    stdout = (
        "frame:0    pts:0       pts_time:0\n"
        "frame:30   pts:3000    pts_time:1.0\n"
        "frame:90   pts:9000    pts_time:3.0\n"
    )

    assert footage.parse_scene_count(stdout) == 3


def test_windows_are_evenly_spaced_and_cover_the_clip():
    windows = footage.windows(600, 6, 20)

    assert len(windows) == 6
    assert windows[0] == (0.0, 20)
    assert windows[-1][0] + 20 == 600
    starts = [start for start, _ in windows]
    assert starts == sorted(starts)


def test_short_clip_uses_one_window():
    assert footage.windows(12, 6, 20) == [(0.0, 12)]


def test_source_context_reads_trust_and_distinct_channels(tmp_path):
    report = {
        "selected": "a",
        "candidates": [
            {"id": "a", "channel": "White House", "score": {"total": 88, "trust": 20}},
            {"id": "b", "channel": "Reuters", "score": {"total": 70, "trust": 18}},
            {"id": "c", "channel": "Reuters", "score": {"total": 65, "trust": 18}},
            {"id": "d", "channel": "Random", "score": {"total": 42, "trust": 4}},
        ],
    }
    path = tmp_path / "SOURCES.json"
    path.write_text(__import__("json").dumps(report), encoding="utf-8")

    trust, angles = footage.source_context(path)

    assert trust == 20
    assert angles == 2
