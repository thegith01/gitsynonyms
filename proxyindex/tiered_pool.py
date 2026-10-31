#!/usr/bin/env python3
"""Three-tier public proxy pool with independent refresh intervals.

Tier 1 (wide, every 6 h)
    Collect up to 1,000,000 unique ``ip:port`` entries from every source in
    ``sources.txt``, then keep the ones whose TCP port actually opens.
    Output: ``pool/tier1/tier1_raw.txt`` and ``tier1/tier1_open.jsonl``.

Tier 2 (fast, every 30 min)
    Probe tier 1 through YouTube's HTTPS canary and keep the 10,000 lowest
    latency proxies.
    Output: ``pool/tier2/tier2_fast.jsonl`` and ``tier2_fast.txt``.

Tier 3 (ready, every 15 min)
    Run a real ``yt-dlp`` extraction plus a ranged media download through each
    tier 2 proxy and keep the 1,000 with the best measured throughput.
    Output: ``pool/tier3/tier3_ready.jsonl`` and ``tier3_ready.txt``.

Stages refresh in rolling batches: a scheduled run only tests candidates whose
record is missing or older than the tier's ``--max-age``, so the work per run
stays inside its slot while every entry in the pool is younger than the
declared freshness window.  The plain ``.txt`` files are what the downloader
consumes; the ``.jsonl`` sidecars keep latency, throughput and verification
time for the next run and for audit.
"""

from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POOL = ROOT / "pool"
TIER1 = POOL / "tier1"
TIER2 = POOL / "tier2"
TIER3 = POOL / "tier3"

SOURCES = ROOT / "sources.txt"
TIER1_RAW = TIER1 / "tier1_raw.txt"
TIER1_OPEN = TIER1 / "tier1_open.jsonl"
TIER1_STATS = TIER1 / "tier1_stats.json"
TIER2_RECORDS = TIER2 / "tier2_fast.jsonl"
TIER2_PLAIN = TIER2 / "tier2_fast.txt"
TIER3_RECORDS = TIER3 / "tier3_ready.jsonl"
TIER3_PLAIN = TIER3 / "tier3_ready.txt"
TIER3_FAILED = TIER3 / "tier3_failed.json"

CANARY_HTTPS = "https://www.youtube.com/generate_204"
TEST_VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
RANGE_BYTES = 128 * 1024
MAX_SOURCE_BYTES = 4_000_000
IP_PORT = re.compile(r"^(?:https?://)?(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})/?$")


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

def normalize(entry: object) -> str | None:
    """Return ``ip:port`` for a valid IPv4 proxy entry, else ``None``."""
    if not isinstance(entry, str):
        return None
    match = IP_PORT.fullmatch(entry.strip())
    if not match:
        return None
    address, port_text = match.groups()
    octets = [int(part) for part in address.split(".")]
    port = int(port_text)
    if any(octet > 255 for octet in octets) or octets[0] == 0:
        return None
    if not 1 <= port <= 65535:
        return None
    return f"{address}:{port}"


def as_url(proxy: str) -> str:
    return f"http://{proxy}"


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.is_file():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and normalize(record.get("proxy")):
            record["proxy"] = normalize(record["proxy"])
            records.append(record)
    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_plain(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{record['proxy']}\n" for record in records),
        encoding="utf-8",
        newline="\n",
    )


def merge_records(
    existing: list[dict],
    tested: list[dict],
    *,
    limit: int,
    max_age: float,
    now: float,
    sort_key: str,
    reverse: bool = False,
) -> list[dict]:
    """Replace tested entries, drop stale ones, sort and cap.

    A tested record always wins over the stored one for the same proxy, so a
    fresh failure removes the proxy from the pool instead of keeping a stale
    success.  ``tested`` entries carry ``"ok": False`` for that case.
    """
    merged: dict[str, dict] = {
        record["proxy"]: record
        for record in existing
        if now - float(record.get("verified_at", 0)) <= max_age
    }
    for record in tested:
        proxy = normalize(record.get("proxy"))
        if not proxy:
            continue
        if record.get("ok") is False:
            merged.pop(proxy, None)
            continue
        record = dict(record)
        record["proxy"] = proxy
        merged[proxy] = record
    ordered = sorted(
        merged.values(),
        key=lambda record: (record.get(sort_key, 0), record["proxy"]),
        reverse=reverse,
    )
    return ordered[:limit]


