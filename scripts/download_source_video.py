#!/usr/bin/env python3
"""Download a YouTube source video: direct first, then the whole repo proxy pool.

Order of attempts
-----------------
1. direct connection (no proxy)
2. every candidate from the repository proxy code, probed in parallel and
   sorted by latency
3. a short *screening* pass per proxy (``--probe-timeout``): a real yt-dlp
   extraction that proves the proxy can reach the player API at all
4. only the proxies that pass screening get the full ``--timeout`` to move
   bytes, so a dead address costs seconds instead of twenty minutes

A proxy that hits the full timeout without writing a single byte is dropped
immediately; retrying it with the remaining clients and formats is what used
to turn one dead address into hours of wall clock.

Quality: prefer 1080p or higher, then degrade step by step.

Proxy candidates come from ``scripts/select_public_ytdlp_proxy.py``:
``proxyindex/alive_http.txt`` when present, otherwise the public lists
(TheSpeedX / monosans / proxifly).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import select_public_ytdlp_proxy as selector  # noqa: E402

CLIENT_CHAIN = ["tv_embedded", "android_vr", "web_safari", "mweb", "default"]

# Live replays are often capped per client: tv_embedded may expose only 720p
# while web_safari/android_vr expose 1080p.  The proxy phase must therefore
# try every client and every quality tier, not just the first 1080p selector.
# ``default`` is the client that exposed the 720p tiers of the lJYmGObStag
# live replay; the specialized clients either timed out or returned only
# storyboards.  Keep it first so a 720p run does not spend minutes on them.
PROXY_CLIENTS = ["default", "tv_embedded", "android_vr", "web_safari"]

FORMAT_CHAIN = [
    "bv*[height>=1080]+ba/b[height>=1080]",
    "bv*[height>=720]+ba/b[height>=720]",
    "bv*+ba/b",
]


def log(message: str) -> None:
    print(message, flush=True)


def candidate_proxies(limit: int) -> list[str]:
    pool = selector.load_pools()
    if pool:
        log(f"proxy pool from proxyindex: {len(pool)} entries")
    else:
        log("proxyindex pool empty; fetching public proxy lists")
        try:
            lists = selector.fetch_lists()
        except Exception as error:  # noqa: BLE001
            log(f"could not fetch public proxy lists: {error}")
            return []
        pool = [proxy for proxies in lists.values() for proxy in proxies]
        log(f"public list candidates: {len(pool)}")
    pool = list(dict.fromkeys(pool))
    if limit > 0 and len(pool) > limit:
        pool = pool[:limit]
    return pool


def probe(candidates: list[str], workers: int = 32) -> list[tuple[str, float]]:
    log(f"probing {len(candidates)} proxies against YouTube...")
    results: list[tuple[str, float]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(selector.probe_proxy, proxy): proxy for proxy in candidates}
        for future in futures:
            proxy = futures[future]
            try:
                latency = future.result()
            except Exception:  # noqa: BLE001
                latency = None
            if latency is not None:
                results.append((proxy, latency))
    results.sort(key=lambda item: item[1])
    log(f"alive proxies: {len(results)}")
    return results


def _progress_size(target: Path) -> int:
    """Bytes already written for ``target`` (the ``%(ext)s`` template)."""
    pattern = target.name.replace("%(ext)s", "*")
    total = 0
    for path in target.parent.glob(pattern):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


# Screening classifies a proxy, it does not judge the video.  A proxy that
# answers YouTube with "Sign in to confirm you're not a bot" still transports
# bytes; another player client may hand it the media, and that failure costs
# three seconds, not a timeout.  Only transport failures are worth dropping.
SCREEN_GATE_MARKERS = (
    "sign in to confirm", "not a bot", "confirm your age", "http error 429",
    "video unavailable", "private video", "members-only", "requested format",
    "unable to extract", "no video formats found",
)
SCREEN_DEAD_MARKERS = (
    "timeout", "timed out", "connection refused", "connection reset",
    "failed to connect", "unable to connect", "tunnel connection failed",
    "ssl", "certificate", "name resolution", "network is unreachable",
    "proxyerror", "unable to connect to proxy", "remote end closed",
    "incompleteread", "eof occurred", "connection aborted",
)


def classify_screen(returncode: int, detail: str, timed_out: bool) -> str:
    """``ok``, ``gate`` (cheap YouTube rejection, keep going) or ``dead``."""
    if timed_out:
        return "dead"
    if returncode == 0:
        return "ok"
    text = detail.lower()
    if any(marker in text for marker in SCREEN_GATE_MARKERS):
        return "gate"
    if any(marker in text for marker in SCREEN_DEAD_MARKERS):
        return "dead"
    # Unknown failure: it was fast, so let the real attempt decide.
    return "gate"


def smoke_test(url: str, proxy: str, timeout: int,
               cookies: Path | None) -> tuple[str, str]:
    """Two-stage check: can this proxy transport YouTube traffic at all?

    The format is deliberately permissive (``bv*+ba/b``): this asks only
    whether the proxy can reach the player API.  The quality floor is enforced
    by the download formats that follow, so a live replay whose 1080p tier only
    exists on one client is not rejected here for the wrong reason.
    """
    command = [
        "yt-dlp", "--simulate", "--no-warnings",
        "--retries", "0", "--fragment-retries", "0", "--socket-timeout", "15",
        "-f", "bv*+ba/b", "--print", "%(id)s",
        "--proxy", proxy,
    ]
    if cookies:
        command += ["--cookies", str(cookies)]
    command.append(url)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "dead", f"{proxy}: screen timeout after {timeout}s"
    detail = (result.stderr or result.stdout).strip().splitlines()
    tail = detail[-1] if detail else f"exit {result.returncode}"
    status = classify_screen(result.returncode, tail, timed_out=False)
    return status, f"{proxy}: screen {status} ({tail[:120]})"


def try_download(url: str, target: Path, fmt: str, proxy: str | None, timeout: int,
                 cookies: Path | None, client: str = "default") -> tuple[bool, str, int]:
    command = ["yt-dlp", "--no-warnings", "--retries", "3", "--fragment-retries", "3",
               "--socket-timeout", "20", "--merge-output-format", "mp4",
               "-f", fmt, "-o", str(target)]
    if client != "default":
        command += ["--extractor-args", f"youtube:player_client={client}"]
    if proxy:
        command += ["--proxy", proxy]
    if cookies:
        command += ["--cookies", str(cookies)]
    command.append(url)
    label = f"{proxy or 'direct'} [{client}]"
    log(f"  trying {label} @ {fmt}")
    started = time.monotonic()
    before = _progress_size(target)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{label}: timeout after {timeout}s", _progress_size(target) - before
    elapsed = time.monotonic() - started
    if result.returncode == 0:
        return True, f"{label}: ok in {elapsed:.0f}s", _progress_size(target) - before
    detail = (result.stderr or result.stdout).strip().splitlines()
    tail = detail[-1] if detail else f"exit {result.returncode}"
    return False, f"{label}: {tail[:180]}", _progress_size(target) - before


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct-then-proxy source download")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output-dir", default="work")
    parser.add_argument("--min-height", type=int, default=1080)
    parser.add_argument("--proxy-limit", type=int, default=120)
    parser.add_argument("--proxy-tries", type=int, default=60,
                        help="How many probed proxies to screen, best latency first")
    parser.add_argument("--probe-timeout", type=int, default=60,
                        help="Seconds a proxy gets to pass the screening extraction")
    parser.add_argument("--probe-workers", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=900,
                        help="Seconds a screened proxy gets to finish the real download")
    parser.add_argument("--cookies", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={args.video_id}"
    target = out / f"{args.video_id}.source.%(ext)s"
    cookies = Path(args.cookies) if args.cookies else None
    if cookies and not cookies.is_file():
        log(f"cookies file missing: {cookies}")
        cookies = None

    # Never try a tier above the requested floor: a 720p-only live replay
    # would otherwise spend an hour probing 1080p selectors that cannot exist.
    tiers = [args.min_height]
    tiers.extend(height for height in (1080, 720, 0) if height == 0 or height < args.min_height)
    formats = [
        "bv*+ba/b" if height == 0 else f"bv*[height>={height}]+ba/b[height>={height}]"
        for height in dict.fromkeys(tiers)
    ]

    attempts: list[dict] = []
    finished = False
    for client in CLIENT_CHAIN:
        for fmt in formats:
            ok, note, _ = try_download(url, target, fmt, None, args.timeout, cookies, client)
            attempts.append({"mode": "direct", "client": client, "format": fmt,
                             "ok": ok, "note": note})
            log(f"  {note}")
            if ok:
                finished = True
                break
        if finished:
            break

    if not finished:
        candidates = candidate_proxies(args.proxy_limit)
        alive = probe(candidates) if candidates else []
        shortlist = alive[:args.proxy_tries]
        # Screen every shortlisted proxy concurrently, then consume the
        # survivors in latency order: the fastest one starts downloading while
        # the remaining screens are still running in the pool.
        if shortlist:
            log(f"screening {len(shortlist)} proxies (<= {args.probe_timeout}s each)...")
            with ThreadPoolExecutor(max_workers=args.probe_workers) as pool:
                screens = {
                    pool.submit(smoke_test, url, proxy, args.probe_timeout, cookies):
                        (proxy, latency)
                    for proxy, latency in shortlist
                }
                for future, (proxy, latency) in screens.items():
                    try:
                        status, screen_note = future.result()
                    except Exception as error:  # noqa: BLE001
                        status, screen_note = "dead", f"{proxy}: screen error {error}"
                    attempts.append({"mode": "probe", "proxy": proxy,
                                     "latency": round(latency, 3),
                                     "screen": status, "ok": status != "dead",
                                     "note": screen_note})
                    log(f"  {screen_note}")
                    if status == "dead":
                        continue
                    # Quality first, then transport: keep the highest tier
                    # across every proxy/client before degrading, so a single
                    # 720p-only client cannot mask a 1080p-capable proxy.
                    unusable = False
                    for fmt in formats:
                        for client in PROXY_CLIENTS:
                            ok, note, moved = try_download(
                                url, target, fmt, proxy, args.timeout, cookies, client
                            )
                            attempts.append({"mode": "proxy", "proxy": proxy,
                                             "client": client,
                                             "latency": round(latency, 3),
                                             "format": fmt, "ok": ok,
                                             "moved_bytes": moved, "note": note})
                            log(f"  {note}")
                            if ok:
                                finished = True
                                break
                            # A screened proxy that times out with zero bytes
                            # written cannot transfer media; the remaining
                            # clients and formats would only burn more timeouts.
                            if moved <= 0 and "timeout after" in note:
                                log(f"  dropping {proxy}: no bytes before the deadline")
                                unusable = True
                                break
                        if finished or unusable:
                            break
                    if finished:
                        break

    report = {"video_id": args.video_id, "succeeded": finished, "attempts": attempts}
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not finished:
        log("::error::every direct and proxy attempt failed; YouTube requires authenticated media access")
        return 1

    produced = [p for p in out.glob(f"{args.video_id}.source.*")
                if p.is_file() and p.suffix not in {".part", ".ytdl"}]
    if not produced:
        log("::error::yt-dlp reported success but no source file exists")
        return 1
    log(f"downloaded: {produced[0].name} ({produced[0].stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
