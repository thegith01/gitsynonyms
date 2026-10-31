#!/usr/bin/env python3
"""Absolute-time, live-status and delay verification for event videos.

This is the gate owned by 模块1 事件分析处 绝对时间科.  A video that carries an
absolute time marker (an on-screen clock, a scheduled start in the description,
platform live metadata, a transcript timestamp or an official calendar) is only
"confirmed" when at least three independent clock channels agree.  A missing
channel is reported as ``unverified``/``unknown`` and is never promoted to
``ok`` (DIRECTIVE.md 第七条).

Two independent branches of the same event corroborate each other, but a reprint
of the same press release does not count as a second source.  Stream latency is
kept separate from schedule lead: if the stream has already ended there is no
live edge to measure, so the latency is ``null`` with an explicit reason.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import statistics
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

SCHEMA = "gitsynonyms.time-verification/2"
UA = "Mozilla/5.0 (compatible; gitsynonyms-time-verification/1.0)"
UTC = timezone.utc
ET = ZoneInfo("America/New_York")
REQUIRED_CLOCK_CHANNELS = 3
NTP_EPOCH_DELTA = 2_208_988_800

DEFAULT_HTTP_CLOCKS = (
    ("google-date", "google", "https://www.google.com/generate_204"),
    ("cloudflare-date", "cloudflare", "https://www.cloudflare.com/cdn-cgi/trace"),
    ("github-date", "github", "https://api.github.com"),
    ("apple-date", "apple", "https://www.apple.com"),
)
DEFAULT_NTP_HOSTS = ("pool.ntp.org", "time.cloudflare.com", "time.google.com")
DEFAULT_WORLDTIME = ("worldtimeapi", "worldtimeapi", "https://worldtimeapi.org/api/timezone/Etc/UTC")

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
CLOCK_PATTERN = re.compile(
    r"(?:(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})"
    r"(?:,?\s+at)?\s*)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<ampm>am|pm)?\s*(?P<zone>EDT|EST|ET|UTC|GMT)?",
    re.IGNORECASE,
)


@dataclass
class ClockReading:
    """One independent clock channel and its uncertainty."""

    source: str
    operator: str
    kind: str
    status: str = "unknown"
    utc: datetime | None = None
    uncertainty_ms: int = 0
    rtt_ms: int = 0
    url: str = ""
    detail: str = ""
    independent: bool = True
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_json(self) -> dict:
        return {
            "source": self.source,
            "operator": self.operator,
            "kind": self.kind,
            "status": self.status,
            "utc": iso(self.utc),
            "uncertainty_ms": self.uncertainty_ms,
            "rtt_ms": self.rtt_ms,
            "url": self.url,
            "detail": self.detail,
            "independent": self.independent,
            "observed_at": iso(self.observed_at),
        }


def iso(moment: datetime | None) -> str:
    if moment is None:
        return ""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_et(moment: datetime | None) -> str:
    if moment is None:
        return ""
    return moment.astimezone(ET).isoformat(timespec="seconds")


def parse_clock(value: str | datetime, tz: ZoneInfo = ET) -> datetime:
    """Parse an absolute time, defaulting unspecified zones to US Eastern.

    Accepts ISO-8601, ``5:30 PM ET`` and ``October 29, 2026, at 5:30 PM EDT``.
    A date-only value is rejected: an event date is not an absolute clock time.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
    text = (value or "").strip()
    if not text:
        raise ValueError("empty time")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        # A bare calendar date (2026-10-29) is not an absolute clock reading.
        if "T" not in text and ":" not in text and " " not in text:
            raise ValueError(f"date without a clock time: {value!r}")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed

    match = CLOCK_PATTERN.search(text)
    if not match:
        raise ValueError(f"cannot parse absolute time: {value!r}")
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    ampm = (match.group("ampm") or "").lower()
    if not (ampm or ":" in text):
        raise ValueError(f"date without a clock time: {value!r}")
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"out of range time: {value!r}")
    if match.group("month"):
        month = MONTHS.get(match.group("month").lower())
        if month is None:
            raise ValueError(f"unknown month: {value!r}")
        day = int(match.group("day"))
        year = int(match.group("year"))
    else:
        today = datetime.now(ET)
        month, day, year = today.month, today.day, today.year
    zone = (match.group("zone") or "").upper()
    if zone in {"UTC", "GMT"}:
        return datetime(year, month, day, hour, minute, tzinfo=UTC)
    return datetime(year, month, day, hour, minute, tzinfo=tz)