def freshness(records: list[dict], now: float) -> dict:
    if not records:
        return {"count": 0, "oldest_seconds": None, "median_seconds": None}
    ages = sorted(now - float(record.get("verified_at", 0)) for record in records)
    return {
        "count": len(records),
        "oldest_seconds": round(ages[-1]),
        "median_seconds": round(ages[len(ages) // 2]),
    }


# --------------------------------------------------------------------------
# Tier 1: collect and TCP screen
# --------------------------------------------------------------------------

def fetch_source(url: str, timeout: float) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "gitsynonyms-proxy-pool/2.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_SOURCE_BYTES).decode("utf-8", "replace")


def parse_source(text: str) -> list[str]:
    sys.path.insert(0, str(ROOT))
    import collect  # noqa: E402 - sibling stage, reused so parsing never drifts

    return [proxy for proxy in (normalize(entry) for entry in collect.parse(text)) if proxy]


def collect_sources(limit: int, workers: int, timeout: float) -> dict:
    urls = [
        line.strip()
        for line in SOURCES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"sources: {len(urls)}", flush=True)
    TIER1.mkdir(parents=True, exist_ok=True)
    raw = TIER1 / "raw.txt"
    fetched = 0
    entries = 0
    failures = 0

    def work(url: str) -> list[str]:
        try:
            return parse_source(fetch_source(url, timeout))
        except Exception:  # noqa: BLE001 - a dead source is expected
            return []

    with raw.open("w", encoding="utf-8", newline="\n") as handle, ThreadPoolExecutor(
        max_workers=workers
    ) as pool:
        for result in pool.map(work, urls):
            fetched += 1
            if result:
                handle.write("\n".join(result) + "\n")
                entries += len(result)
            else:
                failures += 1
            if fetched % 500 == 0:
                print(
                    f"  fetched {fetched}/{len(urls)} sources, {entries} entries",
                    flush=True,
                )

    unique = dedupe(raw, TIER1_RAW, limit)
    raw.unlink(missing_ok=True)
    stats = {
        "generated_at": int(time.time()),
        "sources": len(urls),
        "sources_with_entries": len(urls) - failures,
        "sources_failed": failures,
        "entries": entries,
        "unique": unique,
        "limit": limit,
    }
    TIER1_STATS.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(f"unique after dedupe: {unique} (cap {limit}) -> {TIER1_RAW}", flush=True)
    return stats


def dedupe(raw: Path, target: Path, limit: int) -> int:
    """Deduplicate with the platform sort, then evenly sample down to ``limit``."""
    if os.name == "posix":
        sorted_path = TIER1 / "raw.sorted.txt"
        with sorted_path.open("w", encoding="utf-8", newline="\n") as handle:
            subprocess.run(
                ["sort", "-u", "-S", "512M", "-T", str(TIER1), str(raw)],
                stdout=handle,
                check=True,
            )
    else:  # local development on Windows: the pool is small enough for a set
        unique = sorted(
            {line.strip() for line in raw.read_text(encoding="utf-8").splitlines() if line.strip()}
        )
        sorted_path = TIER1 / "raw.sorted.txt"
        sorted_path.write_text("\n".join(unique) + "\n", encoding="utf-8", newline="\n")

    total = count_lines(sorted_path)
    if total <= limit:
        sorted_path.replace(target)
        return total

    step = total / limit
    kept = 0
    with sorted_path.open(encoding="utf-8") as source, target.open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        for index, line in enumerate(source):
            if index >= int(kept * step):
                handle.write(line)
                kept += 1
                if kept >= limit:
                    break
    sorted_path.unlink(missing_ok=True)
    return kept


def count_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


async def tcp_probe(
    host: str, port: int, timeout: float, semaphore: asyncio.Semaphore
) -> float | None:
    async with semaphore:
        started = time.monotonic()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout
            )
        except Exception:  # noqa: BLE001 - unreachable proxies are the norm
            return None
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return (time.monotonic() - started) * 1000


def screen(limit: int, concurrency: int, timeout: float) -> dict:
    if not TIER1_RAW.is_file():
        raise SystemExit(f"{TIER1_RAW} is missing; run the collect stage first")
    entries = [
        line.strip()
        for line in TIER1_RAW.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"tier1 raw: {len(entries)} candidates", flush=True)
    results: list[dict] = []
    chunk = 50_000
    for start in range(0, len(entries), chunk):
        part = entries[start : start + chunk]
        results.extend(asyncio.run(screen_chunk(part, concurrency, timeout)))
        print(
            f"  tcp {min(start + chunk, len(entries))}/{len(entries)}, "
            f"{len(results)} open",
            flush=True,
        )

    now = time.time()
    records = [
        {"proxy": proxy, "latency_ms": round(latency, 1), "verified_at": int(now)}
        for proxy, latency in results
    ]
    records.sort(key=lambda record: (record["latency_ms"], record["proxy"]))
    records = records[:limit]
    write_jsonl(TIER1_OPEN, records)
    stats = {
        "generated_at": int(now),
        "checked": len(entries),
        "open": len(records),
        "limit": limit,
        "tcp_survival": round(len(records) / len(entries), 6) if entries else 0,
    }
    (TIER1 / "tier1_screen.json").write_text(
        json.dumps(stats, indent=2) + "\n", encoding="utf-8"
    )
    print(f"tcp open kept: {len(records)} -> {TIER1_OPEN}", flush=True)
    return stats


async def screen_chunk(
    entries: list[str], concurrency: int, timeout: float
) -> list[tuple[str, float]]:
    semaphore = asyncio.Semaphore(concurrency)
    pairs: list[tuple[str, asyncio.Task]] = []
    for entry in entries:
        host, _, port_text = entry.rpartition(":")
        if not host or not port_text.isdigit():
            continue
        pairs.append((entry, tcp_probe(host, int(port_text), timeout, semaphore)))
    results = await asyncio.gather(*(task for _, task in pairs))
    return [
        (entry, result)
        for (entry, _), result in zip(pairs, results)
        if result is not None
    ]


# --------------------------------------------------------------------------
# Tier 2: HTTPS speed screen
# --------------------------------------------------------------------------

def https_probe(proxy: str, timeout: float) -> float | None:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": as_url(proxy), "https": as_url(proxy)})
    )
    request = urllib.request.Request(
        CANARY_HTTPS, headers={"User-Agent": "gitsynonyms-proxy-pool/2.0"}
    )
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 204:
                return None
    except (OSError, urllib.error.URLError, http.client.HTTPException, TimeoutError):
        return None
    return (time.monotonic() - started) * 1000


