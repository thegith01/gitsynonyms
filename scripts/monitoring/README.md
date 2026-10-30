# White House video monitor

`.github/workflows/monitor-whitehouse.yml` checks the latest entries in
`@WhiteHouse/videos` every five minutes, GitHub Actions' shortest supported
schedule interval. GitHub may delay scheduled jobs during periods of high load.
The `/streams` tab is not scanned by default: it fills with livestream entries
that only become usable replays after they end, so the uploads tab keeps the
scan focused. A manual run with `include_streams=true` adds `/streams` after
`/videos` has been exhausted.
It reads flat channel listings and ignores individual metadata failures during
discovery, then downloads the selected video's captions and media.

The workflow handles one unprocessed upload per run. It downloads both
`zh-Hans` and `en-orig` captions, burns the bilingual ASS into a 1080p MP4 on
the cloud runner, backs the source and deliverables up to filebin, publishes the
MP4 to a GitHub Release, and lets the Jekyll workflow regenerate the Pages site.
It records an ID only after the pipeline succeeds, so failed runs can retry.
The processed ID list is `.github/state/whitehouse-processed-videos.txt`.

Each scan retries the newest unprocessed upload until it succeeds or a newer
upload replaces it at the top of the channel listing; a failure never marks the
video as processed. `force_check` reprocesses the newest upload even when it is
already recorded, and a manual `video_id` run skips the channel listing.

YouTube may require authentication from hosted runners. The pipeline uses the
configured proxy pool (`YTDLP_PROXY` or the discovered public pool) and in
accordance with `DIRECTIVE.md` never stores YouTube cookies. Captions come from
YouTube's seven public formats (`json3`, `srv3`, `srv2`, `srv1`, `ttml`, `vtt`,
`srt`); the ASR path only runs when the caption report proves YouTube publishes
no English track, not when the caption probe itself failed.

When no `YTDLP_PROXY` secret is set and a direct download cannot complete, the
monitor falls back to the fastest working public proxy from the proxy index
(the validated pool or every discovered proxy list), instead of failing on the
first blocked direct egress.

`workflow_dispatch` can reprocess the latest upload with `force_check`, or process a specific video with `video_id` (the resolver then skips the channel listing). The designated single-asset source `yt:9aPyO1jfDGM` is processed this way; it has no caption track, so the subtitle stage fails loudly instead of substituting one. Manual
runs must target `main` to publish. The workflow requires permissions to write
contents and to start the reusable pipeline workflow.

`install_workflow.py` copies the tracked workflow template into
`.github/workflows/`; the template and installed workflow should be kept in sync.

## Module 1: material acquisition

`acquisition.py` is the evidence-gathering layer. It reads a source registry
(official RSS, GDELT, the Factbase calendar, the White House YouTube channels)
and maintains `output/materials/ledger.jsonl` plus a materialised
`manifest.json` for downstream analysis. Each record carries its source, URL,
fetch time, content checksum, revision and a quality grade:

- `A` payload captured and hashed (`--fetch-articles`, `--download`),
- `B` citable reference, no payload,
- `C` rejected as insufficient (`status` stays `rejected` for audit).

The same event seen in two sources is merged once and counted as corroboration
(`details.also_seen_in`, `events[].corroboration`). A dead source is reported
as `unavailable`/`error` and never stops the rest of the run. `sources`,
`collect` and `report` subcommands are documented in the repository README;
`tests/test_acquisition.py` covers the behaviour offline.