def _headers_for(url: str, timeout: int) -> tuple[object | None, str]:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": UA, "Cache-Control": "no-cache", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.headers, ""
    except urllib.error.HTTPError as error:
        return error.headers, f"HTTP {error.code}"
    except Exception as error:  # noqa: BLE001 - a dead clock must not stop the run
        return None, f"{type(error).__name__}: {error}"


def read_http_date(
    source: str,
    operator: str,
    url: str,
    *,
    timeout: int = 8,
) -> ClockReading:
    """Read a server's ``Date`` header and bound the result by the round trip."""
    started = time.time()
    headers, note = _headers_for(url, timeout)
    finished = time.time()
    rtt_ms = int((finished - started) * 1000)
    if headers is None:
        return ClockReading(source, operator, "http-date", "fail", url=url,
                            rtt_ms=rtt_ms, detail=note)
    raw = headers.get("Date")
    if not raw:
        return ClockReading(source, operator, "http-date", "fail", url=url,
                            rtt_ms=rtt_ms, detail="missing Date header")
    try:
        server = parsedate_to_datetime(raw)
    except (TypeError, ValueError) as error:
        return ClockReading(source, operator, "http-date", "fail", url=url,
                            rtt_ms=rtt_ms, detail=f"bad Date header: {error}")
    if server.tzinfo is None:
        server = server.replace(tzinfo=UTC)
    age = 0
    try:
        age = max(0, int(headers.get("Age") or 0))
    except ValueError:
        pass
    # Date has one-second resolution; the request midpoint is the best estimate
    # of when the server generated it.  Report the residual half-RTT as error.
    estimate = server + timedelta(seconds=age + (finished - started) / 2)
    return ClockReading(
        source, operator, "http-date", "ok", estimate,
        uncertainty_ms=1000 + rtt_ms // 2, rtt_ms=rtt_ms, url=url,
        detail=f"Date={raw}" + (f", Age={age}" if age else ""),
    )


def _ntp_timestamp(value: float) -> bytes:
    seconds = int(value) + NTP_EPOCH_DELTA
    fraction = int((value - int(value)) * (1 << 32))
    return struct.pack("!II", seconds, fraction)


def _from_ntp(packet: bytes, offset: int) -> float:
    seconds, fraction = struct.unpack("!II", packet[offset:offset + 8])
    return (seconds - NTP_EPOCH_DELTA) + fraction / (1 << 32)