def rolling_batch(
    candidates: list[dict],
    fresh: dict[str, dict],
    batch: int,
    max_age: float,
    now: float,
    key: str,
) -> list[dict]:
    """Oldest/most promising candidates that are not fresh in the next tier."""
    stale = [
        candidate
        for candidate in candidates
        if candidate["proxy"] not in fresh
        or now - float(fresh[candidate["proxy"]].get("verified_at", 0)) > max_age
    ]
    stale.sort(key=lambda candidate: (candidate.get(key, 0), candidate["proxy"]))
    return stale[:batch]


def speed(batch: int, target: int, max_age: float, concurrency: int, timeout: float) -> dict:
    if not TIER1_OPEN.is_file():
        raise SystemExit(f"{TIER1_OPEN} is missing; run the screen stage first")
    candidates = load_jsonl(TIER1_OPEN)
    existing = load_jsonl(TIER2_RECORDS)
    now = time.time()
    fresh = {record["proxy"]: record for record in existing}
    selected = rolling_batch(candidates, fresh, batch, max_age, now, "latency_ms")
    print(
        f"tier2: {len(candidates)} candidates, {len(existing)} stored, "
        f"testing {len(selected)}",
        flush=True,
    )

    def work(candidate: dict) -> dict:
        proxy = candidate["proxy"]
        try:
            latency = https_probe(proxy, timeout)
        except Exception as error:  # noqa: BLE001 - one proxy must not kill the run
            print(f"  {proxy}: probe error {error}", flush=True)
            latency = None
        if latency is None:
            return {"proxy": proxy, "ok": False, "verified_at": int(now)}
        return {
            "proxy": proxy,
            "ok": True,
            "latency_ms": round(latency, 1),
            "verified_at": int(now),
        }

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        tested = list(pool.map(work, selected))

    merged = merge_records(
        existing, tested, limit=target, max_age=max_age, now=now, sort_key="latency_ms"
    )
    write_jsonl(TIER2_RECORDS, merged)
    write_plain(TIER2_PLAIN, merged)
    stats = {
        "generated_at": int(now),
        "candidates": len(candidates),
        "tested": len(selected),
        "passed": sum(1 for record in tested if record.get("ok")),
        "kept": len(merged),
        **freshness(merged, now),
    }
    (TIER2 / "tier2_stats.json").write_text(
        json.dumps(stats, indent=2) + "\n", encoding="utf-8"
    )
    print(f"tier2 kept: {len(merged)} -> {TIER2_PLAIN}", flush=True)
    return stats


