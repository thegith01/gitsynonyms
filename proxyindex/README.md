# Proxy index (list of lists)

A reproducible, validated meta-index of public proxy-list sources: instead of one
repository with a few files, this aggregates thousands of repositories and the
proxy files inside them, deduplicates the entries, and records which proxies
actually answer at collection time.

## Pipeline

| Stage | Script | Output |
|---|---|---|
| 0. research terms | `discover_terms.py` | `term_research.jsonl` (one record per term), `sources_extra.txt` (URLs found across forums, social and search) |
| 1. discover sources | `build_index.py` | `sources.txt` (one raw file URL per line), `sources.jsonl` (repo, stars, last push, size) |
| 2. collect and dedupe | `collect.py` | `raw.txt` (every entry), `proxies.txt` (unique `ip:port`), `collect.jsonl` (per-source counts) |
| 3. validate | `validate.py` | `alive_tcp.txt` (socket opens), `alive_http.txt` (real HTTP CONNECT returns 200) |

```bash
python3 discover_terms.py --dry-run          # inspect the term plan without network
python3 discover_terms.py                    # research every term through Last30Days
python3 discover_terms.py --merge            # ... and append new URLs to sources.txt
python3 build_index.py                       # needs the GitHub CLI, authenticated
python3 collect.py
python3 validate.py
```

## Term research across forums, social and search

`build_index.py` can only find repositories whose topics or names already match
its query list. `discover_terms.py` widens that net before discovery: it
enumerates synonyms, near-synonyms and word permutations for "network proxy"
in English and Chinese, asks the Last30Days skill to research each term across
forums, social platforms and search engines, and writes every absolute URL it
actually received to `sources_extra.txt`.

The term plan is deterministic and grouped, so a full sweep can be split across
runs without re-researching a term:

```bash
python3 discover_terms.py --groups core qualifier chinese
python3 discover_terms.py --groups permutation --limit 40
python3 discover_terms.py --terms "proxy pool daily update" --merge
```

| Group | Covers |
|---|---|
| `core` | proxy, proxies, proxy list, proxy pool, proxy server, proxy database, ip pool, 网络代理, 代理列表, 代理池, 代理IP |
| `qualifier` | free, public, open, anonymous, elite, transparent, http, https, socks4/5, rotating, residential, datacenter, working, live, valid, fresh, daily, 免费, 高匿, 住宅, 机房 ... |
| `action` | scraper, crawler, grabber, collector, aggregator, checker, validator, 抓取, 采集, 聚合, 检测, 验证, 筛选 ... |
| `permutation` | qualifier x {proxy list, proxy pool, proxies} |
| `chinese` | 免费代理, 高匿代理池, 可用代理IP, 每日代理列表 ... |
| `scope` | every base term restricted with `site:reddit.com`, `site:news.ycombinator.com`, `site:v2ex.com`, `site:hostloc.com`, `site:github.com`, `forum`, `telegram` ... |

Research follows the repository rule that a missing result is never replaced by
a guess: a term whose research fails is logged with `"ok": false` and an error,
contributes no URLs, and does not stop the rest of the sweep. Use
`LAST30DAYS_SCRIPT` to point at a local `last30days.py`, or have the
`last30days` CLI on `PATH`.

## Why two validation passes

A proxy that accepts a TCP connection is not a proxy that works. The second pass
sends a real request through each survivor (`curl -x http://ip:port
http://example.com/`) and keeps only the ones that return `200`. In practice the
TCP pass keeps an order of magnitude more candidates than the HTTP pass.

## Caveats

- The overwhelming majority of public proxies are dead, slow, or duplicated
  mirrors of the same handful of upstream scrapers; expect a low single-digit
  survival rate and a list that is stale within hours.
- These are untrusted third parties. `CONNECT` tunnels cannot read TLS traffic
  without breaking certificate validation, but the operator still sees which
  hosts you contact. Never send credentials, cookies or private data through
  them.
- Prefer your own egress (a VPS with `ssh -D`, a VPN, or a paid proxy) for
  anything that matters; this index is a last resort for public content.
- Many sources are unlicensed scrapes. Check the licence of a source repository
  before redistributing its data.

## Tiered pool: 1,000,000 → 10,000 → 1,000

`tiered_pool.py` keeps three pools with independent refresh intervals. The
wide scan is cheap per entry, so it runs rarely; the ready pool is expensive
per entry, so it runs often and in small rolling batches.

| Tier | Size | Test | Refresh | File |
|---|---|---|---|---|
| 1 wide | up to 1,000,000 unique, 250,000 TCP-open kept | fetch + TCP connect | every 6 h | `pool/tier1/tier1_open.jsonl` |
| 2 fast | 10,000 | HTTPS `generate_204` through the proxy, lowest latency | every 30 min | `pool/tier2/tier2_fast.txt` |
| 3 ready | 1,000 | real `yt-dlp -g` extraction + 128 KiB ranged media download, highest throughput | every 15 min | `pool/tier3/tier3_ready.txt` |

```bash
python3 proxyindex/tiered_pool.py collect --limit 1000000 --workers 96
python3 proxyindex/tiered_pool.py screen  --limit 250000 --concurrency 800
python3 proxyindex/tiered_pool.py speed   --batch 4000 --target 10000 --max-age 10800
python3 proxyindex/tiered_pool.py ready   --batch 900  --target 1000  --max-age 7200
python3 proxyindex/tiered_pool.py status
```

Each stage only tests candidates whose record is missing or older than its
`--max-age`, so a 15-minute tier-3 run touches roughly 900 proxies instead of
all 10,000. A proxy that fails is recorded in `tier2_failed.json` or
`tier3_failed.json` and skipped until the freshness window expires; without that
memory a rolling batch would retest the same failures every run and never reach
the rest of the pool. Tier 2 samples the pool in a stable hash order rather than
by TCP latency: the fastest TCP handshakes are often services that accept a
socket but are not HTTP proxies, and ordering by them tested 4,000 entries with
zero HTTPS passes. A proxy that succeeds is re-verified before it can expire, so
the ready pool never contains an entry older than two hours.

The pool lives in the Actions cache, not in git. `.github/workflows/proxy-pool.yml`
runs the three cadences; `auto-pipeline.yml` restores the tier-3 cache before
the source download and before the caption stage.

## Consuming the pool for a blocked download

When a direct connection cannot complete a download, the downloader iterates
the freshest available pool — tier 3, then tier 2, then the committed
`alive_http.txt` fallback — and retries through the fastest candidate that
passes the YouTube HTTPS check. `PROXY_POOL_FILE` overrides the file for a
one-off run. A configured `YTDLP_PROXY` secret still short-circuits the public
lookup and is used as the primary egress.

`scripts/select_working_proxy.py` re-validates the proxy that carried the
source download with the same `yt-dlp -J` request the caption stage needs. A
free proxy can die between two steps; reusing it blindly is what made a caption
probe fail with a connect timeout minutes after a successful download.