def read_ntp(host: str, *, timeout: int = 3) -> ClockReading:
    """Read one SNTP server; the offset is bounded by the measured delay."""
    packet = bytearray(48)
    packet[0] = 0x1B  # leap=0, version=3, mode=3 (client)
    t1 = time.time()
    packet[40:48] = _ntp_timestamp(t1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(bytes(packet), (host, 123))
        response, _ = sock.recvfrom(1024)
        t4 = time.time()
    except Exception as error:  # noqa: BLE001 - UDP is often blocked
        return ClockReading(f"ntp:{host}", f"ntp:{host}", "ntp", "fail",
                            detail=f"{type(error).__name__}: {error}")
    finally:
        sock.close()
    if len(response) < 48:
        return ClockReading(f"ntp:{host}", f"ntp:{host}", "ntp", "fail",
                            detail=f"short NTP response ({len(response)} bytes)")
    mode = response[0] & 0x07
    stratum = response[1]
    if mode not in (4, 5) or stratum == 0 or stratum > 15:
        return ClockReading(f"ntp:{host}", f"ntp:{host}", "ntp", "fail",
                            detail=f"mode={mode}, stratum={stratum}")
    t2 = _from_ntp(response, 32)
    t3 = _from_ntp(response, 40)
    offset = ((t2 - t1) + (t3 - t4)) / 2
    delay = (t4 - t1) - (t3 - t2)
    estimate = datetime.fromtimestamp(t4 + offset, UTC)
    return ClockReading(
        f"ntp:{host}", f"ntp:{host}", "ntp", "ok", estimate,
        uncertainty_ms=max(1, int(delay * 1000 / 2)),
        rtt_ms=int(delay * 1000),
        url=f"udp://{host}:123",
        detail=f"stratum={stratum}, offset={offset * 1000:+.1f}ms",
    )


def read_worldtime(
    source: str, operator: str, url: str, *, timeout: int = 8
) -> ClockReading:
    """Read an HTTP JSON clock (WorldTimeAPI-compatible payload)."""
    started = time.time()
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        finished = time.time()
    except Exception as error:  # noqa: BLE001
        return ClockReading(source, operator, "http-json", "fail", url=url,
                            detail=f"{type(error).__name__}: {error}")
    raw = payload.get("utc_datetime") or payload.get("datetime") or ""
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ClockReading(source, operator, "http-json", "fail", url=url,
                            detail="missing utc_datetime")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    rtt_ms = int((finished - started) * 1000)
    return ClockReading(
        source, operator, "http-json", "ok",
        moment + timedelta(milliseconds=rtt_ms / 2),
        uncertainty_ms=500 + rtt_ms // 2, rtt_ms=rtt_ms, url=url,
        detail=f"utc_datetime={raw}",
    )


def read_system_clock() -> ClockReading:
    """The local clock is recorded for comparison, never counted as independent."""
    return ClockReading(
        "system", "local", "system", "ok", datetime.now(UTC),
        uncertainty_ms=1000, url="", detail="local wall clock", independent=False,
    )


def collect_clocks(
    http_clocks: Iterable[tuple[str, str, str]] = DEFAULT_HTTP_CLOCKS,
    ntp_hosts: Iterable[str] = DEFAULT_NTP_HOSTS,
    worldtime: tuple[str, str, str] | None = DEFAULT_WORLDTIME,
) -> list[ClockReading]:
    """Probe every clock channel concurrently; dead channels stay as failures."""
    readings: list[ClockReading] = []
    jobs = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for source, operator, url in http_clocks:
            jobs.append((pool.submit(read_http_date, source, operator, url), len(readings)))
            readings.append(ClockReading(source, operator, "http-date"))
        for host in ntp_hosts:
            jobs.append((pool.submit(read_ntp, host), len(readings)))
            readings.append(ClockReading(f"ntp:{host}", f"ntp:{host}", "ntp"))
        if worldtime:
            jobs.append((pool.submit(read_worldtime, *worldtime), len(readings)))
            readings.append(ClockReading(worldtime[0], worldtime[1], "http-json"))
        for future, position in jobs:
            try:
                readings[position] = future.result()
            except Exception as error:  # noqa: BLE001 - keep the failure record
                readings[position].status = "fail"
                readings[position].detail = f"{type(error).__name__}: {error}"
    readings.append(read_system_clock())
    return readings


def consensus(readings: Iterable[ClockReading], required: int = REQUIRED_CLOCK_CHANNELS) -> dict:
    """Build one consensus clock from distinct independent operators.

    Only one reading per operator is kept, so two services run by the same
    company do not fake a second channel.  Fewer than ``required`` survivors is
    ``unverified`` even when the available clocks happen to agree.
    """
    usable = [r for r in readings if r.status == "ok" and r.utc is not None and r.independent]
    by_operator: dict[str, ClockReading] = {}
    for reading in usable:
        current = by_operator.get(reading.operator)
        if current is None or reading.uncertainty_ms < current.uncertainty_ms:
            by_operator[reading.operator] = reading
    selected = list(by_operator.values())
    system = next((r for r in readings if r.kind == "system" and r.utc), None)
    if len(selected) < required:
        return {
            "status": "unverified",
            "reason": f"{len(selected)} independent clock channels, {required} required",
            "required": required,
            "channels_ok": len(selected),
            "operators": sorted(by_operator),
            "consensus_utc": iso(datetime.fromtimestamp(
                statistics.median([r.utc.timestamp() for r in selected]), UTC
            )) if selected else "",
            "uncertainty_ms": 0,
            "spread_ms": 0,
            "system_offset_ms": None,
            "sources": [r.to_json() for r in readings],
        }
    values = [r.utc.timestamp() for r in selected]
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations)
    limit = max(2.0, 4.0 * mad)
    kept = [r for r, value in zip(selected, values) if abs(value - median) <= limit]
    if len(kept) < required:
        return {
            "status": "unverified",
            "reason": f"outlier rejection left {len(kept)} channels, {required} required",
            "required": required,
            "channels_ok": len(kept),
            "operators": sorted(r.operator for r in kept),
            "consensus_utc": "",
            "uncertainty_ms": 0,
            "spread_ms": 0,
            "system_offset_ms": None,
            "sources": [r.to_json() for r in readings],
        }
    kept_values = [r.utc.timestamp() for r in kept]
    centre = statistics.median(kept_values)
    spread_ms = int((max(kept_values) - min(kept_values)) * 1000)
    uncertainty = max(
        max(r.uncertainty_ms for r in kept),
        int(statistics.median([abs(v - centre) for v in kept_values]) * 1000),
        1,
    )
    consensus_dt = datetime.fromtimestamp(centre, UTC)
    return {
        "status": "verified" if spread_ms <= 5000 else "degraded",
        "reason": "" if spread_ms <= 5000 else f"clock spread {spread_ms}ms exceeds 5000ms",
        "required": required,
        "channels_ok": len(kept),
        "operators": sorted(r.operator for r in kept),
        "consensus_utc": iso(consensus_dt),
        "consensus_et": iso_et(consensus_dt),
        "uncertainty_ms": uncertainty,
        "spread_ms": spread_ms,
        "system_offset_ms": int((system.utc - consensus_dt).total_seconds() * 1000) if system else None,
        "sources": [r.to_json() for r in readings],
    }


