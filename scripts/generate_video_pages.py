#!/usr/bin/env python3
"""Generate the Pages video index and one detail page per archived video.

The index is sorted newest first by event date, every entry links to its own
detail page, and existing pages for older videos are left untouched.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
SITE = ROOT / "site"
VIDEO_PAGES = SITE / "videos"
CAPTION_DIR = SITE / "captions"
VIDEO_PAGES.mkdir(parents=True, exist_ok=True)
CAPTION_DIR.mkdir(parents=True, exist_ok=True)

FORMATS = ("vtt", "srt", "ttml", "srv3", "srv2", "srv1", "json3")


def parse_info(folder: Path) -> dict | None:
    info_file = folder / "INFO.txt"
    if not info_file.exists():
        return None
    values: dict[str, str] = {}
    for line in info_file.read_text(encoding="utf-8").splitlines():
        for key in ("Video ID", "Event date", "Duration", "Uploader"):
            if key not in values and line.startswith(f"{key}:"):
                values[key] = line.split(":", 1)[1].strip()
        # The title is only the first "Video:" line; later prose may repeat the
        # label with an empty value, which must not overwrite the real title.
        if "Title" not in values and line.startswith("Video:") and not line.startswith("Video ID:"):
            title = line.split(":", 1)[1].strip()
            if title:
                values["Title"] = title
    if not values.get("Video ID"):
        return None
    values.setdefault("Title", values["Video ID"])
    try:
        values["date"] = datetime.strptime(values.get("Event date", ""), "%Y-%m-%d")
    except ValueError:
        values["date"] = datetime.min
    return values


def collect() -> list[dict]:
    videos = []
    for folder in sorted(OUT.iterdir()):
        if not folder.is_dir():
            continue
        values = parse_info(folder)
        if not values:
            continue
        values["folder"] = folder
        videos.append(values)
    videos.sort(key=lambda v: (v["date"], v.get("Title", "")), reverse=True)
    return videos


def copy_caption(video_id: str, folder: Path, language: str) -> list[tuple[str, str]]:
    """Copy the published caption formats into the site and list them."""
    copied = []
    for extension in FORMATS:
        source = folder / f"{video_id}.en.{language}.{extension}"
        if not source.exists():
            continue
        target = CAPTION_DIR / f"{video_id}.{language}.{extension}"
        target.write_bytes(source.read_bytes())
        copied.append((extension, f"captions/{target.name}"))
    return copied


# Older archives stored the tracks under these names instead of the per-format
# layout, so the published pages keep working for them.
LEGACY_CAPTIONS = {
    "en-orig": {"srt": "auto-generated_English.srt", "vtt": "source_English.vtt"},
    "zh-Hans": {"srt": "auto-translated_Chinese.srt"},
}


def copy_legacy_caption(video_id: str, folder: Path, language: str) -> list[tuple[str, str]]:
    copied = []
    for extension, name in LEGACY_CAPTIONS.get(language, {}).items():
        source = folder / name
        if not source.exists():
            continue
        target = CAPTION_DIR / f"{video_id}.{language}.{extension}"
        if target.exists():
            continue
        target.write_bytes(source.read_bytes())
        copied.append((extension, f"captions/{target.name}"))
    return copied


def copy_bilingual(video_id: str, folder: Path) -> list[tuple[str, str]]:
    copied = []
    for extension in ("srt", "vtt", "ass"):
        source = folder / f"auto-translated+auto-generated_Bilingual_zh-Hans-en-orig.{extension}"
        if not source.exists():
            source = folder / f"bilingual_Chinese-English.{extension}"
        if not source.exists():
            continue
        target = CAPTION_DIR / f"{video_id}.bilingual.{extension}"
        target.write_bytes(source.read_bytes())
        copied.append((extension, f"captions/{target.name}"))
    return copied


NAV_ITEMS = (
    ("index", "./", "首页"),
    ("latest", "latest.html", "最新成片"),
    ("videos", "videos.html", "全部成片"),
    ("generator", "generator.html", "字幕生成"),
    ("about", "about.html", "说明"),
)


def nav(prefix: str = "", active: str = "") -> list[str]:
    """The one navigation used by every page, so links cannot drift apart."""
    lines = ['        <nav class="page-nav" aria-label="主导航">']
    for key, href, label in NAV_ITEMS:
        if key == "index":
            target = prefix or "./"
        else:
            target = f"{prefix}{href}"
        current = ' class="active"' if key == active else ""
        lines.append(f'          <a{current} href="{target}">{label}</a>')
    lines.append("        </nav>")
    return lines


def player_block(video_id: str, prefix: str, release: str, title: str) -> list[str]:
    """Embed the small preview; never point a <video> at the multi-GB release.

    The release download is sent as an attachment and does not stream, so a
    browser either downloads 1.8 GB or shows an empty player. The preview is
    cut on a cloud runner and committed to ``site/media/``; when it is not there
    yet the block shows the source thumbnail instead of a broken player.
    """
    preview = SITE / "media" / f"{video_id}-preview.mp4"
    poster = SITE / "media" / f"{video_id}-poster.jpg"
    if preview.exists():
        poster_attr = f' poster="{prefix}media/{poster.name}"' if poster.exists() else ""
        return [
            '        <div class="video-frame">',
            f'          <video controls preload="metadata" playsinline{poster_attr} src="{prefix}media/{preview.name}">',
            f'            <a href="{release}">下载 1080p 成片</a>',
            '          </video>',
            '        </div>',
            '        <p class="hint">网页播放的是 720p 节选预览；完整 1080p 成片见下方下载。</p>',
        ]
    thumbnail = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
    fallback = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return [
        '        <div class="video-frame video-frame--fallback">',
        f'          <img src="{thumbnail}" alt="{title}" loading="lazy"'
        f" onerror=\"this.onerror=null;this.src='{fallback}'\">",
        '        </div>',
        '        <p class="hint">该成片尚未生成网页预览；下方可下载完整成片或打开原始视频。</p>',
    ]


def detail_page(video: dict, previous_video: dict | None, next_video: dict | None) -> str:
    video_id = video["Video ID"]
    title = html.escape(video.get("Title", video_id))
    event_date = video.get("Event date", "")
    duration = video.get("Duration", "")
    uploader = video.get("Uploader", "The White House")
    folder = video["folder"]
    english = copy_caption(video_id, folder, "en-orig") + copy_legacy_caption(
        video_id, folder, "en-orig"
    )
    chinese = copy_caption(video_id, folder, "zh-Hans") + copy_legacy_caption(
        video_id, folder, "zh-Hans"
    )
    bilingual = copy_bilingual(video_id, folder)
    release = (
        "https://github.com/gitsynonyms02/gitsynonyms/releases/download/"
        f"{video_id}/Burned_Bilingual_{video_id}.mp4"
    )
    navigation = nav("../", "videos")
    lines = [
        '<!doctype html>',
        '<html lang="zh-CN">',
        '  <head>',
        '    <meta charset="utf-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1">',
        '    <meta name="theme-color" content="#0b1020">',
        f'    <title>{title} · GitSynonyms</title>',
        '    <link rel="stylesheet" href="../styles.css?v=video-v2">',
        '  </head>',
        '  <body>',
        '    <main class="shell">',
        '      <header>',
        '        <p class="eyebrow">GITSYNONYMS · BURNED CAPTIONS</p>',
        f'        <h1>{title}</h1>',
        f'        <p class="intro">事件日期：{html.escape(event_date)} · 时长：{html.escape(duration)} · 上传者：{html.escape(uploader)}</p>',
        *navigation,
        '      </header>',
        '',
        '      <section class="panel video-panel" aria-labelledby="video-title">',
        f'        <h2 id="video-title">{title}</h2>',
        *player_block(video_id, "../", release, title),
        '        <p class="hint">1080p 硬字幕成片；金色中文在上、白色英文在下，英文逐词高亮，磨砂玻璃钻石背景框从片头持续到片尾。</p>',
        '        <dl class="meta-grid">',
        f'          <div><dt>视频 ID</dt><dd>{html.escape(video_id)}</dd></div>',
        f'          <div><dt>事件日期</dt><dd>{html.escape(event_date)}</dd></div>',
        f'          <div><dt>时长</dt><dd>{html.escape(duration)}</dd></div>',
        f'          <div><dt>上传者</dt><dd>{html.escape(uploader)}</dd></div>',
        '          <div><dt>样式</dt><dd>classic · 玻璃钻石框</dd></div>',
        '          <div><dt>刻录编码</dt><dd>libx264 · CRF 18 · 音频原样复制</dd></div>',
        '          <div><dt>字幕来源</dt><dd>YouTube en-orig + zh-Hans（json3 逐词时间戳）</dd></div>',
        '        </dl>',
        '      </section>',
        '',
        '      <section class="panel" aria-labelledby="download-title">',
        '        <h2 id="download-title">下载</h2>',
        '        <p class="hint">1080p 成片托管于 GitHub Release；字幕文件随站点提供，含全部七种格式。</p>',
        '        <ul class="download-list">',
        '          <li>',
        f'            <a class="secondary-button" href="{release}">1080p 硬字幕 MP4</a>',
        '            <span>全高清成片，GitHub Release 资源</span>',
        '          </li>',
    ]
    for extension, path in bilingual:
        label = {"ass": "双语 ASS", "srt": "双语 SRT", "vtt": "双语 VTT"}[extension]
        lines += [
            '          <li>',
            f'            <a class="secondary-button" href="{path}">{label}</a>',
            f'            <span>{label}，中英对照</span>',
            '          </li>',
        ]
    for extension, path in english:
        lines += [
            '          <li>',
            f'            <a class="secondary-button" href="{path}">English {extension.upper()}</a>',
            f'            <span>YouTube 英文原轨 {extension.upper()} 格式</span>',
            '          </li>',
        ]
    for extension, path in chinese:
        lines += [
            '          <li>',
            f'            <a class="secondary-button" href="{path}">中文 {extension.upper()}</a>',
            f'            <span>YouTube 中文自动翻译 {extension.upper()} 格式</span>',
            '          </li>',
        ]
    lines += [
        '        </ul>',
        f'        <p class="hint">原始视频：<a href="https://www.youtube.com/watch?v={video_id}" target="_blank" rel="noreferrer">youtube.com/watch?v={video_id}</a>。</p>',
        '      </section>',
    ]
    if previous_video or next_video:
        lines += ['', '      <section class="panel" aria-labelledby="siblings-title">',
                  '        <h2 id="siblings-title">其他成片</h2>',
                  '        <ul class="download-list">']
        for sibling in (previous_video, next_video):
            if not sibling:
                continue
            sibling_id = sibling["Video ID"]
            sibling_title = html.escape(sibling.get("Title", sibling_id))
            lines += [
                '          <li>',
                f'            <a class="secondary-button" href="{sibling_id}.html">{sibling_title}</a>',
                f'            <span>📅 {html.escape(sibling.get("Event date", ""))} · ID: {sibling_id}</span>',
                '          </li>',
            ]
        lines += ['        </ul>', '      </section>']
    lines += [
        '',
        '      <footer>',
        '        页面只展示已生成的成片与文件，不保存任何令牌。字幕时间取自源轨道，词级高亮来自 json3 逐词时间戳。',
        '      </footer>',
        '    </main>',
        '  </body>',
        '</html>',
        '',
    ]
    return "\n".join(lines)


def index_page(videos: list[dict]) -> str:
    lines = [
        '<!doctype html>',
        '<html lang="zh-CN">',
        '  <head>',
        '    <meta charset="utf-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1">',
        '    <meta name="theme-color" content="#0b1020">',
        '    <title>视频列表 · GitSynonyms</title>',
        '    <link rel="stylesheet" href="styles.css?v=videos-v2">',
        '  </head>',
        '  <body>',
        '    <main class="shell">',
        '      <header>',
        '        <p class="eyebrow">GITSYNONYMS · BURNED CAPTIONS</p>',
        '        <h1>视频列表</h1>',
        '        <p class="intro">所有已生成的双语成片，按事件时间从新到旧排列。点击标题进入详情页。</p>',
        *nav("", "videos"),
        '      </header>',
        '',
        '      <section class="panel" aria-labelledby="videos-title">',
        '        <h2 id="videos-title">全部成片</h2>',
        '        <ul class="download-list">',
    ]
    for index, video in enumerate(videos):
        video_id = video["Video ID"]
        title = html.escape(video.get("Title", video_id))
        badge = ' <span class="badge">最新</span>' if index == 0 else ''
        lines += [
            '          <li>',
            f'            <a class="secondary-button" href="videos/{video_id}.html">{title}{badge}</a>',
            f'            <span>📅 {html.escape(video.get("Event date", ""))} · 至 {html.escape(video.get("Duration", ""))} · ID: {video_id}</span>',
            '          </li>',
        ]
    lines += [
        '        </ul>',
        '      </section>',
        '',
        '      <footer>',
        '        页面只展示已生成的成片与文件，不保存任何令牌。',
        '      </footer>',
        '    </main>',
        '  </body>',
        '</html>',
        '',
    ]
    return "\n".join(lines)


def latest_page(videos: list[dict]) -> str:
    """The latest page shows the newest video and links to the full archive."""
    newest = videos[0]
    video_id = newest["Video ID"]
    title = html.escape(newest.get("Title", video_id))
    release = (
        "https://github.com/gitsynonyms02/gitsynonyms/releases/download/"
        f"{video_id}/Burned_Bilingual_{video_id}.mp4"
    )
    lines = [
        '<!doctype html>',
        '<html lang="zh-CN">',
        '  <head>',
        '    <meta charset="utf-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1">',
        '    <meta name="theme-color" content="#0b1020">',
        '    <title>最新成片 · GitSynonyms</title>',
        '    <link rel="stylesheet" href="styles.css?v=latest-video-v5">',
        '  </head>',
        '  <body>',
        '    <main class="shell">',
        '      <header>',
        '        <p class="eyebrow">GITSYNONYMS · BURNED CAPTIONS</p>',
        '        <h1>最新成片</h1>',
        '        <p class="intro">最新生成的双语成片。点击进入详情页可查看全部七种字幕格式与下载链接。</p>',
        *nav("", "latest"),
        '      </header>',
        '',
        '      <section class="panel video-panel" aria-labelledby="video-title">',
        f'        <h2 id="video-title">{title}</h2>',
        *player_block(video_id, "", release, title),
        '        <p class="hint">1080p 硬字幕成片；金色中文在上、白色英文在下，英文逐词高亮，磨砂玻璃钻石背景框从片头持续到片尾。</p>',
        '        <dl class="meta-grid">',
        f'          <div><dt>视频 ID</dt><dd>{html.escape(video_id)}</dd></div>',
        f'          <div><dt>事件日期</dt><dd>{html.escape(newest.get("Event date", ""))}</dd></div>',
        f'          <div><dt>时长</dt><dd>{html.escape(newest.get("Duration", ""))}</dd></div>',
        '          <div><dt>样式</dt><dd>classic · 玻璃钻石框</dd></div>',
        '          <div><dt>刻录编码</dt><dd>libx264 · CRF 18 · 音频原样复制</dd></div>',
        '          <div><dt>字幕来源</dt><dd>YouTube en-orig + zh-Hans（json3 逐词时间戳）</dd></div>',
        '        </dl>',
        '      </section>',
        '',
        '      <section class="panel" aria-labelledby="download-title">',
        '        <h2 id="download-title">下载（最新成片）</h2>',
        '        <p class="hint">1080p 成片托管于 GitHub Release；字幕文件随站点提供。</p>',
        '        <ul class="download-list">',
        '          <li>',
        f'            <a class="secondary-button" href="{release}">1080p 硬字幕 MP4</a>',
        '            <span>全高清成片，GitHub Release 资源</span>',
        '          </li>',
    ]
    for extension, path in copy_bilingual(video_id, newest["folder"]):
        label = {"ass": "双语 ASS", "srt": "双语 SRT", "vtt": "双语 VTT"}[extension]
        lines += [
            '          <li>',
            f'            <a class="secondary-button" href="{path}">{label}</a>',
            f'            <span>{label}，中英对照</span>',
            '          </li>',
        ]
    for language, extension, path in [
        ("English", ext, p)
        for ext, p in (
            copy_caption(video_id, newest["folder"], "en-orig")
            + copy_legacy_caption(video_id, newest["folder"], "en-orig")
        )
    ] + [
        ("中文", ext, p)
        for ext, p in (
            copy_caption(video_id, newest["folder"], "zh-Hans")
            + copy_legacy_caption(video_id, newest["folder"], "zh-Hans")
        )
    ]:
        lines += [
            '          <li>',
            f'            <a class="secondary-button" href="{path}">{language} {extension.upper()}</a>',
            f'            <span>{language} {extension.upper()} 字幕文件</span>',
            '          </li>',
        ]
    lines += [
        '        </ul>',
        f'        <p class="hint">原始视频：<a href="https://www.youtube.com/watch?v={video_id}" target="_blank" rel="noreferrer">youtube.com/watch?v={video_id}</a>。</p>',
        '      </section>',
        '',
        '      <section class="panel" aria-labelledby="archive-title">',
        '        <h2 id="archive-title">全部成片</h2>',
        '        <ul class="download-list">',
    ]
    for video in videos:
        other_id = video["Video ID"]
        lines += [
            '          <li>',
            f'            <a class="secondary-button" href="videos/{other_id}.html">{html.escape(video.get("Title", other_id))}</a>',
            f'            <span>📅 {html.escape(video.get("Event date", ""))} · ID: {other_id}</span>',
            '          </li>',
        ]
    lines += [
        '        </ul>',
        '      </section>',
        '',
        '      <footer>',
        '        页面只展示已生成的成片与文件，不保存任何令牌。字幕时间取自源轨道，词级高亮来自 json3 逐词时间戳。',
        '      </footer>',
        '    </main>',
        '  </body>',
        '</html>',
        '',
    ]
    return "\n".join(lines)


def home_page(videos: list[dict]) -> str:
    """The public landing page: what this is, the newest film, and recent ones.

    Long explanations live on ``about.html``; the landing page only answers
    "what is this" and "where do I watch the newest one".
    """
    newest = videos[0]
    video_id = newest["Video ID"]
    title = html.escape(newest.get("Title", video_id))
    release = (
        "https://github.com/gitsynonyms02/gitsynonyms/releases/download/"
        f"{video_id}/Burned_Bilingual_{video_id}.mp4"
    )
    lines = [
        '<!doctype html>',
        '<html lang="zh-CN">',
        '  <head>',
        '    <meta charset="utf-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1">',
        '    <meta name="theme-color" content="#0b1020">',
        '    <meta name="description" content="白宫现场的中英双语 1080p 成片，附七种字幕格式。">',
        '    <title>白宫现场 · 中英双语成片 · GitSynonyms</title>',
        '    <link rel="stylesheet" href="styles.css?v=home-v1">',
        '  </head>',
        '  <body>',
        '    <main class="shell">',
        '      <header>',
        '        <p class="eyebrow">GITSYNONYMS · WHITE HOUSE / BILINGUAL</p>',
        '        <h1>白宫现场，中英双语</h1>',
        '        <p class="intro">把白宫发布会、集会与讲话做成 1080p 中英双语成片，字幕逐词对齐，成片与七种字幕格式一并公开。</p>',
        *nav("", "index"),
        '      </header>',
        '',
        '      <section class="panel video-panel" aria-labelledby="latest-title">',
        '        <p class="eyebrow">最新一场</p>',
        f'        <h2 id="latest-title">{title}</h2>',
        f'        <p class="hint">📅 {html.escape(newest.get("Event date", ""))} · {html.escape(newest.get("Duration", ""))} · 1080p · 中英双语</p>',
        *player_block(video_id, "", release, title),
        '        <div class="actions">',
        f'          <a class="secondary-button" href="videos/{video_id}.html">观看与下载</a>',
        '          <a class="secondary-button" href="latest.html">成片详情与字幕</a>',
        '        </div>',
        '      </section>',
        '',
        '      <section class="panel" aria-labelledby="recent-title">',
        '        <h2 id="recent-title">近期成片</h2>',
        '        <ul class="download-list">',
    ]
    for video in videos[:5]:
        other_id = video["Video ID"]
        lines += [
            '          <li>',
            f'            <a class="secondary-button" href="videos/{other_id}.html">{html.escape(video.get("Title", other_id))}</a>',
            f'            <span>📅 {html.escape(video.get("Event date", ""))} · ID: {other_id}</span>',
            '          </li>',
        ]
    lines += [
        '        </ul>',
        '        <p class="hint"><a href="videos.html">查看全部成片 →</a></p>',
        '      </section>',
        '',
        '      <section class="panel" aria-labelledby="how-title">',
        '        <h2 id="how-title">这条流水线在做什么</h2>',
        '        <p class="hint">监测白宫发布 → 获取干净素材 → 七种字幕格式与 ASR／翻译 → 1080p 双语刻录 → 备份后发布。每一步的规则与限制写在说明页。</p>',
        '        <div class="actions">',
        '          <a class="secondary-button" href="about.html">完整说明</a>',
        '          <a class="secondary-button" href="generator.html">字幕生成器</a>',
        '        </div>',
        '      </section>',
        '',
        '      <footer>',
        '        公开页面，不保存任何令牌。成片取自 YouTube 公开视频；机器翻译字幕已标注引擎与生成时间。',
        '      </footer>',
        '    </main>',
        '  </body>',
        '</html>',
        '',
    ]
    return "\n".join(lines)


def main() -> int:
    videos = collect()
    print(f"videos found: {len(videos)}")
    for index, video in enumerate(videos):
        video_id = video["Video ID"]
        previous_video = videos[index + 1] if index + 1 < len(videos) else None
        next_video = videos[index - 1] if index > 0 else None
        page = VIDEO_PAGES / f"{video_id}.html"
        page.write_text(detail_page(video, previous_video, next_video), encoding="utf-8")
        print(f"  wrote {page.relative_to(SITE)}")
    index = SITE / "videos.html"
    index.write_text(index_page(videos), encoding="utf-8")
    print(f"  wrote {index.relative_to(SITE)}")
    if videos:
        home = SITE / "index.html"
        home.write_text(home_page(videos), encoding="utf-8")
        print(f"  wrote {home.relative_to(SITE)}")
        latest = SITE / "latest.html"
        latest.write_text(latest_page(videos), encoding="utf-8")
        print(f"  wrote {latest.relative_to(SITE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
