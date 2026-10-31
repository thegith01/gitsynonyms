#!/usr/bin/env python3
"""Resolve the next White House video the monitor should process.

The channel has two separate YouTube tabs and both are authoritative:

* ``/videos``  - regular uploads and short clips;
* ``/streams`` - live events and their replays.

A stream replay can exist only on the second tab (an ended live event is not
always copied into ``/videos``), so scanning only ``/videos`` silently misses
material that is explicitly designated in ``resources/registry.json``.  This
resolver scans both tabs, merges the two newest-first listings, and picks the
newest unprocessed candidate.

Two guard rails keep the five-minute monitor moving:

* currently-live or upcoming entries are skipped (there is no finished file to
  download yet);
* an upload that keeps failing is quarantined after ``MAX_ATTEMPTS`` failures
  for ``RETRY_COOLDOWN_HOURS`` so one broken video cannot starve the channel.

The resolver is deliberately side-effect free with respect to the attempt
ledger.  The workflow records failures and clears them on success through the
``--record-failure`` / ``--clear-failure`` modes, which keeps the scan itself
deterministic and testable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
PROCESSED_FILE = ROOT / ".github" / "state" / "whitehouse-processed-videos.txt"
ATTEMPTS_FILE = ROOT / ".github" / "state" / "whitehouse-attempts.json"

TABS = ("videos", "streams")
TAB_URLS = {
    "videos": "https://www.youtube.com/@WhiteHouse/videos",
    "streams": "https://www.youtube.com/@WhiteHouse/streams",
}
# Ties go to the streams tab: a full event is more useful than a short clip
# published on the same day.
TAB_PRIORITY = {"streams": 0, "videos": 1}

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYER_CLIENTS = ("default", "tv", "mweb", "web_safari")
LIVE_STATUSES = {"is_live", "is_upcoming"}

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
MONTH_DATE = re.compile(
    r"\b(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\.?\s+"
    r"(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
ISO_DATE = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b")


class ScanError(RuntimeError):
    """A channel tab could not be read."""


@dataclass(frozen=True)
class Candidate:
    video_id: str
    title: str
    tab: str
    rank: int
    live_status: str = ""
    duration: Optional[float] = None
    published: Optional[date] = None


def parse_title_date(title: str) -> Optional[date]:
    """Return the date written in a White House title, if there is one."""
    match = MONTH_DATE.search(title or "")
    if match:
        month = MONTHS[match.group("month")[:3].lower()]
        try:
            return date(int(match.group("year")), month, int(match.group("day")))
        except ValueError:
            return None
    match = ISO_DATE.search(title or "")
    if match:
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            return None
    return None


def parse_listing(stdout: str, tab: str) -> list[Candidate]:
    """Parse the ``id<TAB>title<TAB>live_status<TAB>duration`` flat listing."""
    candidates: list[Candidate] = []
    for rank, line in enumerate(stdout.splitlines()):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        video_id = parts[0].strip()
        if not VIDEO_ID.fullmatch(video_id):
            continue
        if len(parts) >= 4:
            title = "\t".join(parts[1:-2]).strip()
            live_status = parts[-2].strip()
            duration_text = parts[-1].strip()
        else:
            title = "\t".join(parts[1:]).strip()
            live_status = ""
            duration_text = ""
        duration: Optional[float]
        try:
            duration = float(duration_text)
        except (TypeError, ValueError):
            duration = None
        candidates.append(
            Candidate(
                video_id=video_id,
                title=title or video_id,
                tab=tab,
                rank=rank,
                live_status=live_status,
                duration=duration,
                published=parse_title_date(title),
            )
        )
    return candidates


def infer_dates(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Fill missing dates from the nearest dated entry below them.

    Both channel tabs are ordered newest first.  For an undated entry, the
    next dated entry below it is a conservative lower bound on its real date.
    Entries below every dated entry keep no date and sort last.  This is what
    lets a dated stream (Oct. 30) outrank an undated short clip (e.g. "Hello,
    America") without inventing a precise timestamp.
    """
    by_tab: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        by_tab.setdefault(candidate.tab, []).append(candidate)

    inferred: dict[tuple[str, str], date] = {}
    for tab, entries in by_tab.items():
        upcoming: Optional[date] = None
        for candidate in sorted(entries, key=lambda item: item.rank, reverse=True):
            if candidate.published is not None:
                upcoming = candidate.published
            elif upcoming is not None:
                inferred[(tab, candidate.video_id)] = upcoming

    result: list[Candidate] = []
    for candidate in candidates:
        if candidate.published is not None:
            result.append(candidate)
        else:
            result.append(
                replace(
                    candidate,
                    published=inferred.get((candidate.tab, candidate.video_id)),
                )
            )
    return result