LIVE_MAP = {
    "is_live": "live",
    "live": "live",
    "is_upcoming": "upcoming",
    "upcoming": "upcoming",
    "was_live": "ended_live",
    "post_live": "ended_live",
    "not_live": "vod",
    "vod": "vod",
}


def live_status(meta: dict) -> dict:
    """Map platform metadata to a live verdict without trusting a title alone."""
    raw = str(meta.get("live_status") or meta.get("status") or "").lower()
    status = LIVE_MAP.get(raw, "unknown")
    title = str(meta.get("title") or "")
    description = str(meta.get("description") or "")
    hints = []
    if re.search(r"\bLIVE\s+REPLAY\b|\bREPLAY\b", title, re.IGNORECASE):
        hints.append("title_replay")
    elif re.search(r"\bLIVE\b", title, re.IGNORECASE):
        hints.append("title_live")
    if re.search(r"streamed live|was live|live replay", description, re.IGNORECASE):
        hints.append("description_live_past")
    if status == "unknown" and "title_replay" in hints:
        status = "ended_live"
    if status == "unknown" and "title_live" in hints:
        status = "unknown"  # a title claiming LIVE is not proof
    return {
        "status": status,
        "raw": raw,
        "hints": hints,
        "at_verification_live": status == "live",
        "was_live": status in {"live", "ended_live"},
        "authoritative": status != "unknown",
    }


