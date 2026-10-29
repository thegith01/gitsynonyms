#!/usr/bin/env python3
"""Build a duplicate-free, millisecond caption timeline from YouTube cues.

YouTube's rolling captions re-send a moving window of the same words: cue *n*
shows the tail of cue *n-1* plus new words, and the old ASS writer re-emitted
every active cue at every boundary. The result was the reported defect — the
same sentence stayed visible for several events, then appeared again in the
next one — plus karaoke words whose highlight drifted because duplicate tokens
matched the wrong timing.

This module turns cues into one monotonic token timeline per language:

* every token keeps its absolute start/end from ``json3``/``srv3`` when the
  source provides them (millisecond resolution);
* a rolling cue only contributes the tokens that are genuinely new;
* immediate ASR stutters such as ``I I`` are collapsed, but intentional
  repetition in normal content is not touched;
* captions are segmented into disjoint display events, so a word is rendered
  exactly once.

Nothing here guesses at meaning: tokens are selected by time, and words are
never dropped silently.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

CJK = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]"
)
CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
NON_CJK_CHUNK = re.compile(
    r"[^\s\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+"
)
PUNCTUATION = re.compile(r"^[\s，。、；：！？…·（）〔〕〈〉《》「」『』【】‘’“”%,.;:!?()\[\]{}<>\"'—–-]+$")
# Formatting that carries no spoken content. ``parse_srt`` already keeps
# HTML tags in the cue text, and a tag is not a word: leaving it in makes the
# tokenizer place ``<b>`` on the English line and splits the styled phrase.
STYLE_TAG = re.compile(r"</?(?:b|i|u|s)>|<br\s*/?>|{\\[biu][01]}|{\\an\d}", re.IGNORECASE)

# Closed-class words that are never intentionally doubled in a speech
# transcript. Restricting the stutter collapse to this list protects real
# repetition such as "no no", "very very", or a chanted slogan.
DEDUPE_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "at",
    "for", "with", "is", "are", "was", "were", "be", "been", "it", "that",
    "this", "we", "you", "they", "he", "she", "his", "her", "their", "our",
    "my", "me", "us", "them", "as", "so", "if", "then", "than", "from",
    "by", "not", "i",
}

MAX_EVENT_SECONDS = 6.5
MIN_EVENT_SECONDS = 1.2
MAX_EVENT_GAP = 0.65
# Two lines of the renderer's 42-character English line is 84 characters; a
# smaller budget used to split a caption that the layout would have wrapped
# cleanly, leaving "First Lady Melania Trump." on two unrelated events.
EN_EVENT_CHARS = 84
ZH_EVENT_CHARS = 32
# A period inside an initial or a title is not the end of a sentence.
ABBREVIATION = re.compile(
    r"^(?:[A-Za-z]|Mr|Mrs|Ms|Dr|Prof|Sen|Rep|Gov|Gen|Col|Lt|Sgt|St|Jr|Sr|"
    r"vs|etc|No|Inc|Corp|Co|Ave|Blvd|Rd|U\.S|U\.K)\.$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Token:
    text: str
    start: float
    end: float
    language: str
    exact: bool = True
    group: int = -1

    @property
    def normalized(self) -> str:
        return normalize_token(self.text)


def normalize_token(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("，。、；：！？…·（）〔〕〈〉《》「」『』【】‘’“”%,.;:!?()[]{}<>\"'—–-").casefold()


def is_punctuation(value: str) -> bool:
    return bool(PUNCTUATION.match(value))


def _is_cjk_token(value: str) -> bool:
    return bool(CJK.search(value))


def _clean(text: str) -> str:
    text = STYLE_TAG.sub("", text)
    return re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()


def tokenize_cue(cue: dict, *, group: int = -1) -> list[Token]:
    """Turn one cue into display tokens with absolute times.

    English is split on whitespace so punctuation stays attached to its word;
    Chinese is split per character so a long translated cue can be placed on a
    precise time without cutting a Latin acronym in half.
    """
    text = _clean(str(cue.get("text", "")))
    if not text:
        return []
    start = float(cue.get("start", 0.0))
    end = float(cue.get("end", start))
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        return []

    if _is_cjk_token(text):
        # Keep the source order: CJK characters and Latin/punctuation chunks
        # are interleaved, not grouped by kind.
        matches = list(
            re.finditer(
                r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|[^\s\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+",
                text,
            )
        )
        parts = [match.group(0) for match in matches]
        timings = cue.get("word_timings") or []
        times, exact = _distribute(parts, start, end, timings, chinese=True)
    else:
        matches = list(re.finditer(r"\S+", text))
        parts = [match.group(0) for match in matches]
        timings = cue.get("word_timings") or []
        times, exact = _distribute(parts, start, end, timings, chinese=False)

    cue_is_cjk = _is_cjk_token(text)
    tokens = []
    for part, span, match in zip(parts, times, matches):
        if not part.strip():
            continue
        # "唐纳德·J·特朗普" must stay on the Chinese line: an ASCII fragment
        # glued to CJK on both sides is part of that word, not an English word.
        glued = (
            cue_is_cjk
            and not CJK.search(part)
            and not re.search(r"\s", part)
            and (
                (match.start() > 0 and CJK.match(text[match.start() - 1]))
                or (match.end() < len(text) and CJK.match(text[match.end()]))
            )
        )
        language = (
            "zh"
            if CJK.search(part)
            or glued
            or (
                (is_punctuation(part) or (part.startswith("{") and part.endswith("}")))
                and cue_is_cjk
            )
            else "en"
        )
        tokens.append(
            Token(
                text=part,
                # A cue that holds a finished line (VTT keeps it on screen
                # until the next boundary) carries word timings whose tail runs
                # to the cue's original end, and ``build_ass`` has already
                # trimmed that end. Clamp to it or the last word keeps the
                # whole hold interval and the dialogue never gives the screen
                # back.
                start=min(max(span[0], start), end),
                end=min(max(span[1], start), end),
                language=language,
                exact=exact,
                group=group,
            )
        )
    return tokens


def _spread(
    parts: Sequence[str],
    indexes: Sequence[int],
    gap_start: float,
    gap_end: float,
    spans: list[tuple[float, float] | None],
) -> None:
    """Fill one untimed stretch of a cue, evenly across its spoken tokens."""
    spoken = [index for index in indexes if not is_punctuation(parts[index])]
    gap_end = max(gap_start, gap_end)
    if not spoken:
        for index in indexes:
            spans[index] = (gap_start, gap_start)
        return
    step = (gap_end - gap_start) / len(spoken)
    cursor = gap_start
    for index in indexes:
        if is_punctuation(parts[index]):
            spans[index] = (cursor, cursor)
            continue
        finish = min(gap_end, cursor + step)
        spans[index] = (cursor, max(finish, cursor))
        cursor = finish


def _align_timings(
    parts: Sequence[str],
    usable: Sequence[int],
    timings: Sequence[dict],
    start: float,
    end: float,
) -> list[tuple[float, float] | None] | None:
    """Place word timings on their matching display tokens.

    VTT often timestamps only part of a line: the rolling prefix is plain text
    and only the newly spoken words carry ``<00:00:..>`` tags. Matching by the
    timing's own text (instead of assuming position zero) keeps
    ``the United States`` on its real milliseconds instead of spreading it over
    the whole cue — which used to misplace the first word of the line and then
    pull the next event onto the wrong clock.
    """
    if not timings:
        return None
    positional = len(timings) == len(usable) and not any(
        str(timing.get("text", "")).strip() for timing in timings
    )
    spans: list[tuple[float, float] | None] = [None] * len(parts)
    anchors: list[tuple[int, float, float]] = []
    cursor = 0
    for timing in timings:
        wanted = normalize_token(str(timing.get("text", "")))
        found = None
        if positional:
            found = cursor
        elif wanted:
            for position in range(cursor, len(usable)):
                if normalize_token(parts[usable[position]]) == wanted:
                    found = position
                    break
        if found is None or found >= len(usable):
            continue
        anchors.append(
            (
                found,
                min(max(float(timing.get("start", start)), start), end),
                min(max(float(timing.get("end", end)), start), end),
            )
        )
        cursor = found + 1
    if not anchors:
        return None

    position = 0
    gap_start = start
    for found, timing_start, timing_end in anchors:
        _spread(parts, usable[position:found], gap_start, timing_start, spans)
        part_index = usable[found]
        spans[part_index] = (timing_start, max(timing_end, timing_start))
        position = found + 1
        gap_start = max(gap_start, timing_end)
    _spread(parts, usable[position:], gap_start, end, spans)
    return spans


def _distribute(
    parts: Sequence[str],
    start: float,
    end: float,
    timings: Sequence[dict],
    *,
    chinese: bool,
) -> tuple[list[tuple[float, float]], bool]:
    """Assign a time span to every display token.

    When the cue carries word timings and they line up with the display tokens
    we use them verbatim. Otherwise the cue interval is divided by token width;
    Chinese punctuation receives a zero-length span at the previous character
    so it does not steal time from speech.
    """
    if not parts:
        return [], False
    usable = [index for index, part in enumerate(parts) if not is_punctuation(part)]
    if not usable:
        return [(start, end) for _ in parts], False

    if timings:
        aligned = _align_timings(parts, usable, timings, start, end)
        if aligned is not None:
            previous = (start, start)
            for index, span in enumerate(aligned):
                if span is None:
                    aligned[index] = previous
                previous = aligned[index]
            return aligned, True

    # Every spoken token gets the same share of the cue. Word timings above
    # already carry the exact per-word starts; this fallback is only for
    # formats without them (SRT, VTT without cue timings, plain text).
    weights = []
    for part in parts:
        weights.append(0.0 if is_punctuation(part) else 1.0)
    total = sum(weights) or 1.0
    cursor = start
    result = []
    for part, weight in zip(parts, weights):
        if weight == 0:
            result.append((cursor, cursor))
            continue
        span = (end - start) * weight / total
        result.append((cursor, min(end, cursor + span)))
        cursor = min(end, cursor + span)
    if result:
        result[-1] = (result[-1][0], end)
    return result, False


def _overlap_length(previous: Sequence[Token], current: Sequence[Token]) -> int:
    """Longest suffix of ``previous`` that is the prefix of ``current``."""
    limit = min(len(previous), len(current), 40)
    for count in range(limit, 1, -1):
        left = [token.normalized for token in previous[-count:]]
        right = [token.normalized for token in current[:count]]
        if left == right and any(left):
            return count
    return 0


def build_timeline(cues: Sequence[dict]) -> list[Token]:
    """Merge cues into one monotonic, duplicate-free token timeline.

    Order comes from the cue text, not from sorting token start times: rolling
    cues overlap in time, and sorting by start interleaves words from different
    cues ("the President of" + "the United States" became "the the United").
    Only the genuinely new suffix of each rolling cue is appended.
    """
    ordered = sorted(cues, key=lambda cue: (float(cue.get("start", 0)), float(cue.get("end", 0))))
    starts = [float(cue.get("start", 0)) for cue in ordered]
    timeline: list[Token] = []
    previous_end = 0.0
    for cue_index, cue in enumerate(ordered):
        # Without word timings (SRT, plain VTT) spreading a cue over its whole
        # span collides with the next cue that starts inside it. Cap the spoken
        # window at the next cue's start so the text stays on one clock; the
        # real per-word timings of json3 are never touched.
        speech_end = float(cue.get("end", 0))
        if not cue.get("word_timings"):
            later = next(
                (value for value in starts[cue_index + 1 :] if value > starts[cue_index]),
                None,
            )
            if later is not None and later < speech_end:
                speech_end = later
        tokens = tokenize_cue({**cue, "end": speech_end}, group=cue_index)
        if not tokens:
            continue
        # A rolling window starts while the previous cue is still on screen —
        # sometimes exactly at its end (VTT writes touching cues, json3 writes
        # overlapping ones). Only in that case can the cue repeat an earlier
        # window, so ``_overlap_length`` is allowed to trim it; a cue that
        # starts after a real pause is new speech even if it repeats a phrase.
        rolling_window = float(cue.get("start", 0)) <= previous_end + 0.001
        overlap = _overlap_length(timeline, tokens) if rolling_window else 0
        new_tokens = tokens[overlap:]
        if not new_tokens:
            previous_end = max(previous_end, float(cue.get("end", 0)))
            continue
        floor = timeline[-1].start + 0.01 if timeline else 0.0
        if new_tokens[0].start < floor and all(token.exact for token in new_tokens):
            # Keep the millisecond starts where they are still in order; only
            # push a late cue's first word past its predecessor.
            shifted = []
            cursor = floor
            for token in new_tokens:
                start = max(token.start, cursor)
                end = max(start + 0.04, token.end)
                shifted.append(Token(token.text, start, end, token.language, True, token.group))
                cursor = start + 0.01
            new_tokens = shifted
        timeline.extend(new_tokens)
        previous_end = max(previous_end, float(cue.get("end", 0)))

    # Collapse an immediate ASR stutter ("I I", "the the") without touching
    # content words that can be intentionally repeated.
    collapsed: list[Token] = []
    for token in timeline:
        if (
            collapsed
            and token.language == "en"
            and collapsed[-1].language == "en"
            and token.normalized
            and token.normalized == collapsed[-1].normalized
            and token.normalized in DEDUPE_STOPWORDS
            and 0 <= token.start - collapsed[-1].start <= 0.45
        ):
            previous = collapsed[-1]
            collapsed[-1] = Token(
                previous.text,
                previous.start,
                max(previous.end, token.end),
                "en",
                previous.exact,
                previous.group,
            )
            continue
        collapsed.append(token)

    # Enforce a single monotonic track without reordering the text. Exact word
    # timings are clamped; a translated track keeps its own cue times because
    # rolling translation cues legitimately overlap.
    normalized: list[Token] = []
    for token in collapsed:
        start = token.start
        if token.exact and normalized:
            start = max(start, normalized[-1].start + 0.01)
        end = max(start + 0.04, token.end)
        normalized.append(Token(token.text, start, end, token.language, token.exact, token.group))
    for index in range(len(normalized) - 1):
        token = normalized[index]
        if not token.exact:
            continue
        next_start = normalized[index + 1].start
        if token.end > next_start:
            normalized[index] = Token(
                token.text,
                token.start,
                max(token.start + 0.04, next_start),
                token.language,
                token.exact,
                token.group,
            )
    return [token for token in normalized if token.end > token.start]


def _char_count(tokens: Iterable[Token]) -> int:
    total = 0.0
    for token in tokens:
        if is_punctuation(token.text):
            continue
        if token.language == "zh":
            total += 1
        else:
            # Count real characters (plus the joining space): the layout wraps
            # at 42 characters per line, so an event must stay near 84, not
            # 84 em units, or the renderer receives a four-line paragraph.
            total += len(token.text) + 1
    return int(round(total))


def _sentence_end(text: str) -> bool:
    stripped = text.strip()
    if ABBREVIATION.match(stripped):
        return False
    return bool(re.search(r"[.!?。！？…][\"'”’)]?$", stripped))


def segment_timeline(
    tokens: Sequence[Token],
    *,
    max_seconds: float = MAX_EVENT_SECONDS,
    max_chars: int = EN_EVENT_CHARS,
    max_gap: float = MAX_EVENT_GAP,
    min_seconds: float = MIN_EVENT_SECONDS,
) -> list[list[Token]]:
    """Split a token timeline into disjoint, readable display events."""
    if not tokens:
        return []
    events: list[list[Token]] = []
    index = 0
    while index < len(tokens):
        end_index = index
        while end_index + 1 < len(tokens):
            current = tokens[end_index]
            upcoming = tokens[end_index + 1]
            candidate = tokens[index : end_index + 2]
            same_group = upcoming.group == current.group and upcoming.group >= 0
            duration = upcoming.end - tokens[index].start
            gap = upcoming.start - current.end
            # A source cue is one unit: only the render budget may cut it in
            # half. Duration and pauses are judged between cues, so a long
            # auto-translated cue does not get split into unreadable fragments.
            if _char_count(candidate) > max_chars:
                break
            if duration > max_seconds and not same_group:
                break
            if gap > max_gap:
                break
            if (
                _sentence_end(current.text)
                and current.end - tokens[index].start >= 1.5
                and _char_count(candidate) >= 14
            ):
                break
            end_index += 1

        event = tokens[index : end_index + 1]
        # A very short fragment reads as a flash; merge it with the next event
        # when the combined caption still fits.
        while (
            end_index + 1 < len(tokens)
            and tokens[end_index].end - event[0].start < min_seconds
            and tokens[end_index + 1].end - event[0].start <= max_seconds
            and tokens[end_index + 1].start - tokens[end_index].end <= max_gap
            and _char_count(tokens[index : end_index + 2]) <= max_chars
        ):
            end_index += 1
            event = tokens[index : end_index + 1]

        events.append(event)
        index = end_index + 1
    return events


def assign_tokens(
    events: Sequence[list[Token]], tokens: Sequence[Token]
) -> list[list[Token]]:
    """Assign every token to exactly one event, keeping source cues whole.

    Tokens created from one source cue share a ``group`` id. A translated
    rolling cue is one contiguous phrase, so assigning its characters one by
    one by their interpolated midpoint split the phrase across English events
    and interleaved it with the next cue ("美国总统唐纳德·特第一夫" /
    "朗普和..."). The whole group is placed by the midpoint of its own span,
    and groups never move backwards in event order.
    """
    if not events:
        return []
    starts = [event[0].start for event in events]
    groups: dict[object, list[Token]] = {}
    for position, token in enumerate(tokens):
        key: object = (
            (token.language, token.group) if token.group >= 0 else ("", -1, position)
        )
        groups.setdefault(key, []).append(token)
    assigned: list[list[Token]] = [[] for _ in events]
    event_index = 0
    for group in groups.values():
        midpoint = (group[0].start + group[-1].end) / 2
        found = _rightmost_start(starts, midpoint)
        event_index = max(event_index, max(0, min(len(events) - 1, found)))
        assigned[event_index].extend(group)
    return assigned


def _rightmost_start(starts: Sequence[float], value: float) -> int:
    """Index of the last start <= value (0 when ``value`` is before all)."""
    low, high = 0, len(starts)
    while low < high:
        middle = (low + high) // 2
        if starts[middle] <= value:
            low = middle + 1
        else:
            high = middle
    return low - 1


def _monotonic(tokens: Sequence[Token]) -> list[Token]:
    """Keep text order while preventing a later token from starting earlier."""
    result: list[Token] = []
    for token in tokens:
        start = token.start
        if result:
            start = max(start, result[-1].start + 0.01)
        result.append(
            Token(
                token.text,
                start,
                max(start + 0.04, token.end),
                token.language,
                token.exact,
                token.group,
            )
        )
    return result


def _merge_unique(*groups: Sequence[Token]) -> list[Token]:
    """Concatenate tracks and drop an exactly repeated token.

    The normal call has one English and one Chinese track, so this is a no-op.
    Passing the same cue list in both positions (some layout tests do) must not
    render every character twice.
    """
    seen: set[tuple[str, str, int, int]] = set()
    merged: list[Token] = []
    for group in groups:
        for token in group:
            key = (
                token.language,
                token.text,
                round(token.start * 1000),
                round(token.end * 1000),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(token)
    return merged


def build_display_events(
    cues: Sequence[dict],
    *,
    other_cues: Sequence[dict] | None = None,
) -> list[tuple[list[Token], list[Token]]]:
    """Return ``(english_tokens, chinese_tokens)`` for each display event.

    ``cues`` is the master track (normally English, because it carries word
    timings); ``other_cues`` is the second language. Both are classified by
    script, so a mixed cue still lands on the right line.
    """
    first_tokens = build_timeline(cues)
    second_tokens = build_timeline(other_cues or [])
    if not first_tokens and not second_tokens:
        return []

    # The master (`cues`) supplies the English clock; the other track is the
    # Chinese line. Latin fragments in a translated cue stay on that line
    # instead of competing for the English clock.
    # The master track owns the English clock. A translated track often keeps
    # Latin names and acronyms ("Mcronone", "2019") that tokenize as English;
    # merging them into the master list lets _monotonic() push every real
    # English word behind the last translation fragment, so the English
    # captions disappear until the end of the film. Prefer the master track,
    # and fall back to the other track only when the master has no English.
    master_english = [token for token in first_tokens if token.language == "en"]
    other_english = [token for token in second_tokens if token.language == "en"]
    if master_english and (
        not other_english or len(master_english) >= len(other_english)
    ):
        english = master_english
    else:
        english = other_english
    # If the second track contains CJK it is the translated line, so keep all
    # of its tokens there -- including the Latin fragments -- instead of
    # letting those fragments masquerade as the English clock.
    if any(token.language == "zh" for token in second_tokens):
        chinese = _merge_unique(
            second_tokens,
            [token for token in first_tokens if token.language == "zh"],
        )
    else:
        chinese = [token for token in first_tokens if token.language == "zh"]
    english = _monotonic(english)

    if english:
        events = segment_timeline(english, max_chars=EN_EVENT_CHARS)
        english_events = events
        chinese_events = assign_tokens(events, chinese) if chinese else [[] for _ in events]
    elif chinese:
        events = segment_timeline(chinese, max_chars=ZH_EVENT_CHARS)
        english_events = [[] for _ in events]
        chinese_events = events
    else:
        return []
    return list(zip(english_events, chinese_events))