def deduplicate(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Keep one record per video, preferring the streams tab on a duplicate."""
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        current = best.get(candidate.video_id)
        if current is None or (
            TAB_PRIORITY.get(candidate.tab, 99),
            candidate.rank,
        ) < (
            TAB_PRIORITY.get(current.tab, 99),
            current.rank,
        ):
            best[candidate.video_id] = candidate
    return list(best.values())


def parse_timestamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def quarantine_remaining(
    record: Optional[Mapping[str, object]],
    *,
    now: datetime,
    max_attempts: int,
    cooldown: timedelta,
) -> Optional[timedelta]:
    """Return how long a repeatedly failing upload is still quarantined."""
    if not record:
        return None
    try:
        attempts = int(record.get("attempts", 0))
    except (TypeError, ValueError):
        attempts = 0
    if attempts < max_attempts:
        return None
    last_attempt = parse_timestamp(record.get("last_attempt"))
    if last_attempt is None:
        return None
    remaining = cooldown - (now - last_attempt)
    return remaining if remaining > timedelta(0) else None


def candidate_sort_key(candidate: Candidate) -> tuple:
    # Newest date first; on a tie streams before videos, then the earlier rank.
    return (
        candidate.published or date.min,
        -TAB_PRIORITY.get(candidate.tab, 99),
        -candidate.rank,
    )


def choose_candidate(
    candidates: Sequence[Candidate],
    *,
    processed: Iterable[str],
    attempts: Mapping[str, Mapping[str, object]],
    now: datetime,
    max_attempts: int = 3,
    cooldown: timedelta = timedelta(hours=6),
    force_check: bool = False,
) -> Optional[Candidate]:
    """Pick the newest candidate that is not processed, live or quarantined."""
    processed_ids = set(processed)
    ordered = sorted(
        infer_dates(deduplicate(candidates)),
        key=candidate_sort_key,
        reverse=True,
    )
    for candidate in ordered:
        if candidate.live_status in LIVE_STATUSES:
            continue
        if not force_check and candidate.video_id in processed_ids:
            continue
        if quarantine_remaining(
            attempts.get(candidate.video_id),
            now=now,
            max_attempts=max_attempts,
            cooldown=cooldown,
        ) is not None:
            continue
        return candidate
    return None


def load_processed(path: Path = PROCESSED_FILE) -> set[str]:
    if not path.exists():
        return set()
    result: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if VIDEO_ID.fullmatch(value):
            result.add(value)
    return result


def load_attempts(path: Path = ATTEMPTS_FILE) -> dict:
    if not path.exists():
        return {"version": 1, "videos": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"::warning::could not read attempt state {path}: {error}", file=sys.stderr)
        return {"version": 1, "videos": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("videos"), dict):
        print(f"::warning::attempt state {path} has an unexpected shape", file=sys.stderr)
        return {"version": 1, "videos": {}}
    payload.setdefault("version", 1)
    return payload


def write_attempts(payload: dict, path: Path = ATTEMPTS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def record_failure(
    video_id: str,
    *,
    path: Path = ATTEMPTS_FILE,
    now: Optional[datetime] = None,
    reason: str = "pipeline",
) -> dict:
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError(f"invalid YouTube video id: {video_id!r}")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = load_attempts(path)
    videos = payload.setdefault("videos", {})
    record = videos.get(video_id)
    if not isinstance(record, dict):
        record = {}
    try:
        attempts = int(record.get("attempts", 0))
    except (TypeError, ValueError):
        attempts = 0
    record.update(
        {
            "attempts": attempts + 1,
            "first_attempt": record.get("first_attempt")
            or now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "last_attempt": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "last_result": reason,
        }
    )
    videos[video_id] = record
    payload["updated_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    write_attempts(payload, path)
    return payload


def clear_failure(
    video_id: str,
    *,
    path: Path = ATTEMPTS_FILE,
    now: Optional[datetime] = None,
) -> dict:
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError(f"invalid YouTube video id: {video_id!r}")
    payload = load_attempts(path)
    videos = payload.setdefault("videos", {})
    if video_id not in videos:
        return payload
    videos.pop(video_id, None)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload["updated_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    write_attempts(payload, path)
    return payload


def build_listing_command(
    yt_dlp: str,
    url: str,
    *,
    limit: int,
    client: str = "default",
    proxy: str = "",
) -> list[str]:
    command = [
        yt_dlp,
        "--no-warnings",
        "--ignore-errors",
        "--flat-playlist",
        "--playlist-end",
        str(limit),
        "--print",
        "%(id)s\t%(title)s\t%(live_status)s\t%(duration)s",
        url,
    ]
    if client != "default":
        command[1:1] = ["--extractor-args", f"youtube:player_client={client}"]
    if proxy:
        command[1:1] = ["--proxy", proxy]
    return command


def list_tab(
    tab: str,
    *,
    limit: int = 10,
    proxy: str = "",
    timeout: float = 120.0,
    runner=subprocess.run,
) -> list[Candidate]:
    """Read one tab, trying each player client until one returns entries."""
    yt_dlp = shutil.which("yt-dlp")
    if not yt_dlp:
        raise ScanError("yt-dlp is required to scan the White House channel")
    url = TAB_URLS[tab]
    errors: list[str] = []
    for client in PLAYER_CLIENTS:
        command = build_listing_command(
            yt_dlp, url, limit=limit, client=client, proxy=proxy
        )
        try:
            result = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except Exception as error:  # noqa: BLE001 - try the next client
            errors.append(f"{client}: {error}")
            continue
        if result.returncode != 0:
            errors.append(
                f"{client}: {(result.stderr or result.stdout or '').strip()}"
            )
            continue
        candidates = parse_listing(result.stdout, tab)
        if candidates:
            print(f"{tab}: {len(candidates)} candidates via {client} client")
            return candidates
        errors.append(f"{client}: no entries")
    raise ScanError(f"could not read {url}: " + " | ".join(errors))


def scan(
    *,
    include_streams: bool = True,
    limit: int = 10,
    proxy: str = "",
    timeout: float = 120.0,
    runner=subprocess.run,
) -> list[Candidate]:
    tabs = ("videos", "streams") if include_streams else ("videos",)
    candidates: list[Candidate] = []
    errors: list[str] = []
    for tab in tabs:
        try:
            candidates.extend(
                list_tab(
                    tab,
                    limit=limit,
                    proxy=proxy,
                    timeout=timeout,
                    runner=runner,
                )
            )
        except ScanError as error:
            errors.append(str(error))
            print(f"::warning::{error}", file=sys.stderr)
    if not candidates and errors:
        raise ScanError(" | ".join(errors))
    return candidates


def write_output(video_id: str, title: str) -> None:
    title = (title or video_id).replace("\r", " ").replace("\n", " ").strip()
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"video_id={video_id}\n")
            handle.write(f"video_title={title}\n")
    else:
        print(f"video_id={video_id}")
        print(f"video_title={title}")


def _int_env(name: str, default: int, *, minimum: int = 1, maximum: int = 50) -> int:
    try:
        value = int(os.environ.get(name, "").strip())
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip())
    except ValueError:
        return default


def _force_check() -> bool:
    return os.environ.get("FORCE_CHECK", "").strip().lower() in {"1", "true", "yes"}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve the next unprocessed White House YouTube video."
    )
    parser.add_argument(
        "--record-failure",
        metavar="VIDEO_ID",
        help="Increment the failure counter for one video and exit.",
    )
    parser.add_argument(
        "--clear-failure",
        metavar="VIDEO_ID",
        help="Remove the failure record for one video and exit.",
    )
    parser.add_argument(
        "--attempts-file",
        type=Path,
        default=ATTEMPTS_FILE,
        help="Attempt ledger path (default: .github/state/whitehouse-attempts.json).",
    )
    args = parser.parse_args(argv)

    if args.record_failure:
        record_failure(
            args.record_failure,
            path=args.attempts_file,
            reason=os.environ.get("FAILURE_REASON", "pipeline"),
        )
        return 0
    if args.clear_failure:
        clear_failure(args.clear_failure, path=args.attempts_file)
        return 0

    if os.environ.get("GITHUB_REF", "refs/heads/main") != "refs/heads/main":
        raise SystemExit(
            "The White House monitor must run from main to publish the site."
        )

    forced = os.environ.get("FORCE_VIDEO_ID", "").strip()
    if forced:
        if not VIDEO_ID.fullmatch(forced):
            raise SystemExit(
                "FORCE_VIDEO_ID must be an 11-character YouTube video ID: "
                + forced
            )
        print(f"Processing the operator-selected video {forced} instead of the listing.")
        write_output(forced, forced)
        return 0

    include_streams = os.environ.get("INCLUDE_STREAMS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    limit = _int_env("SCAN_LIMIT", 10, minimum=1, maximum=50)
    max_attempts = _int_env("MAX_ATTEMPTS", 3, minimum=1, maximum=20)
    cooldown = timedelta(hours=_float_env("RETRY_COOLDOWN_HOURS", 6.0))
    now = datetime.now(timezone.utc)

    candidates = scan(
        include_streams=include_streams,
        limit=limit,
        proxy=os.environ.get("YTDLP_PROXY", "").strip(),
        timeout=_float_env("SCAN_TIMEOUT_SECONDS", 120.0),
    )
    attempts = load_attempts(args.attempts_file).get("videos", {})
    selected = choose_candidate(
        candidates,
        processed=load_processed(),
        attempts=attempts,
        now=now,
        max_attempts=max_attempts,
        cooldown=cooldown,
        force_check=_force_check(),
    )

    if selected is None:
        print(
            "No unprocessed upload found in the latest entries of "
            + ", ".join(TAB_URLS[tab] for tab in (TABS if include_streams else TABS[:1]))
        )
        write_output("", "")
        return 0

    print(
        f"Discovered {selected.video_id}: {selected.title} "
        f"(tab={selected.tab}, date={selected.published or 'unknown'}, "
        f"live={selected.live_status or 'vod'})"
    )
    write_output(selected.video_id, selected.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
