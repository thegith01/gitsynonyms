#!/usr/bin/env python3
"""Build the lowest-standard local Immersive Translate bilingual subtitle pair.

Chrome observation of Immersive Translate v1.34.4 on YouTube showed a phrase
window model, not a raw source-cue model: the extension hooks the player's
``/api/timedtext`` json3 response, drops ambient markers such as ``[music]`` and
``>>``, joins the short timed-text phrases that are active at a moment, and
renders one source window with one translated window in a shadow-DOM overlay.
The Chinese line arrives about half a second after the English line while the
translation service responds.

This local baseline mirrors that unit model with the official YouTube English
ASR and its official auto-translated Chinese track. Whole English phrase cues
are grouped into sentence/clause units under the 6.5 s and 60-character reading
budgets. Each whole official Chinese cue is assigned to the English unit it
overlaps most, so a re-segmented translation is never split, and a unit with no
Chinese evidence is merged into the nearest bilingual event instead of being
rendered alone or dropped. A local word-karaoke pass is added because an ASS is
burned offline, but the baseline makes no claim that v1.34.4 itself highlights
words.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_youtube_bilingual_srt as captions  # noqa: E402
import local_bilingual_ass  # noqa: E402
import subtitle_ergonomics  # noqa: E402
import subtitle_timing  # noqa: E402
import subtitle_timeline  # noqa: E402

ENGLISH = "en-orig"
CHINESE = "zh-Hans"
DEFAULT_SRT_NAME = "bilingual_immersive_lowest_Chinese-English.srt"
DEFAULT_ASS_NAME = "bilingual_immersive_lowest_Chinese-English.ass"
DEFAULT_REPORT_NAME = "IMMERSIVE_LOWEST.json"
DEFAULT_ERGONOMICS_NAME = "IMMERSIVE_LOWEST_ERGONOMICS.json"
DEFAULT_BOX_STYLE = "presidential-blue"
DEFAULT_BOX_COLOR = "#0F1647"
CHINESE_TEXT_COLOR = "#FFFFA8"
SCHEME_NAME = "scheme_local__immersive_lowest"
SCHEME_LABEL = "scheme_低级_沉浸翻译（最低 / LOWEST 标准）"
BASELINE_ID = "immersive-translate"
BASELINE_VERSION = "1.34.4"
REA_EVIDENCE_ID = "ev_8afad77784dc3350625bc01599d2ddd910cc811cc08b8f6054508c3d7a25855f"
REA_COVERAGE = (
    "partial: 53 inventoried files, 1 analyzed source; semantic graph truncated"
)
LOWEST_FORMAT_PRIORITY = (
    "json3",
    "srv3",
    "srv2",
    "srv1",
    "ttml",
    "vtt",
    "srt",
)


def _read_source_report(folder: Path) -> dict:
    path = folder / "CAPTION_FORMATS.json"
    if not path.is_file():
        raise ValueError(
            f"{SCHEME_LABEL} requires CAPTION_FORMATS.json to verify that "
            "English is YouTube auto-generated and Chinese is its auto-translation."
        )
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read {path.name}: {error}") from error
    if not isinstance(report, dict) or not isinstance(report.get("tracks"), dict):
        raise ValueError(f"{path.name} has no caption track records")
    return report


def _verify_source_kind(report: dict, language: str, expected_kind: str) -> dict:
    track = report["tracks"].get(language)
    if not isinstance(track, dict) or not track.get("present"):
        raise ValueError(
            f"{report.get('video_id', 'source')} has no verified {language} track"
        )
    actual = track.get("kind")
    if actual != expected_kind:
        raise ValueError(
            f"{language} source is {actual or 'unknown'}, expected {expected_kind}; "
            "refresh the YouTube caption set before building this scheme"
        )
    return {
        "verified": True,
        "kind": actual,
        "youtube_code": track.get("youtube_code"),
        "formats": track.get("formats", []),
        "missing_formats": track.get("missing_formats", []),
    }


def load_source_tracks(folder: Path, video_id: str, media_stem: str | None) -> tuple[dict, dict]:
    source_report = _read_source_report(folder)

    provenance = {}
    tracks = {}
    for language, expected_kind in (
        (ENGLISH, "auto-generated"),
        (CHINESE, "auto-translated"),
    ):
        provenance[language] = _verify_source_kind(
            source_report, language, expected_kind
        )
        files = local_bilingual_ass.discover_reported_formats(
            folder,
            video_id,
            language,
            media_stem,
            source_report["tracks"].get(language, {}),
        )
        if not files:
            raise ValueError(
                f"no official {language} caption formats for {video_id} in {folder}"
            )
        parsed: dict[str, list[dict]] = {}
        failures = {}
        for extension in LOWEST_FORMAT_PRIORITY:
            path = files.get(extension)
            if path is None:
                continue
            try:
                parser = captions.CAPTION_PARSERS[extension]
                cues = parser(
                    path.read_text(encoding="utf-8-sig", errors="replace")
                )
            except captions.SubtitleOverlapError:
                raise
            except (OSError, ValueError) as error:
                failures[extension] = str(error)
                continue
            if cues:
                parsed[extension] = cues
            else:
                failures[extension] = "no usable cues"
        if not parsed:
            raise ValueError(
                f"no readable {language} caption format: "
                + "; ".join(
                    f"{extension}: {error}"
                    for extension, error in failures.items()
                )
            )
        primary_format = next(
            extension
            for extension in LOWEST_FORMAT_PRIORITY
            if extension in parsed
        )
        tracks[language] = {
            "cues": parsed[primary_format],
            "primary_format": primary_format,
            "formats_parsed": [
                extension
                for extension in LOWEST_FORMAT_PRIORITY
                if extension in parsed
            ],
            "formats_used": [primary_format],
            "formats_found": [
                extension
                for extension in LOWEST_FORMAT_PRIORITY
                if extension in files
            ],
            "format_failures": failures,
            "format_sources": {
            extension: files[extension].name
            for extension in LOWEST_FORMAT_PRIORITY
            if extension in files
            },
        }
    return tracks, provenance


# The normal-subtitle ambient filter used by Immersive Translate v1.34.4:
# bracketed sound labels and the ">>" speaker marker are removed before a cue
# becomes a display unit. The AI-subtitle filter also removes parentheses, but
# the normal YouTube path does not, so parentheses stay as spoken text here.
AMBIENT_MARKERS = re.compile(r"\s*\[[^\]]*\]\s*|\s*>>\s*")
SENTENCE_END = re.compile(r"[.!?。！？…][\"'”’)]?$")
CLAUSE_END = re.compile(r"[,;:，；：、][\"'”’)]?$|[-–—][\"'”’)]?$")
CHINESE_FALLBACK_SECONDS = 0.35


def _filter_ambient_cues(cues: Sequence[dict]) -> list[dict]:
    """Remove ambient labels from cue text while preserving its timing.

    A cue that contains nothing but ``[music]``/``>>`` disappears entirely.
    Word timings stay attached: the tokenizer skips the removed labels and
    spreads the remaining words inside the same cue interval.
    """
    filtered = []
    for cue in cues:
        start, end = float(cue["start"]), float(cue["end"])
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end <= start
        ):
            raise ValueError("caption track contains an empty or invalid source cue")
        text = AMBIENT_MARKERS.sub(" ", str(cue.get("text", "")))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        filtered.append({**cue, "text": text})
    return filtered


def _split_clause_tokens(
    tokens: Sequence[subtitle_timeline.Token],
) -> list[list[subtitle_timeline.Token]]:
    """Split one overlong source cue into readable clause pieces.

    This is only a safety valve for a single cue that is wider than one line.
    Normal YouTube phrase cues are 20-40 characters and are grouped whole by
    :func:`_phrase_units`; cutting inside a cue loses the official Chinese
    cue pairing, so it is avoided whenever the source keeps cues short.
    """
    units: list[list[subtitle_timeline.Token]] = []
    current: list[subtitle_timeline.Token] = []
    for token in tokens:
        if current and token.start - current[-1].end > subtitle_timeline.MAX_EVENT_GAP:
            units.append(current)
            current = []
        current.append(token)
        characters = subtitle_timeline._char_count(current)
        duration = current[-1].end - current[0].start
        if subtitle_timeline._sentence_end(token.text):
            if characters <= subtitle_timeline.EN_EVENT_CHARS and duration <= subtitle_timeline.MAX_EVENT_SECONDS:
                units.append(current)
                current = []
                continue
        elif characters <= subtitle_timeline.EN_EVENT_CHARS and duration <= subtitle_timeline.MAX_EVENT_SECONDS:
            continue

        split_at = None
        for index in range(len(current) - 1, 0, -1):
            prefix = current[:index]
            if subtitle_timeline._char_count(prefix) > subtitle_timeline.EN_EVENT_CHARS:
                continue
            if not CLAUSE_END.search(prefix[-1].text):
                continue
            split_at = index
            break
        if split_at is None:
            split_at = len(current) - 1
        if split_at <= 0:
            # A single token that is wider than the line budget cannot be split.
            units.append(current)
            current = []
            continue
        units.append(current[:split_at])
        current = current[split_at:]
    if current:
        units.append(current)
    return [unit for unit in units if unit]


def _token_groups(
    tokens: Sequence[subtitle_timeline.Token],
) -> list[list[subtitle_timeline.Token]]:
    """Collect the de-duplicated tokens of each source phrase cue."""
    groups: dict[int, list[subtitle_timeline.Token]] = {}
    ordered: list[list[subtitle_timeline.Token]] = []
    for token in tokens:
        if token.group not in groups:
            groups[token.group] = []
            ordered.append(groups[token.group])
        groups[token.group].append(token)
    return ordered


def _phrase_units(
    tokens: Sequence[subtitle_timeline.Token],
) -> list[list[subtitle_timeline.Token]]:
    """Group whole phrase cues into readable, bilingual-sized units.

    Immersive Translate receives short timed-text phrases and keeps a moving
    window of them on screen. Grouping whole cues (rather than cutting inside
    one) preserves the official Chinese translation cue that YouTube publishes
    on the same boundary. Cues are joined while the unit stays inside the
    one-line budget, the reading time and the silence gap; a sentence-ending
    cue closes the unit so a new sentence starts a new caption.
    """
    units: list[list[subtitle_timeline.Token]] = []
    current: list[subtitle_timeline.Token] = []
    for group in _token_groups(tokens):
        start = group[0].start
        end = group[-1].end
        characters = subtitle_timeline._char_count(group)
        duration = end - start
        if characters > subtitle_timeline.EN_EVENT_CHARS or duration > subtitle_timeline.MAX_EVENT_SECONDS:
            if current:
                units.append(current)
                current = []
            units.extend(_split_clause_tokens(group))
            continue
        if current:
            gap = start - current[-1].end
            combined = [*current, *group]
            if (
                gap > subtitle_timeline.MAX_EVENT_GAP
                or subtitle_timeline._char_count(combined) > subtitle_timeline.EN_EVENT_CHARS
                or end - current[0].start > subtitle_timeline.MAX_EVENT_SECONDS
                or subtitle_timeline._sentence_end(current[-1].text)
            ):
                units.append(current)
                current = []
        current.extend(group)
        if subtitle_timeline._sentence_end(group[-1].text):
            units.append(current)
            current = []
    if current:
        units.append(current)
    return [unit for unit in units if unit]


def _unit_interval(unit: Sequence[subtitle_timeline.Token]) -> tuple[float, float]:
    return unit[0].start, unit[-1].end


def _assign_chinese_cues(
    units: Sequence[Sequence[subtitle_timeline.Token]],
    chinese_by_cue: dict[int, list[subtitle_timeline.Token]],
) -> tuple[list[list[subtitle_timeline.Token]], list[str], list[dict]]:
    """Assign each whole official Chinese cue to one English unit.

    YouTube's auto-translated Chinese track does not always reuse the English
    phrase grid: when the translator re-segments a sentence, an English phrase
    cue can have no Chinese twin while the neighbouring Chinese cue covers two
    English phrases. Pairing cue-to-cue therefore misplaces translations (an
    English phrase ended up with only "比巴黎" while "更好、更盛大的版本" sat in
    the next caption).

    Immersive Translate translates the phrases that are active at a moment, so
    the faithful unit is the display unit, not the raw source cue. Each whole
    Chinese cue goes to the English unit it overlaps most; a cue that falls in
    a silence gap goes to the nearest unit within 0.35 s, and a still-unplaced
    cue is attached to the nearest unit regardless of distance so no
    translation is dropped. Chinese characters are never split between units.
    """
    intervals = [_unit_interval(unit) for unit in units]
    assigned: list[list[subtitle_timeline.Token]] = [[] for _ in units]
    selections: list[set[str]] = [set() for _ in units]
    unassigned: list[dict] = []

    ordered_groups = sorted(
        chinese_by_cue.values(),
        key=lambda group: (group[0].start, group[-1].end),
    )
    for group in ordered_groups:
        spoken = [
            token
            for token in group
            if not subtitle_timeline.is_punctuation(token.text)
        ]
        if not spoken:
            continue
        group_start = min(token.start for token in group)
        group_end = max(token.end for token in spoken)
        best_index = None
        best_overlap = 0.0
        for index, (start, end) in enumerate(intervals):
            overlap = min(group_end, end) - max(group_start, start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_index = index
        if best_index is not None:
            assigned[best_index].extend(group)
            if (
                abs(intervals[best_index][0] - group_start) <= 0.001
                and abs(intervals[best_index][1] - group_end) <= 0.001
            ):
                selections[best_index].add("cue-aligned")
            else:
                selections[best_index].add("unit-overlap")
            continue

        best_distance = None
        for index, (start, end) in enumerate(intervals):
            distance = max(start - group_end, group_start - end, 0.0)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = index
        if best_index is not None and best_distance <= CHINESE_FALLBACK_SECONDS:
            assigned[best_index].extend(group)
            selections[best_index].add("nearest-fallback")
            continue
        if best_index is not None:
            assigned[best_index].extend(group)
            selections[best_index].add("nearest-fallback")
            unassigned.append(
                {
                    "start": group_start,
                    "end": group_end,
                    "distance": round(best_distance, 3),
                    "text": "".join(token.text for token in group),
                }
            )
            continue
        unassigned.append(
            {
                "start": group_start,
                "end": group_end,
                "distance": None,
                "text": "".join(token.text for token in group),
            }
        )

    methods = [
        (
            "cue-aligned"
            if "cue-aligned" in values
            else "unit-overlap"
            if "unit-overlap" in values
            else "nearest-fallback"
            if "nearest-fallback" in values
            else "missing"
        )
        for values in selections
    ]
    return assigned, methods, unassigned


def _interval_distance(
    left_start: float, left_end: float, right_start: float, right_end: float
) -> float:
    return max(right_start - left_end, left_start - right_end, 0.0)


def _merge_orphan_into_nearest_event(
    events: Sequence[dict], orphan: dict
) -> None:
    """Attach a Chinese-less English unit to the closest bilingual event.

    YouTube occasionally leaves a source phrase without a translated cue (a
    dropped phrase in the auto-translated track). Dropping the English text
    would violate the "every spoken word renders" rule, while emitting it alone
    would violate the bilingual-only rule. The unit is therefore carried by the
    nearest event, so its words still render once inside a bilingual caption.
    """
    start = float(orphan["start"])
    end = float(orphan["end"])
    if not events:
        raise ValueError("no bilingual event is available to carry a source unit")
    target = min(
        events,
        key=lambda event: (
            _interval_distance(
                start, end, float(event["start"]), float(event["end"])
            ),
            0 if float(event["start"]) >= start else 1,
        ),
    )
    before = start < float(target["start"])
    tokens = orphan["_english_tokens"]
    target["_english_tokens"] = (
        [*tokens, *target["_english_tokens"]]
        if before
        else [*target["_english_tokens"], *tokens]
    )
    target["_english_tokens"].sort(key=lambda token: token.start)
    target["start"] = min(float(target["start"]), start)
    target["end"] = max(float(target["end"]), end)
    target["source_start"] = min(float(target["source_start"]), start)
    target["source_end"] = max(float(target["source_end"]), end)
    target["merged_source_units"] = target.get("merged_source_units", 0) + 1
    orphan["disposition"] = "merged-into-neighbor"


def build_source_anchored_events(
    chinese: Sequence[dict], english: Sequence[dict]
) -> tuple[list[dict], list[dict]]:
    """Create bilingual phrase units from the official YouTube tracks.

    Chrome observation of Immersive Translate 1.34.4 showed that it does not
    display one event per raw source cue. It removes ambient labels, keeps a
    moving window of the short timed-text phrases, and translates each visible
    phrase; the Chinese line arrives a fraction of a second later. This local
    baseline reproduces that unit model without copying the Microsoft
    translation engine:

    * English word timings are merged into one monotonic timeline and whole
      phrase cues are grouped into units (sentence end, pause, then the 6.5 s
      / 60-character reading budgets);
    * each whole official Chinese cue is assigned to the English unit it
      overlaps most, so a translation is never split at a source boundary that
      YouTube re-segmented;
    * a unit without Chinese evidence is not rendered alone; its English words
      are merged into the nearest bilingual event so every spoken word renders
      exactly once;
    * a local word-karaoke pass is layered on the ASS because the baseline is
      burned offline, not because v1.34.4 highlights words.
    """
    filtered_chinese = _filter_ambient_cues(chinese)
    filtered_english = _filter_ambient_cues(english)
    if not filtered_chinese:
        raise ValueError(f"{CHINESE} track contains no usable cues")
    if not filtered_english:
        raise ValueError(f"{ENGLISH} track contains no usable cues")
    filtered_chinese.sort(key=lambda cue: (float(cue["start"]), float(cue["end"])))
    filtered_english.sort(key=lambda cue: (float(cue["start"]), float(cue["end"])))

    english_tokens = subtitle_timeline.build_timeline(filtered_english)
    chinese_tokens = subtitle_timeline.build_timeline(filtered_chinese)
    if not english_tokens:
        raise ValueError(f"{ENGLISH} track contains no readable words")
    if not chinese_tokens:
        raise ValueError(f"{CHINESE} track contains no readable words")

    chinese_by_cue: dict[int, list[subtitle_timeline.Token]] = {}
    for token in chinese_tokens:
        chinese_by_cue.setdefault(token.group, []).append(token)

    units = _phrase_units(english_tokens)
    assigned_chinese, unit_methods, _ = _assign_chinese_cues(
        units, chinese_by_cue
    )
    events = []
    unpaired = []
    for index, unit in enumerate(units):
        start, source_end = _unit_interval(unit)
        english_text = captions._single_caption_line(
            " ".join(token.text for token in unit)
        ).strip()
        chinese_unit = assigned_chinese[index]
        chinese_text = captions._single_caption_line(
            "".join(token.text for token in chinese_unit)
        ).strip()
        chinese_text = captions._strip_leading_closers(chinese_text)
        has_chinese = any(
            not subtitle_timeline.is_punctuation(token.text)
            for token in chinese_unit
        )
        midpoint = (start + source_end) / 2
        active_chinese = [
            cue
            for cue in filtered_chinese
            if float(cue["start"]) <= midpoint < float(cue["end"])
        ]
        if not english_text or not chinese_text or not has_chinese:
            unpaired.append(
                {
                    "start": start,
                    "end": source_end,
                    "reason": (
                        "missing-english" if not english_text else "missing-chinese"
                    ),
                    "missing": "English" if not english_text else "Chinese",
                    "active": "Chinese" if not english_text else "English",
                    "english": english_text,
                    "active_chinese_cues": len(active_chinese),
                    "pairing": unit_methods[index],
                    "_english_tokens": unit,
                }
            )
            continue

        end = max(
            source_end,
            max(
                token.end
                for token in chinese_unit
                if not subtitle_timeline.is_punctuation(token.text)
            ),
        )
        if index + 1 < len(units):
            next_start = _unit_interval(units[index + 1])[0]
            end = min(end, next_start)
        if end <= start:
            unpaired.append(
                {
                    "start": start,
                    "end": source_end,
                    "reason": "no-positive-display-duration",
                    "missing": "display duration",
                    "active": "English",
                    "english": english_text,
                    "active_chinese_cues": len(active_chinese),
                    "_english_tokens": unit,
                }
            )
            continue

        events.append(
            {
                "start": start,
                "end": end,
                "source_start": start,
                "source_end": source_end,
                "source_trimmed": end < source_end,
                "chinese": chinese_text,
                "english": english_text,
                "target_selection": unit_methods[index],
                "chinese_token_count": len(chinese_unit),
                "english_token_count": len(unit),
                "active_chinese_cues": len(active_chinese),
                "merged_source_units": 0,
                "english_word_timings": [
                    {
                        "start": token.start,
                        "end": token.end,
                        "text": token.text,
                    }
                    for token in unit
                ],
                "_english_tokens": unit,
            }
        )

    if not events:
        raise ValueError(
            "the official tracks have no bilingual phrase-unit event"
        )

    for orphan in unpaired:
        _merge_orphan_into_nearest_event(events, orphan)
    for event in events:
        tokens = event.pop("_english_tokens")
        event["english"] = captions._single_caption_line(
            " ".join(token.text for token in tokens)
        ).strip()
        event["english_token_count"] = len(tokens)
        event["english_word_timings"] = [
            {"start": token.start, "end": token.end, "text": token.text}
            for token in tokens
        ]
    for orphan in unpaired:
        orphan.pop("_english_tokens", None)

    events.sort(key=lambda event: (float(event["start"]), float(event["end"])))
    return events, unpaired


def render_ass(
    events: Sequence[dict],
    *,
    video_duration: float | None = None,
    box_style: str = DEFAULT_BOX_STYLE,
    box_color: str = DEFAULT_BOX_COLOR,
    box_opacity: float = 0.99,
    caption_order: str = "chinese-first",
) -> str:
    """Render clause-unit bilingual events with the shared ASS styling."""
    monolingual = [
        item for item in events if not item["chinese"] or not item["english"]
    ]
    if monolingual:
        raise ValueError(
            "the lowest-standard renderer only accepts bilingual events"
        )
    bilingual_events = list(events)
    chinese = [
        {"start": item["start"], "end": item["end"], "text": item["chinese"]}
        for item in bilingual_events
    ]
    english = [
        {
            "start": item["start"],
            "end": item["end"],
            "text": item["english"],
            "word_timings": item.get("english_word_timings", []),
        }
        for item in bilingual_events
    ]
    content = captions.build_ass(
        chinese,
        english,
        first_font="Microsoft YaHei",
        second_font="Segoe UI",
        second_font_size=48,
        first_font_scale=1.2,
        first_color=CHINESE_TEXT_COLOR,
        second_color="#F2F1EC",
        english_highlight_color="#9BCBD1",
        cue_aligned=True,
        box_style=box_style,
        box_color=box_color,
        box_opacity=box_opacity,
        caption_order=caption_order,
        video_duration=video_duration,
        max_english_lines=1,
        max_chinese_lines=1,
        prefer_clause_boundaries=True,
    )
    lines = content.splitlines()
    dialogue_indexes = [
        index
        for index, line in enumerate(lines)
        if line.startswith("Dialogue: 1,")
    ]
    if len(dialogue_indexes) == len(bilingual_events):
        for dialogue_index, event in zip(dialogue_indexes, bilingual_events):
            fields = lines[dialogue_index].split(",", 9)
            if len(fields) != 10:
                raise ValueError("Generated lowest-standard ASS has a malformed dialogue.")
            hours, minutes, seconds = fields[1].split(":")
            whole_seconds, fraction = seconds.split(".")
            original_start = (
                int(hours) * 3600
                + int(minutes) * 60
                + int(whole_seconds)
                + int(fraction) / 100
            )
            shift = round((original_start - float(event["start"])) * 100)
            fields[1] = captions.ass_timestamp(float(event["start"]))
            fields[2] = captions.ass_timestamp(float(event["end"]))
            fields[9] = re.sub(
                r"\\kt(\d+)",
                lambda match: f"\\kt{max(0, int(match.group(1)) + shift)}",
                fields[9],
            )
            lines[dialogue_index] = ",".join(fields)

    events = [
        line for line in lines if line.startswith("Dialogue: 1,")
    ]
    other_lines = [
        line for line in lines if not line.startswith("Dialogue: 1,")
    ]

    def timestamp_seconds(value: str) -> float:
        hours, minutes, seconds = value.split(":")
        whole_seconds, fraction = seconds.split(".")
        return (
            int(hours) * 3600
            + int(minutes) * 60
            + int(whole_seconds)
            + int(fraction) / 100
        )

    events.sort(
        key=lambda line: timestamp_seconds(line.split(",", 9)[1])
    )
    for index, line in enumerate(events):
        fields = line.split(",", 9)
        if len(fields) != 10:
            raise ValueError("Generated lowest-standard ASS has a malformed dialogue.")
        start = timestamp_seconds(fields[1])
        end = timestamp_seconds(fields[2])
        if index + 1 < len(events):
            next_start = timestamp_seconds(events[index + 1].split(",", 9)[1])
            if end > next_start:
                if next_start <= start:
                    raise ValueError(
                        "Generated lowest-standard ASS contains simultaneous "
                        "display events that cannot be separated."
                    )
                fields[2] = captions.ass_timestamp(next_start)
        if timestamp_seconds(fields[2]) <= start:
            raise ValueError(
                "Generated lowest-standard ASS contains a zero-duration event "
                "after overlap correction."
            )
        events[index] = ",".join(fields)
    return "\n".join([*other_lines, *events]) + "\n"


def _ass_dialogue_to_srt(ass_text: str) -> str:
    """Mirror the rendered ASS dialogues as an SRT file.

    The ASS renderer may split a merged source unit to keep both languages on
    one line; writing the SRT from the same dialogues keeps the two deliverables
    frame-for-frame identical instead of leaving the SRT on pre-split units.
    """
    blocks = []
    for line in ass_text.splitlines():
        if not line.startswith("Dialogue: 1,"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            raise ValueError("Generated lowest-standard ASS has a malformed dialogue.")
        start = _ass_timestamp_seconds(fields[1])
        end = _ass_timestamp_seconds(fields[2])
        text = re.sub(r"\{[^}]*\}", "", fields[9])
        text = text.replace(r"\N", "\n").replace(r"\h", " ")
        lines = [part.strip() for part in text.splitlines()]
        lines = [part for part in lines if part]
        if not lines:
            continue
        blocks.append(
            f"{len(blocks) + 1}\n"
            f"{captions.format_timestamp(start)} --> "
            f"{captions.format_timestamp(end)}\n"
            + "\n".join(lines)
        )
    if not blocks:
        raise ValueError("Generated lowest-standard ASS has no dialogue event.")
    return "\n\n".join(blocks) + "\n"


def _ass_timestamp_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def build(
    folder: Path,
    video_id: str,
    media: Path | None = None,
    *,
    srt_path: Path | None = None,
    ass_path: Path | None = None,
    report_path: Path | None = None,
    ergonomics_path: Path | None = None,
    fps: float = 24.0,
    strict: bool = False,
    box_style: str = DEFAULT_BOX_STYLE,
    box_color: str = DEFAULT_BOX_COLOR,
    box_opacity: float = 0.99,
    caption_order: str = "chinese-first",
) -> dict:
    folder = Path(folder)
    media = media or local_bilingual_ass.media_file(folder, video_id)
    tracks, provenance = load_source_tracks(
        folder, video_id, media.stem if media else None
    )
    events, unpaired = build_source_anchored_events(
        tracks[CHINESE]["cues"], tracks[ENGLISH]["cues"]
    )
    raw_video_duration = local_bilingual_ass.probe_duration(media)
    video_duration = local_bilingual_ass.ass_coverage_duration(
        raw_video_duration
    )
    if box_style != "none" and video_duration is None:
        raise ValueError(
            "a readable local video duration is required for full-video caption-box coverage"
        )

    srt_file = (srt_path or folder / DEFAULT_SRT_NAME).expanduser().resolve()
    ass_file = (ass_path or folder / DEFAULT_ASS_NAME).expanduser().resolve()
    report_file = (
        report_path or folder / DEFAULT_REPORT_NAME
    ).expanduser().resolve()
    ergonomics_file = (
        ergonomics_path or folder / DEFAULT_ERGONOMICS_NAME
    ).expanduser().resolve()
    for destination in (srt_file, ass_file, report_file, ergonomics_file):
        destination.parent.mkdir(parents=True, exist_ok=True)

    ass_text = render_ass(
        events,
        video_duration=video_duration,
        box_style=box_style,
        box_color=box_color,
        box_opacity=box_opacity,
        caption_order=caption_order,
    )
    ass_file.write_text(ass_text, encoding="utf-8-sig")
    srt_file.write_text(_ass_dialogue_to_srt(ass_text), encoding="utf-8")
    ergonomics = subtitle_ergonomics.analyze_subtitle(ass_file, fps=fps)
    subtitle_ergonomics.write_report(ergonomics_file, ergonomics)

    target_persistence_events = sum(
        1
        for left, right in zip(events, events[1:])
        if left["chinese"] == right["chinese"]
    )
    trimmed_source_events = sum(
        1 for event in events if event["source_trimmed"]
    )
    max_active_chinese = max(
        (event["active_chinese_cues"] for event in events), default=0
    )
    multi_cue_chinese_intervals = sum(
        1 for event in events if event["active_chinese_cues"] > 1
    )
    target_selection_counts = dict(
        sorted(Counter(event["target_selection"] for event in events).items())
    )
    merged_source_units = sum(
        event.get("merged_source_units", 0) for event in events
    )
    source_unit_count = len(events) + len(unpaired)

    report = {
        "generated_at": subtitle_timing.utc_now(),
        "video_id": video_id,
        "scheme": SCHEME_LABEL,
        "scheme_id": SCHEME_NAME,
        "baseline": {
            "id": BASELINE_ID,
            "version": BASELINE_VERSION,
            "rea_evidence_id": REA_EVIDENCE_ID,
            "rea_coverage": REA_COVERAGE,
            "observed_model": (
                "short timed-text phrase units: ambient labels removed, "
                "overlapping visible phrases joined while active, each visible "
                "unit translated into the target line; no word karaoke in the "
                "extension overlay"
            ),
            "source_anchored": True,
            "active_cues_joined": True,
            "clause_units": True,
            "target_persistence": False,
            "cross_cue_deduplication": True,
            "monolingual_events": 0,
            "word_karaoke": False,
            "local_word_karaoke": True,
        },
        "sources": {
            language: {
                "youtube": provenance[language],
                "primary_format": tracks[language]["primary_format"],
                "formats_found": tracks[language]["formats_found"],
                "formats_parsed": tracks[language]["formats_parsed"],
                "formats_used": tracks[language]["formats_used"],
                "format_sources": tracks[language]["format_sources"],
                "format_failures": tracks[language]["format_failures"],
                "cue_count": len(tracks[language]["cues"]),
            }
            for language in (ENGLISH, CHINESE)
        },
        "style": {
            "caption_order": caption_order,
            "chinese_color": CHINESE_TEXT_COLOR,
            "box_style": box_style,
            "box_color": box_color,
            "box_opacity": box_opacity,
            "box_area": list(captions.CAPTION_BOX_AREA),
            "video_duration": raw_video_duration,
            "background_end": video_duration,
        },
        "synchronization": {
            "method": (
                "whole English phrase cues are grouped into sentence/clause "
                "units under the 6.5 s and 60-character reading budgets; each "
                "whole official Chinese cue is assigned to the English unit it "
                "overlaps most, so a re-segmented translation is never split; "
                "a Chinese-less English unit is merged into the nearest "
                "bilingual event so no spoken word is dropped and no event is "
                "monolingual"
            ),
            "event_count": len(events),
            "rendered_event_count": ergonomics["summary"].get("cues"),
            "overwide_event_splits": max(
                0, ergonomics["summary"].get("cues", len(events)) - len(events)
            ),
            "bilingual_event_count": len(events),
            "events_are_bilingual": True,
            "source_anchored": True,
            "clause_units": True,
            "source_cue_count": len(tracks[ENGLISH]["cues"]),
            "source_unit_count": source_unit_count,
            "source_cues_skipped": len(unpaired) - merged_source_units,
            "source_units_skipped": len(unpaired) - merged_source_units,
            "source_units_merged": merged_source_units,
            "unpaired_intervals": len(unpaired),
            "unpaired_intervals_skipped": False,
            "unpaired_intervals_merged": True,
            "unpaired_details": unpaired,
            "monolingual_events": 0,
            "target_persistence_events": target_persistence_events,
            "trimmed_source_events": trimmed_source_events,
            "max_active_chinese_cues": max_active_chinese,
            "multi_cue_chinese_intervals": multi_cue_chinese_intervals,
            "target_selection_counts": target_selection_counts,
            "english_tokens_rendered": sum(
                event["english_token_count"] for event in events
            ),
            "chinese_tokens_rendered": sum(
                event["chinese_token_count"] for event in events
            ),
        },
        "outputs": {
            "srt": srt_file.name,
            "ass": ass_file.name,
            "ergonomics": ergonomics_file.name,
        },
        "ergonomics_summary": ergonomics["summary"],
    }
    report_file.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if strict and ergonomics["summary"]["errors"]:
        raise ValueError(
            f"ergonomics found {ergonomics['summary']['errors']} errors; "
            f"see {ergonomics_file.name}"
        )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"Build {SCHEME_LABEL} bilingual subtitles."
    )
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--srt-output", type=Path)
    parser.add_argument("--ass-output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ergonomics-report", type=Path)
    parser.add_argument("--fps", type=float, default=24.0)
    parser.add_argument(
        "--box-style",
        choices=(*captions.BOX_STYLES, "none"),
        default=DEFAULT_BOX_STYLE,
    )
    parser.add_argument("--box-color", default=DEFAULT_BOX_COLOR)
    parser.add_argument("--box-opacity", type=float, default=0.99)
    parser.add_argument(
        "--caption-order",
        choices=("chinese-first", "english-first"),
        default="chinese-first",
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build(
            args.directory,
            args.video_id,
            args.media,
            srt_path=args.srt_output,
            ass_path=args.ass_output,
            report_path=args.report,
            ergonomics_path=args.ergonomics_report,
            fps=args.fps,
            strict=args.strict,
            box_style=args.box_style,
            box_color=args.box_color,
            box_opacity=args.box_opacity,
            caption_order=args.caption_order,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"{SCHEME_LABEL} failed: {error}", file=sys.stderr)
        return 1
    print(
        f"{report['scheme']}: {report['synchronization']['event_count']} "
        f"bilingual clause events from "
        f"{report['synchronization']['source_unit_count']} source units; "
        f"{report['synchronization']['source_units_merged']} merged into "
        "neighbouring captions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
