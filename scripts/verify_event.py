#!/usr/bin/env python3
"""Corroborate a monitored upload against independent web sources.

Stage "verify" of the autonomous pipeline.  Given the title of a newly seen
upload, query Google News RSS (no API key) and score how well independent
outlets confirm the same event.  The result is ``EVENT.json``.

This does not claim semantic understanding: it measures independent
corroboration, keyword agreement and date proximity, and records the evidence
links so a human can audit the decision.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

GOOGLE_NEWS = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "will", "into",
    "ahead", "after", "before", "over", "under", "live", "video", "full",
    "president", "remarks", "speech", "watch", "update", "news",
}

PRIMARY_DOMAINS = {
    "whitehouse.gov", "c-span.org", "reuters.com", "apnews.com", "bbc.com",
    "bbc.co.uk", "npr.org", "pbs.org",
}


def log(message: str) -> None:
    print(message, flush=True)


def keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]{3,}", text.lower())
    return [word for word in words if word not in STOPWORDS]


def fetch_rss(query: str, timeout: int = 25) -> list[dict]:
    url = GOOGLE_NEWS.format(query=urllib.parse.quote(query))
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    root = ET.fromstring(payload)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        source = item.findtext("{http://news.google.com/rss}source") or ""
        items.append(
            {"title": title, "link": link, "published": published, "source": source.strip()}
        )
    return items


def domain_of(link: str) -> str:
    try:
        return urllib.parse.urlparse(link).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def parse_date(value: str) -> datetime | None:
    for pattern in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_event_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def score_event(title: str, items: list[dict], event_date: datetime | None) -> dict:
    wanted = set(keywords(title))
    domains = {domain_of(item["link"]) for item in items if item["link"]}
    domains.discard("")

    matched_any = 0
    for item in items:
        if wanted & set(keywords(item["title"])):
            matched_any += 1
    keyword_ratio = matched_any / len(items) if items else 0.0

    if event_date:
        near = 0
        for item in items:
            published = parse_date(item["published"])
            if published and abs((published - event_date).days) <= 2:
                near += 1
        date_ratio = near / len(items) if items else 0.0
    else:
        date_ratio = 0.0

    primary = sorted(domains & PRIMARY_DOMAINS)
    score = (
        min(len(domains), 10) * 4          # up to 40 for independent domains
        + round(keyword_ratio * 30)        # up to 30 for topic agreement
        + round(date_ratio * 20)           # up to 20 for date proximity
        + (10 if primary else 0)           # 10 for a primary source
    )
    return {
        "score": min(score, 100),
        "verified": score >= 60,
        "distinct_domains": len(domains),
        "keyword_ratio": round(keyword_ratio, 3),
        "date_ratio": round(date_ratio, 3),
        "primary_sources": primary,
        "domains": sorted(domains)[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a monitored event on the web")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--event-date", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--min-confidence", type=int, default=60)
    args = parser.parse_args()

    query = " ".join(keywords(args.title)[:12]) or args.title
    log(f"query: {query}")
    try:
        items = fetch_rss(query)
    except Exception as error:  # noqa: BLE001
        log(f"news lookup failed: {error}")
        items = []
    log(f"news items: {len(items)}")

    event_date = parse_event_date(args.event_date)
    scoring = score_event(args.title, items, event_date)

    report = {
        "video_id": args.video_id,
        "title": args.title,
        "event_date": args.event_date or None,
        "queried_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "query": query,
        "confidence": scoring["score"],
        "verified": scoring["verified"],
        "evidence": scoring,
        "sources": [
            {
                "title": item["title"],
                "domain": domain_of(item["link"]),
                "published": item["published"],
                "link": item["link"],
            }
            for item in items[:20]
        ],
    }
    target = Path(args.report) if args.report else Path("work/EVENT.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"confidence {report['confidence']}/100 verified={report['verified']}")
    log(f"report: {target}")
    return 0 if report["confidence"] >= args.min_confidence else 1


if __name__ == "__main__":
    raise SystemExit(main())
