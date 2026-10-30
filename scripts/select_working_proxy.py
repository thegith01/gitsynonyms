#!/usr/bin/env python3
"""Pick a proxy that can actually reach YouTube for one video.

The source downloader reports which proxy carried the media bytes, but a free
proxy can die between that download and the next pipeline step.  Reusing the
reported proxy blindly is what made the caption stage fail with a connect
timeout even though the download had just succeeded.

Selection order:
1. proxies reported as successful by the source downloader;
2. the tier-3 pool (real yt-dlp extraction + ranged download verified);
3. the tier-2 pool (HTTPS canary verified).

Every candidate first passes the cheap HTTPS canary in parallel; the fastest
few are then checked with the exact ``yt-dlp -J`` request the caption stage
needs, so "the proxy answers" never gets confused with "YouTube serves this
video through it".
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import select_public_ytdlp_proxy as selector  # noqa: E402

CANARY_WORKERS = 32
DEFAULT_CANDIDATES = 60
DEFAULT_VERIFY = 8


def log(message: str) -> None:
    print(message, flush=True)


def reported_proxies(report: Path) -> list[str]:
    """Proxies that completed the source download, newest attempt first."""
    if not report.is_file():
        return []
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    proxies: list[str] = []
    for attempt in data.get("attempts") or []:
        proxy = attempt.get("proxy")
        if attempt.get("ok") and proxy and proxy not in proxies:
            proxies.append(proxy)
    return proxies


def pool_proxies(limit: int) -> list[str]:
    try:
        return selector.load_pool()[:limit]
    except OSError:
        return []


def canary_probe(proxy: str) -> float | None:
    return selector.probe_proxy(proxy)


def ytdlp_metadata_ok(proxy: str, video_id: str, timeout: float) -> bool:
    command = [
        "yt-dlp",
        "--proxy",
        proxy,
        "--no-warnings",
        "--socket-timeout",
        "10",
        "--retries",
        "0",
        "-J",
        "--skip-download",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and '"id"' in (result.stdout or "")


def pick(
    video_id: str,
    report: Path,
    candidates: int,
    verify: int,
    timeout: float,
) -> tuple[str, str] | None:
    ordered: list[str] = []
    for proxy in reported_proxies(report) + pool_proxies(candidates):
        if proxy not in ordered:
            ordered.append(proxy)
    if not ordered:
        log("no proxy candidates: report empty and pool missing")
        return None

    log(f"probing {len(ordered)} candidates with the HTTPS canary")
    with ThreadPoolExecutor(max_workers=CANARY_WORKERS) as pool:
        latencies = list(pool.map(canary_probe, ordered))
    working = sorted(
        (latency, proxy)
        for proxy, latency in zip(ordered, latencies)
        if latency is not None
    )
    log(f"canary passed: {len(working)}")
    if not working:
        return None

    for latency, proxy in working[:verify]:
        if ytdlp_metadata_ok(proxy, video_id, timeout):
            return proxy, f"yt-dlp metadata ok ({latency * 1000:.0f} ms canary)"
        log(f"  {proxy}: canary ok but yt-dlp failed")
    return None


def write_github_env(name: str, value: str) -> None:
    env_file = os.environ.get("GITHUB_ENV")
    if not env_file:
        log(f"{name}={value} (GITHUB_ENV not set)")
        return
    selector.write_github_env(name, value, env_file)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a YouTube-capable proxy")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--report", default="work/download-report.json")
    parser.add_argument("--candidates", type=int, default=DEFAULT_CANDIDATES)
    parser.add_argument("--verify", type=int, default=DEFAULT_VERIFY)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--name", default="YTDLP_PROXY")
    args = parser.parse_args()

    selected = pick(
        args.video_id,
        Path(args.report),
        args.candidates,
        args.verify,
        args.timeout,
    )
    if selected is None:
        log("no proxy passed the yt-dlp check; leaving the variable unset for direct egress")
        return 1
    proxy, note = selected
    log(f"selected {proxy}: {note}")
    write_github_env(args.name, proxy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
