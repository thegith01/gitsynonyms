#!/usr/bin/env python3
"""Fetch every YouTube caption serialization for the wanted languages.

DIRECTIVE 3.7 says the seven YouTube formats are tried first.  ``yt-dlp``
accepts one ``--sub-format`` preference list and keeps a single file per
language, so this wrapper drives ``download_track`` once per language and
records exactly which of ``json3/srv3/srv2/srv1/ttml/vtt/srt`` YouTube served.

The downloaded files are renamed to the canonical language codes the burner
expects (``en-orig`` and ``zh-Hans``) while the report keeps the real YouTube
code and whether the track was manual, auto-generated or auto-translated.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import download_youtube_bilingual_srt as captions  # noqa: E402

ENGLISH_PREFERENCES = ("en-orig", "en", "en-US", "en-GB", "en-CA", "en-AU")
CHINESE_PREFERENCES = ("zh-Hans", "zh-CN", "zh", "zh-SG", "zh-Hant", "zh-TW", "zh-HK")

CANONICAL = {"en": "en-orig", "zh": "zh-Hans"}


def log(message: str) -> None:
    print(message, flush=True)


def first_match(tracks: dict, preferences: tuple[str, ...]) -> str | None:
    found = captions.pick_language(tracks, preferences)
    if found:
        return found
    prefix = preferences[0].split("-")[0].lower()
    for code in sorted(tracks):
        if code.lower().split("-")[0] == prefix:
            return code
    return None


def resolve(metadata: dict, group: str) -> tuple[str, str] | None:
    """Return (youtube_code, track_kind) for one language group, or None."""
    preferences = ENGLISH_PREFERENCES if group == "en" else CHINESE_PREFERENCES
    manual = metadata.get("subtitles") or {}
    auto = metadata.get("automatic_captions") or {}
    code = first_match(manual, preferences)
    if code:
        return code, "manual"
    code = first_match(auto, preferences)
    if code:
        return code, "auto-generated"
    return None


def proxy_from_env() -> str | None:
    for name in (
        "YTDLP_PROXY",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        value = os.environ.get(name)
        if value:
            return value
    return None


def download_caption_url(url: str, target: Path) -> None:
    """Download one timedtext serialization directly.

    yt-dlp's subtitle downloader occasionally loses the bot-check race even
    when the metadata listing (which carries these signed URLs) succeeded.
    The timedtext endpoint itself is usually still reachable, so this is a
    format-level fallback, not a substitute for the seven-format attempt.
    """
    proxy = proxy_from_env()
    handlers = (
        [urllib.request.ProxyHandler({"http": proxy, "https": proxy})]
        if proxy
        else []
    )
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
    )
    with opener.open(request, timeout=90) as response:
        data = response.read()
    if not data:
        raise RuntimeError("empty timedtext response")
    target.write_bytes(data)


def rename_to_canonical(files: list[Path], video_id: str, code: str, canonical: str) -> list[Path]:
    renamed: list[Path] = []
    for path in files:
        suffix = path.name[len(video_id) + 1 :]
        if not suffix.lower().startswith(code.lower() + "."):
            renamed.append(path)
            continue
        # yt-dlp expands %(language)s to "en.en" or "en.zh-Hans"; keep only the
        # extension and write the canonical code the burner discovers.
        extension = suffix.rsplit(".", 1)[-1]
        target = path.with_name(f"{video_id}.{canonical}.{extension}")
        if target != path:
            path.replace(target)
        renamed.append(target)
    return renamed


def write_report(
    path: Path,
    video_id: str,
    tracks: dict,
    *,
    error: str = "",
    required: list[str] | None = None,
) -> None:
    report: dict = {
        "video_id": video_id,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "youtube",
        "tracks": tracks,
        "available_languages": [],
    }
    if error:
        report["error"] = error
    if required:
        report["required"] = required
        report["missing"] = [
            code for code in required if not tracks.get(code, {}).get("present")
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


LISTING_CLIENTS = ("", "tv", "web_safari", "mweb", "android", "ios")


def listing_arguments(url: str, client: str) -> list[str]:
    arguments = ["-J", "--skip-download"]
    if client:
        arguments += ["--extractor-args", f"youtube:player_client={client}"]
    arguments.append(url)
    return arguments


def try_listing(url: str) -> dict:
    """Ask every player client for the metadata, newest fallback last.

    YouTube's bot check is client-specific: the web client can demand a
    sign-in while ``tv`` or ``mweb`` still returns the caption tracks from the
    same IP.  The first client that returns a listing with caption tracks wins;
    a listing without tracks is not accepted because the caption stage needs
    the signed timedtext URLs it carries.
    """
    errors: list[str] = []
    for client in LISTING_CLIENTS:
        label = client or "default"
        try:
            listing = captions.run_ytdlp(
                listing_arguments(url, client), show_progress=False
            )
            data = json.loads(listing.stdout)
        except Exception as error:  # noqa: BLE001 - try the next client
            errors.append(f"{label}: {error}")
            continue
        if data.get("subtitles") or data.get("automatic_captions"):
            log(f"listing via {label} client")
            return data
        errors.append(f"{label}: no caption tracks in the listing")
    raise RuntimeError(" | ".join(errors))


def fetch_listing(url: str, video_id: str, report_path: Path) -> dict:
    """Fetch the player metadata, re-selecting the proxy when the first one dies.

    A free proxy that carried the source download can be gone minutes later;
    the caption stage must not inherit that failure.  The fallback uses the
    same yt-dlp request, so a proxy is only accepted when YouTube actually
    serves this video through it.
    """
    errors: list[str] = []
    try:
        return try_listing(url)
    except Exception as error:  # noqa: BLE001 - retry with another proxy
        errors.append(str(error))

    try:
        import select_working_proxy as picker  # noqa: E402 - sibling helper

        selected = picker.pick(
            video_id,
            Path("work/download-report.json"),
            candidates=40,
            verify=6,
            timeout=45.0,
        )
    except Exception as error:  # noqa: BLE001 - the retry must never mask the cause
        errors.append(f"proxy re-selection failed: {error}")
        selected = None
    if selected:
        os.environ["YTDLP_PROXY"] = selected[0]
        log(f"listing retry through {selected[0]} ({selected[1]})")
        try:
            return try_listing(url)
        except Exception as error:  # noqa: BLE001 - report the combined failure
            errors.append(str(error))

    message = " | ".join(errors) or "no listing"
    write_report(
        report_path,
        video_id,
        {
            "en-orig": {"present": False, "formats": [], "error": message},
            "zh-Hans": {"present": False, "formats": [], "error": message},
        },
        error=message,
    )
    raise RuntimeError(f"could not read the YouTube caption listing: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download all published YouTube caption formats")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--groups", default="en,zh")
    parser.add_argument("--wait", type=int, default=0, help="Seconds between subtitle requests")
    parser.add_argument("--report", default="")
    parser.add_argument("--require", default="", help="Comma separated canonical codes that must exist")
    args = parser.parse_args()

    url = f"https://www.youtube.com/watch?v={args.video_id}"
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = Path(args.report) if args.report else directory / "CAPTION_FORMATS.json"

    metadata = fetch_listing(url, args.video_id, target)
    log(f"listing: {len(metadata.get('subtitles') or {})} manual, "
        f"{len(metadata.get('automatic_captions') or {})} automatic tracks")

    report: dict = {
        "video_id": args.video_id,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "youtube",
        "tracks": {},
        "available_languages": sorted(
            set(metadata.get("subtitles") or {}) | set(metadata.get("automatic_captions") or {})
        ),
    }

    for group in [item.strip() for item in args.groups.split(",") if item.strip()]:
        canonical = CANONICAL[group]
        resolved = resolve(metadata, group)
        if not resolved:
            log(f"{group}: YouTube publishes no caption track")
            report["tracks"][canonical] = {"present": False, "formats": []}
            continue
        code, kind = resolved
        formats = sorted(set(
            captions.track_formats(metadata.get("subtitles") or {}, code)
            + captions.track_formats(metadata.get("automatic_captions") or {}, code)
        ))
        log(f"{group}: using {code} ({kind}) with {', '.join(formats) or 'no formats'}")
        files: list[Path] = []
        download_error = ""
        try:
            files, _cues, _source = captions.download_track(
                url, args.video_id, code, kind, directory, args.wait, formats
            )
        except Exception as error:  # noqa: BLE001 - a missing track is a normal outcome
            download_error = str(error)
            log(f"{group}: download failed: {error}")

        # The listing above already carries signed timedtext URLs.  When
        # yt-dlp loses the subtitle request to a bot check, fetch the missing
        # serializations directly so all seven formats can still be kept.
        entries: list[dict] = []
        for table in (
            metadata.get("subtitles") or {},
            metadata.get("automatic_captions") or {},
        ):
            entries.extend(
                entry
                for entry in (table.get(code) or [])
                if isinstance(entry, dict)
            )
        by_extension = {
            str(entry["ext"]): str(entry["url"])
            for entry in entries
            if entry.get("ext") and entry.get("url")
        }
        existing = {
            path.suffix.lstrip(".").lower(): path
            for path in directory.glob(f"{args.video_id}.*")
            if path.is_file() and code.lower() in path.name.lower()
        }
        for extension in formats:
            if extension.lower() in existing:
                continue
            url_for_format = by_extension.get(extension)
            if not url_for_format:
                continue
            target = directory / f"{args.video_id}.{code}.{extension}"
            try:
                log(f"{group}: direct timedtext fallback for {extension}")
                download_caption_url(url_for_format, target)
                files.append(target)
                existing[extension.lower()] = target
            except Exception as error:  # noqa: BLE001 - keep trying other formats
                log(f"{group}: direct {extension} failed: {error}")
        files = [path for path in files if path.is_file()]
        files.extend(
            path
            for path in existing.values()
            if path.is_file() and path not in files
        )
        if not files:
            report["tracks"][canonical] = {
                "present": False,
                "formats": [],
                "error": download_error or "no caption serialization downloaded",
            }
            continue
        files = rename_to_canonical(files, args.video_id, code, canonical)
        written = sorted({path.suffix.lstrip(".") for path in files})
        log(f"{group}: wrote {', '.join(written)}")
        report["tracks"][canonical] = {
            "present": True,
            "youtube_code": code,
            "kind": kind,
            "source_formats": formats,
            "formats": written,
            "files": [path.name for path in files],
            "missing_formats": [
                extension
                for extension in captions.CAPTION_FORMATS
                if extension not in written
            ],
        }

    required = [item.strip() for item in args.require.split(",") if item.strip()]
    missing = [code for code in required if not report["tracks"].get(code, {}).get("present")]
    report["required"] = required
    report["missing"] = missing

    target = Path(args.report) if args.report else directory / "CAPTION_FORMATS.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"report: {target}")
    if missing:
        log(f"missing required tracks: {', '.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
