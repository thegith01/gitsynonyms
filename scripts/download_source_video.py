#!/usr/bin/env python3
"""Download a YouTube source video: direct first, then the whole repo proxy pool.

Order of attempts
-----------------
1. direct connection (no proxy)
2. every candidate from the repository proxy code, probed in parallel and
   sorted by latency, tried one by one until a download completes

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

CLIENT_CHAIN = ["tv_embedded", "android_vr", "default"]

FORMAT_CHAIN = [
    "bv*[height>=1080]+ba/b[height>=1080]",
    "bv*[height>=720]+ba/b[height>=720]",
    "bv*+ba/b",
]


def log(message: str) -> None:
    print(message, flush=True)


def candidate_proxies(limit: int) -> list[str]:
    pool = selector.load_pool()
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


def try_download(url: str, target: Path, fmt: str, proxy: str | None, timeout: int,
                 cookies: Path | None, client: str = "default") -> tuple[bool, str]:
    command = ["yt-dlp", "--no-warnings", "--retries", "2", "--fragment-retries", "2",
               "--merge-output-format", "mp4", "-f", fmt, "-o", str(target)]
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
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{label}: timeout after {timeout}s"
    elapsed = time.monotonic() - started
    if result.returncode == 0:
        return True, f"{label}: ok in {elapsed:.0f}s"
    detail = (result.stderr or result.stdout).strip().splitlines()
    tail = detail[-1] if detail else f"exit {result.returncode}"
    return False, f"{label}: {tail[:180]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct-then-proxy source download")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output-dir", default="work")
    parser.add_argument("--min-height", type=int, default=1080)
    parser.add_argument("--proxy-limit", type=int, default=120)
    parser.add_argument("--proxy-tries", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=600)
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

    preferred = "bv*[height>=%d]+ba/b[height>=%d]" % (args.min_height, args.min_height)
    formats = [preferred] + FORMAT_CHAIN
    formats = list(dict.fromkeys(formats))

    attempts: list[dict] = []
    finished = False
    for client in CLIENT_CHAIN:
        for fmt in formats:
            ok, note = try_download(url, target, fmt, None, args.timeout, cookies, client)
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
        for proxy, latency in alive[:args.proxy_tries]:
            for client in ("tv_embedded", "default"):
                ok, note = try_download(url, target, formats[0], proxy, args.timeout, cookies, client)
                attempts.append({"mode": "proxy", "proxy": proxy, "client": client,
                                 "latency": round(latency, 3), "format": formats[0],
                                 "ok": ok, "note": note})
                log(f"  {note}")
                if ok:
                    finished = True
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
