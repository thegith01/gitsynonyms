#!/usr/bin/env python3
"""Build a validated HTTP proxy pool for the repository.

Fetches several high-yield public proxy lists, deduplicates candidates, probes
each one against YouTube's HTTPS endpoint through the proxy, and writes the
fastest working entries to ``proxyindex/alive_http.txt`` so later runs do not
have to re-discover proxies.

Usage:
  python3 scripts/build_proxy_pool.py --limit 6000 --keep 800
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import select_public_ytdlp_proxy as selector  # noqa: E402

LISTS = [
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/shifty0g/ultimate-http-proxy-list/master/proxies.txt",
    "https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt",
    "https://raw.githubusercontent.com/proxy4parsing/proxy-list/main/http.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
    "https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/http.txt",
    "https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/http.txt",
    "https://raw.githubusercontent.com/prxchk/proxy-list/main/http.txt",
    "https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/http/http.txt",
    "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=text",
]

IP_PORT = re.compile(r"^(?:https?://)?(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})/?$")


def fetch(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "gitsynonyms-pool/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(8_000_000).decode("utf-8", "replace")


def collect(limit: int) -> list[str]:
    seen: dict[str, None] = {}
    for url in LISTS:
        name = url.rsplit("/", 3)[-3] if url.count("/") > 3 else url
        try:
            payload = fetch(url)
        except Exception as error:  # noqa: BLE001
            print(f"  list failed {name}: {error}", flush=True)
            continue
        added = 0
        for line in payload.splitlines():
            match = IP_PORT.fullmatch(line.strip())
            if not match:
                continue
            host, port = match.groups()
            if not 1 <= int(port) <= 65535:
                continue
            entry = f"{host}:{port}"
            if entry in seen:
                continue
            seen[entry] = None
            added += 1
            if len(seen) >= limit:
                break
        print(f"  {name}: +{added} (total {len(seen)})", flush=True)
        if len(seen) >= limit:
            break
    return list(seen)


def probe_all(candidates: list[str], workers: int) -> list[tuple[str, float]]:
    alive: list[tuple[str, float]] = []
    done = 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(selector.probe_proxy, f"http://{entry}"): entry
                   for entry in candidates}
        for future in futures:
            entry = futures[future]
            done += 1
            try:
                latency = future.result()
            except Exception:  # noqa: BLE001
                latency = None
            if latency is not None:
                alive.append((entry, latency))
            if done % 250 == 0:
                elapsed = time.monotonic() - started
                print(f"  probed {done}/{len(candidates)} alive={len(alive)} "
                      f"{done/elapsed:.0f}/s", flush=True)
    return alive


def main() -> int:
    parser = argparse.ArgumentParser(description="Build validated proxy pool")
    parser.add_argument("--limit", type=int, default=12000)
    parser.add_argument("--keep", type=int, default=1200)
    parser.add_argument("--workers", type=int, default=160)
    parser.add_argument("--output", default="proxyindex/alive_http.txt")
    args = parser.parse_args()

    print("collecting candidates...", flush=True)
    candidates = collect(args.limit)
    print(f"candidates: {len(candidates)}", flush=True)
    if not candidates:
        print("::error::no candidates", flush=True)
        return 1

    print("probing against YouTube over HTTPS...", flush=True)
    alive = probe_all(candidates, args.workers)
    alive.sort(key=lambda item: item[1])
    print(f"alive: {len(alive)}", flush=True)
    if not alive:
        print("::error::no proxy passed the YouTube probe", flush=True)
        return 1

    kept = alive[:args.keep]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(entry for entry, _ in kept) + "\n"
    out.write_text(body, encoding="utf-8")
    print(f"wrote {len(kept)} proxies to {out}")
    print(f"fastest: {kept[0][0]} ({kept[0][1]*1000:.0f} ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