def _schedule_anchor(entry: dict) -> dict:
    moment = parse_clock(str(entry.get("time") or ""))
    return {
        "source": str(entry.get("source") or ""),
        "url": str(entry.get("url") or ""),
        "time_et": iso_et(moment),
        "time_utc": iso(moment),
        "kind": str(entry.get("kind") or "schedule"),
        "note": str(entry.get("note") or ""),
        "independent": bool(entry.get("independent", True)),
    }


def verify_event(evidence: dict, clocks: dict, *, required: int = REQUIRED_CLOCK_CHANNELS) -> dict:
    """Cross-check one event's videos, schedules and absolute clock markers."""
    event_id = str(evidence.get("event_id") or "event")
    tz = ZoneInfo(str(evidence.get("timezone") or "America/New_York"))

    videos = []
    overlays = []
    for entry in evidence.get("videos", []):
        meta = dict(entry)
        verdict = live_status(meta)
        started = None
        if entry.get("started_at"):
            try:
                started = parse_clock(str(entry["started_at"]), tz)
            except ValueError:
                started = None
        duration = int(entry.get("duration_s") or 0)
        ended = started + timedelta(seconds=duration) if started and duration else None
        video_overlays = []
        for reading in entry.get("overlay_readings") or []:
            try:
                clock = parse_clock(str(reading.get("clock") or ""), tz)
            except ValueError:
                continue
            offset = reading.get("offset_s")
            skew = None
            if started is not None and offset is not None:
                expected = started + timedelta(seconds=float(offset))
                skew = (expected - clock).total_seconds()
            item = {
                "clock_et": iso_et(clock),
                "clock_utc": iso(clock),
                "offset_s": offset,
                "frame": str(reading.get("frame") or ""),
                "clock_skew_s": skew,
                "source": str(entry.get("source") or ""),
                "video_id": str(entry.get("id") or ""),
            }
            video_overlays.append(item)
            overlays.append(item)
        videos.append({
            "id": str(entry.get("id") or ""),
            "title": str(entry.get("title") or ""),
            "source": str(entry.get("source") or ""),
            "url": str(entry.get("url") or ""),
            "live": verdict,
            "started_at_et": iso_et(started),
            "started_at_utc": iso(started),
            "duration_s": duration,
            "ended_at_et": iso_et(ended),
            "description_time_et": iso_et(parse_clock(str(entry["description_time"]), tz))
            if entry.get("description_time") else "",
            "overlays": video_overlays,
            "evidence": list(entry.get("evidence") or []),
        })

    schedules = [_schedule_anchor(item) for item in evidence.get("schedules", [])]
    articles = []
    for item in evidence.get("articles", []):
        try:
            published = parse_clock(str(item.get("published") or ""), tz)
        except ValueError:
            continue
        articles.append({
            "source": str(item.get("source") or ""),
            "url": str(item.get("url") or ""),
            "published_et": iso_et(published),
            "published_utc": iso(published),
            "note": str(item.get("note") or ""),
        })

    reference = None
    if schedules:
        reference = sorted(
            datetime.fromisoformat(item["time_utc"].replace("Z", "+00:00"))
            for item in schedules
        )[len(schedules) // 2]
    elif overlays:
        reference = datetime.fromisoformat(overlays[0]["clock_utc"].replace("Z", "+00:00"))

    tolerance = int(evidence.get("tolerance_s") or 900)
    agreeing = []
    for item in schedules:
        moment = datetime.fromisoformat(item["time_utc"].replace("Z", "+00:00"))
        delta = (moment - reference).total_seconds() if reference else 0
        item["delta_s"] = int(delta)
        if abs(delta) <= tolerance:
            agreeing.append(item)
    distinct = {item["source"] for item in agreeing if item["independent"]}
    event_confirmed = (
        len(distinct) >= required
        and clocks.get("status") in {"verified", "degraded"}
    )
    event_start_et = iso_et(reference) if reference else ""
    event_start_utc = iso(reference) if reference else ""

    statuses = {video["live"]["status"] for video in videos}
    if "live" in statuses:
        overall_live = "live"
    elif statuses and statuses <= {"ended_live", "unknown"} and "ended_live" in statuses:
        overall_live = "ended_live"
    elif statuses and statuses <= {"vod"}:
        overall_live = "vod"
    elif "upcoming" in statuses:
        overall_live = "upcoming"
    else:
        overall_live = "unknown"
    if len(statuses - {"unknown"}) > 1:
        overall_live = "conflict"

    coverage = next((v for v in videos if v["description_time_et"]), None)
    schedule_lead = None
    if reference and coverage and coverage["description_time_et"]:
        coverage_dt = parse_clock(coverage["description_time_et"], tz)
        schedule_lead = int((reference - coverage_dt).total_seconds())

    measured_skew = [item["clock_skew_s"] for item in overlays if item["clock_skew_s"] is not None]
    live_edge = evidence.get("live_edge")
    latency = None
    latency_reason = ""
    if live_edge and clocks.get("consensus_utc"):
        try:
            edge = parse_clock(str(live_edge.get("clock") or ""), tz)
            now = datetime.fromisoformat(str(clocks["consensus_utc"]).replace("Z", "+00:00"))
            latency = int((now - edge).total_seconds())
            latency_reason = "measured against the live edge and the clock consensus"
        except ValueError:
            latency_reason = "live edge unreadable"
    elif overall_live == "live":
        latency_reason = "live stream present but no live-edge clock supplied"
    else:
        latency_reason = "stream ended; no live edge remains to measure"

    checks = {
        "three_clock_channels": clocks.get("channels_ok", 0) >= required
        and clocks.get("status") in {"verified", "degraded"},
        "three_event_sources": len(distinct) >= required,
        "live_status_known": overall_live != "unknown",
        "latency_measured": latency is not None,
    }
    confidence = "low"
    if event_confirmed and checks["three_clock_channels"]:
        confidence = "high" if len(distinct) >= 4 else "medium"

    return {
        "schema": SCHEMA,
        "event_id": event_id,
        "generated_at": iso(datetime.now(UTC)),
        "timezone": str(tz),
        "clocks": clocks,
        "videos": videos,
        "overlays": overlays,
        "schedules": schedules,
        "articles": articles,
        "absolute_time": {
            "event_start_et": event_start_et,
            "event_start_utc": event_start_utc,
            "window_et": [
                min((item["time_et"] for item in schedules), default=""),
                max((item["time_et"] for item in schedules), default=""),
            ],
            "status": "confirmed" if event_confirmed else "unverified",
            "distinct_sources": sorted(distinct),
            "source_count": len(distinct),
            "tolerance_s": tolerance,
            "checked_against_clock": clocks.get("status") in {"verified", "degraded"},
        },
        "live_status": {
            "at_verification": overall_live,
            "was_live": any(video["live"]["was_live"] for video in videos),
            "videos": {video["id"]: video["live"] for video in videos},
            "conflict": overall_live == "conflict",
        },
        "delay": {
            "stream_latency_s": latency,
            "latency_status": "measured" if latency is not None else "unknown",
            "latency_reason": latency_reason,
            "schedule_lead_s": schedule_lead,
            "schedule_lead_reason": (
                "event start minus coverage start; this is pre-show lead, not glass-to-glass latency"
                if schedule_lead is not None else ""
            ),
            "clock_skew_s": int(statistics.median(measured_skew)) if measured_skew else None,
            "clock_skew_samples": len(measured_skew),
            "uncertainty_ms": clocks.get("uncertainty_ms", 0),
        },
        "checks": checks,
        "confidence": confidence,
    }


def render_markdown(report: dict) -> str:
    """Human-readable audit sheet for docs/events/<event-id>.md."""
    absolute = report["absolute_time"]
    live = report["live_status"]
    delay = report["delay"]
    clocks = report["clocks"]
    lines = [
        f"## 绝对时间核验：{report['event_id']}",
        "",
        f"- 核验时间（UTC）：`{report['generated_at']}`",
        f"- 事件绝对时间（美东）：**{absolute['event_start_et'] or '未确认'}**",
        f"- 事件绝对时间（UTC）：`{absolute['event_start_utc'] or '未确认'}`",
        f"- 绝对时间判定：**{absolute['status']}**（{absolute['source_count']} 个独立来源）",
        f"- 直播状态：**{live['at_verification']}**（曾直播：{live['was_live']}）",
        f"- 流媒体延迟：**{delay['stream_latency_s'] if delay['stream_latency_s'] is not None else 'unknown'}**"
        f"（{delay['latency_reason']}）",
        f"- 时段提前量：{delay['schedule_lead_s']} 秒（节目开始到事件开始，不是传输延迟）",
        f"- 置信度：**{report['confidence']}**",
        "",
        "### 时钟源",
        "",
        "| 渠道 | 运营商 | 类型 | 读数（UTC） | 不确定度 | 状态 |",
        "|---|---|---|---:|---:|---|",
    ]
    for source in clocks.get("sources", []):
        lines.append(
            f"| {source['source']} | {source['operator']} | {source['kind']} | "
            f"{source['utc'] or '—'} | {source['uncertainty_ms']} ms | {source['status']} |"
        )
    lines.extend([
        "",
        f"时钟共识：`{clocks.get('consensus_utc') or '未达成'}`，"
        f"渠道 {clocks.get('channels_ok', 0)}/{clocks.get('required', REQUIRED_CLOCK_CHANNELS)}，"
        f"最大偏差 {clocks.get('spread_ms', 0)} ms。",
        "",
        "### 视频分支",
        "",
        "| 视频 | 来源 | 状态 | 开始（美东） | 结束（美东） | 画面/说明时间标识 |",
        "|---|---|---|---|---|---|",
    ])
    for video in report["videos"]:
        marks = [item["clock_et"] for item in video["overlays"]]
        if video.get("description_time_et"):
            marks.append(f"说明 {video['description_time_et']}")
        lines.append(
            f"| `{video['id']}` | {video['source']} | {video['live']['status']} | "
            f"{video['started_at_et'] or '—'} | {video['ended_at_et'] or '—'} | "
            f"{'；'.join(marks) or '—'} |"
        )
    lines.extend([
        "",
        "### 交叉来源",
        "",
        "| 来源 | 时间（美东） | 与参考时间差 | 链接 |",
        "|---|---|---:|---|",
    ])
    for item in report["schedules"]:
        lines.append(
            f"| {item['source']} | {item['time_et']} | {item.get('delta_s', 0)} s | {item['url']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Absolute-time, live-status and delay verification")
    sub = parser.add_subparsers(dest="command", required=True)
    clock_parser = sub.add_parser("clock", help="probe independent clock channels")
    clock_parser.add_argument("--report", default="")
    clock_parser.add_argument("--require", type=int, default=REQUIRED_CLOCK_CHANNELS)
    verify_parser = sub.add_parser("verify", help="verify one event evidence file")
    verify_parser.add_argument("--evidence", required=True)
    verify_parser.add_argument("--report", default="")
    verify_parser.add_argument("--markdown", default="")
    verify_parser.add_argument("--require", type=int, default=REQUIRED_CLOCK_CHANNELS)
    args = parser.parse_args()

    clocks = consensus(collect_clocks())
    if args.command == "clock":
        payload = {"schema": SCHEMA, "generated_at": iso(datetime.now(UTC)), "clocks": clocks}
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        print(text)
        if args.report:
            Path(args.report).write_text(text + "\n", encoding="utf-8")
        return 0 if clocks["status"] in {"verified", "degraded"} else 2

    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    report = verify_event(evidence, clocks, required=args.require)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text(render_markdown(report) + "\n", encoding="utf-8")
    return 0 if report["checks"]["three_clock_channels"] else 2


if __name__ == "__main__":
    sys.exit(main())
