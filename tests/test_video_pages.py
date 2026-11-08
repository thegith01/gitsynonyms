import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "generate_video_pages.py"
SPEC = importlib.util.spec_from_file_location("generate_video_pages", SCRIPT)
pages = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pages
SPEC.loader.exec_module(pages)


VIDEOS = [
    {
        "Video ID": "abc123",
        "Title": "Latest <rally>",
        "Event date": "2026-10-25",
        "Duration": "01:00:00 (3600 s)",
        "folder": Path("."),
    },
    {
        "Video ID": "def456",
        "Title": "Older",
        "Event date": "2026-10-20",
        "Duration": "00:30:00 (1800 s)",
        "folder": Path("."),
    },
]


def test_nav_links_are_relative_per_page_depth():
    root = "\n".join(pages.nav("", "index"))
    detail = "\n".join(pages.nav("../", "videos"))

    assert '<a class="active" href="./">首页</a>' in root
    assert '<a href="about.html">说明</a>' in root
    assert '<a href="../about.html">说明</a>' in detail
    assert '<a class="active" href="../videos.html">全部成片</a>' in detail


def test_home_page_is_a_landing_page_not_the_generator_form():
    text = pages.home_page(VIDEOS)

    assert "白宫现场，中英双语" in text
    assert "最新一场" in text
    assert "videos/abc123.html" in text
    assert 'href="about.html"' in text
    assert 'id="download-form"' not in text


def test_home_page_escapes_the_title_and_omits_missing_videos():
    text = pages.home_page(VIDEOS[:1])

    assert "Latest &lt;rally&gt;" in text
    assert "def456" not in text


def test_latest_page_points_at_the_newest_video():
    text = pages.latest_page(VIDEOS)

    assert "Burned_Bilingual_abc123.mp4" in text
    assert "videos/abc123.html" in text
    assert "videos/def456.html" in text


def test_player_never_points_at_the_multi_gigabyte_release():
    block = "\n".join(
        pages.player_block(
            "abc123", "", "https://example.test/Burned_Bilingual_abc123.mp4", "Title"
        )
    )

    assert "<video" not in block
    assert 'src="https://example.test/Burned_Bilingual_abc123.mp4"' not in block
    assert "i.ytimg.com/vi/abc123/maxresdefault.jpg" in block
    assert "hqdefault.jpg" in block


def test_player_uses_the_committed_preview_when_present(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    (media / "abc123-preview.mp4").write_bytes(b"preview")
    (media / "abc123-poster.jpg").write_bytes(b"poster")
    monkeypatch.setattr(pages, "SITE", tmp_path)

    block = "\n".join(
        pages.player_block(
            "abc123", "../", "https://example.test/Burned_Bilingual_abc123.mp4", "Title"
        )
    )

    assert 'src="../media/abc123-preview.mp4"' in block
    assert 'poster="../media/abc123-poster.jpg"' in block
    assert "720p 节选预览" in block

