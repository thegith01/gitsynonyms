#!/usr/bin/env python3
"""Probe whether this machine can reach YouTube media and Google Translate.

The GitHub-hosted runner is rejected by YouTube with "Sign in to confirm you're
not a bot".  This probe answers three questions in one run:

1. does any ``yt-dlp`` player client get a 1080p format on the direct link?
2. if not, does any proxy from the repository pool get a 1080p format?
3. can the machine reach the free Google Translate endpoint (needed when no
   Chinese caption track exists)?

It never downloads media: every ``yt-dlp`` call uses ``--simulate``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import select_public_ytdlp_proxy as selector  # noqa: E402

CLIENTS = ["tv_embedded", "android_vr", "default"]
TRANSLATE_URL = (
    "https://translate.googleapis.com/translate_a/single"
    "?client=gtx&sl=en&tl=zh-CN&dt=t&q={text}"
)


def log(message: str) -> None:
    print(message, flush=True)


def try_meta(url: str, proxy: str | None, client: str, timeout: int) -> tuple[bool, str]:
    command = [
        "yt-dlp",
        "--no-warnings",
        "--simulate",
        "--socket-timeout",
        "15",
        "--print",
        "%(height)s %(format_id)s %(ext)s",
        "-f",
        "bv*[height>=1080]+ba/b",
    ]
    if client != "default":
        command += ["--extractor-args", f"youtube:player_client={client}"]
    if proxy:
        command += ["--proxy", proxy]
    command.append(url)
    label = f"{proxy or 'direct'} [{client}]"
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{label}: timeout after {timeout}s"
    if result.returncode == 0:
        summary = (result.stdout or "").strip().splitlines()
        return True, f"{label}: {summary[-1] if summary else 'ok'}"
    tail = (result.stderr or result.stdout or "").strip().splitlines()
    detail = (tail[-1] if tail else f"exit {result.returncode}")[:180]
    return False, f"{label}: {detail}"


def list_subs(url: str, proxy: str | None, client: str, timeout: int) -> list[str]:
    """Return the caption languages visible through this route."""
    command = ["yt-dlp", "--no-warnings", "--skip-download", "--list-subs"]
    if client != "default":
        command += ["--extractor-args", f"youtube:player_client={client}"]
    if proxy:
        command += ["--proxy", proxy]
    command.append(url)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ["timeout"]
    text = (result.stdout or "") + (result.stderr or "")
    return [line.strip() for line in text.splitlines() if line.strip()][-25:]


def try_translate(timeout: int = 20, proxy: str | None = None) -> tuple[bool, str]:
    request = urllib.request.Request(
        TRANSLATE_URL.format(text=urllib.parse.quote("The President is speaking now.")),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    opener = (
        urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        if proxy
        else urllib.request.build_opener()
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        text = "".join(part[0] for part in payload[0] if part and part[0])
        return True, text.strip()
    except Exception as error:  # noqa: BLE001
        return False, str(error)[:180]


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe YouTube and translate access")
    parser.add_argument("--video-id", default="9aPyO1jfDGM")
    parser.add_argument("--proxy-tries", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    url = f"https://www.youtube.com/watch?v={args.video_id}"
    direct: list[dict] = []
    for client in CLIENTS:
        ok, note = try_meta(url, None, client, args.timeout)
        direct.append({"client": client, "ok": ok, "note": note})
        log(f"direct {note}")

    proxy_results: list[dict] = []
    direct_ok = any(item["ok"] for item in direct)
    if not direct_ok:
        pool = selector.load_pool()
        log(f"proxy pool entries: {len(pool)}")
        if not pool:
            try:
                lists = selector.fetch_lists()
                pool = [proxy for proxies in lists.values() for proxy in proxies]
            except Exception as error:  # noqa: BLE001
                log(f"could not fetch public proxy lists: {error}")
                pool = []
        pool = list(dict.fromkeys(pool))
        log(f"probing {len(pool)} proxies against YouTube...")
        alive = selector.working_proxies(pool) if pool else []
        log(f"alive proxies: {len(alive)}")
        for latency, proxy in alive[: args.proxy_tries]:
            for client in ("tv_embedded", "default"):
                ok, note = try_meta(url, proxy, client, args.timeout)
                proxy_results.append(
                    {
                        "proxy": proxy,
                        "latency": round(latency, 3),
                        "client": client,
                        "ok": ok,
                        "note": note,
                    }
                )
                log(f"proxy {note}")
                if ok:
                    break
            if any(item["ok"] for item in proxy_results):
                break

    translate_ok, translate_note = try_translate()
    log(f"translate ok={translate_ok} {translate_note}")

    winning = next((item for item in proxy_results if item["ok"]), None)
    translate_proxy_ok, translate_proxy_note = (False, "no proxy")
    if winning and not translate_ok:
        translate_proxy_ok, translate_proxy_note = try_translate(proxy=winning["proxy"])
        log(f"translate via proxy ok={translate_proxy_ok} {translate_proxy_note}")
    if winning:
        subs = list_subs(url, winning["proxy"], winning["client"], args.timeout)
    elif direct_ok:
        good_client = next(item["client"] for item in direct if item["ok"])
        subs = list_subs(url, None, good_client, args.timeout)
    else:
        subs = ["no working route"]
    log("caption list:")
    for line in subs:
        log(f"  {line}")

    report = {
        "video_id": args.video_id,
        "direct": direct,
        "proxies": proxy_results,
        "direct_ok": direct_ok,
        "proxy_ok": any(item["ok"] for item in proxy_results),
        "translate_ok": translate_ok,
        "translate_sample": translate_note,
        "translate_proxy_ok": translate_proxy_ok,
        "translate_proxy_sample": translate_proxy_note,
        "captions": subs,
    }
    Path("work").mkdir(exist_ok=True)
    Path("work/access-probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log("summary: " + json.dumps({k: report[k] for k in
                                  ("direct_ok", "proxy_ok", "translate_ok", "translate_proxy_ok")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