# --------------------------------------------------------------------------
# Tier 3: real extraction and ranged download
# --------------------------------------------------------------------------

def ytdlp_direct_url(proxy: str, video: str, timeout: float) -> str | None:
    command = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--socket-timeout",
        "8",
        "--retries",
        "0",
        "--proxy",
        as_url(proxy),
        "--extractor-args",
        "youtube:player_client=default",
        "-f",
        "bv*[height<=360]/b[height<=360]",
        "-g",
        video,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("http") and "googlevideo.com" in line:
            return line
    return None


def ranged_download(proxy: str, url: str, timeout: float) -> tuple[int, float] | None:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": as_url(proxy), "https": as_url(proxy)})
    )
    request = urllib.request.Request(
        url,
        headers={
            "Range": f"bytes=0-{RANGE_BYTES - 1}",
            "User-Agent": "Mozilla/5.0",
        },
    )
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read(RANGE_BYTES)
    except (OSError, urllib.error.URLError, http.client.HTTPException, TimeoutError):
        return None
    elapsed = max(time.monotonic() - started, 0.001)
    if len(payload) < 16 * 1024:
        return None
    return len(payload), len(payload) / elapsed


def ready_test(proxy: str, video: str, timeout: float) -> dict:
    url = ytdlp_direct_url(proxy, video, timeout)
    if not url:
        return {"proxy": proxy, "ok": False, "reason": "extraction"}
    transfer = ranged_download(proxy, url, timeout)
    if not transfer:
        return {"proxy": proxy, "ok": False, "reason": "download"}
    size, throughput = transfer
    return {
        "proxy": proxy,
        "ok": True,
        "bytes": size,
        "bytes_per_second": round(throughput, 1),
        "verified_at": int(time.time()),
    }


