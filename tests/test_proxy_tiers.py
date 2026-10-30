from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "proxyindex" / "tiered_pool.py"
SPEC = importlib.util.spec_from_file_location("tiered_pool", SCRIPT)
tiers = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(tiers)


def test_normalize_accepts_plain_and_schemed_entries():
    assert tiers.normalize("1.2.3.4:8080") == "1.2.3.4:8080"
    assert tiers.normalize("http://1.2.3.4:8080/") == "1.2.3.4:8080"
    assert tiers.normalize("256.2.3.4:8080") is None
    assert tiers.normalize("1.2.3.4:0") is None
    assert tiers.normalize("host.example:8080") is None


def test_merge_replaces_a_failed_proxy_instead_of_keeping_the_stale_success():
    now = 1_000_000.0
    existing = [
        {"proxy": "1.1.1.1:80", "latency_ms": 10, "verified_at": int(now) - 10},
        {"proxy": "2.2.2.2:80", "latency_ms": 20, "verified_at": int(now) - 10},
    ]
    tested = [{"proxy": "1.1.1.1:80", "ok": False, "verified_at": int(now)}]

    merged = tiers.merge_records(
        existing, tested, limit=10, max_age=100, now=now, sort_key="latency_ms"
    )

    assert [record["proxy"] for record in merged] == ["2.2.2.2:80"]


def test_merge_drops_records_older_than_the_freshness_window():
    now = 1_000_000.0
    existing = [
        {"proxy": "1.1.1.1:80", "latency_ms": 10, "verified_at": int(now) - 500},
        {"proxy": "2.2.2.2:80", "latency_ms": 20, "verified_at": int(now) - 10},
    ]

    merged = tiers.merge_records(
        existing, [], limit=10, max_age=100, now=now, sort_key="latency_ms"
    )

    assert [record["proxy"] for record in merged] == ["2.2.2.2:80"]


def test_merge_sorts_and_caps_to_the_tier_target():
    now = 1_000_000.0
    existing = [
        {"proxy": f"10.0.0.{index}:80", "latency_ms": 100 - index, "verified_at": int(now)}
        for index in range(20)
    ]

    merged = tiers.merge_records(
        existing, [], limit=5, max_age=100, now=now, sort_key="latency_ms"
    )

    assert len(merged) == 5
    assert [record["latency_ms"] for record in merged] == [81, 82, 83, 84, 85]


def test_rolling_batch_skips_proxies_that_are_still_fresh():
    now = 1_000_000.0
    candidates = [
        {"proxy": "1.1.1.1:80", "latency_ms": 5},
        {"proxy": "2.2.2.2:80", "latency_ms": 10},
        {"proxy": "3.3.3.3:80", "latency_ms": 15},
    ]
    fresh = {"1.1.1.1:80": {"verified_at": int(now) - 5}}

    batch = tiers.rolling_batch(candidates, fresh, batch=10, max_age=100, now=now, key="latency_ms")

    assert [candidate["proxy"] for candidate in batch] == ["2.2.2.2:80", "3.3.3.3:80"]


def test_rolling_batch_retests_a_record_that_expired():
    now = 1_000_000.0
    candidates = [{"proxy": "1.1.1.1:80", "latency_ms": 5}]
    fresh = {"1.1.1.1:80": {"verified_at": int(now) - 500}}

    batch = tiers.rolling_batch(candidates, fresh, batch=10, max_age=100, now=now, key="latency_ms")

    assert [candidate["proxy"] for candidate in batch] == ["1.1.1.1:80"]


def test_write_plain_keeps_the_record_order(tmp_path):
    records = [
        {"proxy": "9.9.9.9:80", "bytes_per_second": 900},
        {"proxy": "8.8.8.8:80", "bytes_per_second": 800},
    ]
    target = tmp_path / "tier3_ready.txt"

    tiers.write_plain(target, records)

    assert target.read_text(encoding="utf-8").splitlines() == ["9.9.9.9:80", "8.8.8.8:80"]


def test_load_jsonl_ignores_broken_and_invalid_records(tmp_path):
    path = tmp_path / "tier.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"proxy": "1.1.1.1:80", "latency_ms": 5}),
                "{not json",
                json.dumps({"proxy": "not-a-proxy", "latency_ms": 5}),
                json.dumps({"proxy": "http://2.2.2.2:80", "latency_ms": 6}),
            ]
        ),
        encoding="utf-8",
    )

    records = tiers.load_jsonl(path)

    assert [record["proxy"] for record in records] == ["1.1.1.1:80", "2.2.2.2:80"]
