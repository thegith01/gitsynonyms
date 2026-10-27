import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "make_web_preview.py"
SPEC = importlib.util.spec_from_file_location("make_web_preview", SCRIPT)
preview = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preview
SPEC.loader.exec_module(preview)


def test_segments_are_spread_out_and_never_overlap():
    starts = preview.pick_segments(11771, count=3, seconds=30)

    assert len(starts) == 3
    assert starts == sorted(starts)
    assert starts[0] >= 0
    assert starts[-1] + 30 <= 11771
    for earlier, later in zip(starts, starts[1:]):
        assert later - earlier >= 30


def test_a_short_film_collapses_to_one_segment():
    assert preview.pick_segments(40, count=3, seconds=30) == [0.0]


def test_segments_never_run_past_the_end_of_a_borderline_film():
    starts = preview.pick_segments(95, count=3, seconds=30)

    assert starts
    for start in starts:
        assert start + 30 <= 95


def test_zero_duration_is_rejected():
    try:
        preview.pick_segments(0)
    except ValueError as error:
        assert "positive" in str(error)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("zero duration must be rejected")


def test_preview_command_joins_every_segment_with_audio(tmp_path):
    command = preview.build_preview_command(
        "ffmpeg",
        tmp_path / "in.mp4",
        tmp_path / "out.mp4",
        [10.0, 50.0],
        seconds=30,
        height=720,
        crf=30,
        audio=True,
    )

    joined = " ".join(command)
    assert command[0] == "ffmpeg"
    assert "trim=start=10.0:duration=30" in joined
    assert "trim=start=50.0:duration=30" in joined
    assert "atrim=start=10.0:duration=30" in joined
    assert "concat=n=2:v=1:a=1[v][a]" in joined
    assert "-map [v] -map [a]" in joined
    assert "-movflags +faststart" in joined
    assert "scale=-2:720" in joined


def test_preview_command_drops_audio_when_the_source_has_none(tmp_path):
    command = preview.build_preview_command(
        "ffmpeg", tmp_path / "in.mp4", tmp_path / "out.mp4", [0.0], audio=False
    )

    joined = " ".join(command)
    assert "atrim" not in joined
    assert "concat=n=1:v=1:a=0[v]" in joined
    assert "-an" in joined


def test_poster_is_taken_from_the_requested_second(tmp_path):
    command = preview.build_poster_command(
        "ffmpeg", tmp_path / "in.mp4", tmp_path / "poster.jpg", at_seconds=42.5
    )

    joined = " ".join(command)
    assert "-ss 42.500" in joined
    assert "-frames:v 1" in joined
    assert "scale=1280:-2" in joined