def ready(
    batch: int,
    target: int,
    max_age: float,
    concurrency: int,
    timeout: float,
    video: str,
) -> dict:
    if not TIER2_RECORDS.is_file():
        raise SystemExit(f"{TIER2_RECORDS} is missing; run the speed stage first")
    candidates = load_jsonl(TIER2_RECORDS)
    existing = load_jsonl(TIER3_RECORDS)
    now = time.time()
    fresh = {record["proxy"]: record for record in existing}
    selected = rolling_batch(candidates, fresh, batch, max_age, now, "latency_ms")

    failed: dict[str, int] = {}
    if TIER3_FAILED.is_file():
        try:
            failed = {
                proxy: int(stamp)
                for proxy, stamp in json.loads(
                    TIER3_FAILED.read_text(encoding="utf-8")
                ).items()
                if now - int(stamp) <= max_age
            }
        except (json.JSONDecodeError, ValueError):
            failed = {}
    selected = [candidate for candidate in selected if candidate["proxy"] not in failed][:batch]
    print(
        f"tier3: {len(candidates)} candidates, {len(existing)} stored, "
        f"testing {len(selected)} against {video}",
        flush=True,
    )

    def work(candidate: dict) -> dict:
        proxy = candidate["proxy"]
        try:
            return ready_test(proxy, video, timeout)
        except Exception as error:  # noqa: BLE001 - one proxy must not kill the run
            print(f"  {proxy}: download test error {error}", flush=True)
            return {"proxy": proxy, "ok": False, "reason": "error"}

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        tested = list(pool.map(work, selected))

    for record in tested:
        if record.get("ok"):
            failed.pop(record["proxy"], None)
        else:
            failed[record["proxy"]] = int(now)
    TIER3_FAILED.write_text(json.dumps(failed, sort_keys=True) + "\n", encoding="utf-8")

    merged = merge_records(
        existing,
        tested,
        limit=target,
        max_age=max_age,
        now=now,
        sort_key="bytes_per_second",
        reverse=True,
    )
    write_jsonl(TIER3_RECORDS, merged)
    write_plain(TIER3_PLAIN, merged)
    stats = {
        "generated_at": int(now),
        "candidates": len(candidates),
        "tested": len(selected),
        "passed": sum(1 for record in tested if record.get("ok")),
        "kept": len(merged),
        "failed_recent": len(failed),
        **freshness(merged, now),
    }
    (TIER3 / "tier3_stats.json").write_text(
        json.dumps(stats, indent=2) + "\n", encoding="utf-8"
    )
    print(f"tier3 kept: {len(merged)} -> {TIER3_PLAIN}", flush=True)
    return stats


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------

def status() -> dict:
    now = time.time()
    report = {}
    for name, path in (
        ("tier1_raw", TIER1_RAW),
        ("tier2", TIER2_RECORDS),
        ("tier3", TIER3_RECORDS),
    ):
        if name == "tier1_raw":
            count = count_lines(path) if path.is_file() else 0
            report[name] = {"count": count}
            continue
        records = load_jsonl(path)
        report[name] = freshness(records, now)
    print(json.dumps(report, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Three-tier public proxy pool")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="tier 1: fetch sources and dedupe")
    collect.add_argument("--limit", type=int, default=1_000_000)
    collect.add_argument("--workers", type=int, default=64)
    collect.add_argument("--timeout", type=float, default=20.0)

    screen_parser = sub.add_parser("screen", help="tier 1: keep TCP-reachable")
    screen_parser.add_argument("--limit", type=int, default=250_000)
    screen_parser.add_argument("--concurrency", type=int, default=600)
    screen_parser.add_argument("--timeout", type=float, default=2.5)

    speed_parser = sub.add_parser("speed", help="tier 2: HTTPS latency screen")
    speed_parser.add_argument("--batch", type=int, default=4_000)
    speed_parser.add_argument("--target", type=int, default=10_000)
    speed_parser.add_argument("--max-age", type=float, default=3 * 3600)
    speed_parser.add_argument("--concurrency", type=int, default=128)
    speed_parser.add_argument("--timeout", type=float, default=5.0)

    ready_parser = sub.add_parser("ready", help="tier 3: real download test")
    ready_parser.add_argument("--batch", type=int, default=900)
    ready_parser.add_argument("--target", type=int, default=1_000)
    ready_parser.add_argument("--max-age", type=float, default=2 * 3600)
    ready_parser.add_argument("--concurrency", type=int, default=64)
    ready_parser.add_argument("--timeout", type=float, default=30.0)
    ready_parser.add_argument("--video", default=TEST_VIDEO)

    sub.add_parser("status", help="print pool counts and freshness")

    args = parser.parse_args()
    if args.command == "collect":
        collect_sources(args.limit, args.workers, args.timeout)
    elif args.command == "screen":
        screen(args.limit, args.concurrency, args.timeout)
    elif args.command == "speed":
        speed(args.batch, args.target, args.max_age, args.concurrency, args.timeout)
    elif args.command == "ready":
        ready(
            args.batch,
            args.target,
            args.max_age,
            args.concurrency,
            args.timeout,
            args.video,
        )
    else:
        status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
