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
* bilingual ASS events pair complete, punctuation-terminated sentences and
  never render a cue with only one language;
* captions are segmented into disjoint display events, so a word is rendered
  exactly once.

Nothing here guesses at meaning: tokens are selected by time, and words are
never dropped silently.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
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
# One display line per language: 60 English characters, 28 Chinese characters.
EN_EVENT_CHARS = 60
ZH_EVENT_CHARS = 28
# YouTube marks a change of speaker with ">>" inside the caption text. It is a
# navigation aid in the transcript, not spoken content, and looked like noise
# on the burned frame.
SPEAKER_MARKER = re.compile(r"(?:^|\s)>{2,3}\s*")
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
    text = SPEAKER_MARKER.sub(" ", text)
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
    timings: Sequence[dict | None],
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
    timings = [timing for timing in timings if timing is not None]
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
        next_start = normalized[index + 1].start
        # Every token, spread or exact, stops when the next word starts. A
        # value interpolated across a cue ("1,000%") otherwise kept the whole
        # cue span and overlapped the following sentences, which surfaced as
        # two subtitles on screen at once.
        if token.end > next_start > token.start:
            normalized[index] = Token(
                token.text,
                token.start,
                next_start,
                token.language,
                token.exact,
                token.group,
            )
    return [token for token in normalized if token.end > token.start]


def _char_count(tokens: Iterable[Token]) -> int:
    total = 0.0
    for token in tokens:
        if token.language == "zh":
            # Count the visible Chinese line exactly: layout wraps at 28
            # characters, punctuation included, so the segmenter must too.
            total += len(token.text)
            continue
        if is_punctuation(token.text):
            continue
        # Count real characters (plus the joining space): the layout wraps
        # at 60 characters per line, so an event must stay at or below 60,
        # not 60 em units, or the renderer receives an unexpected line
        # break.
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
    # Re-inflating a token to its source end can cross the next word's start,
    # which produced two overlapping subtitles. The next word always wins.
    for index in range(len(result) - 1):
        current = result[index]
        next_start = result[index + 1].start
        if current.end > next_start > current.start:
            result[index] = Token(
                current.text,
                current.start,
                next_start,
                current.language,
                current.exact,
                current.group,
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


def _language_timelines(
    cues: Sequence[dict],
    other_cues: Sequence[dict] | None,
) -> tuple[list[Token], list[Token], Sequence[dict], Sequence[dict]]:
    first_tokens = build_timeline(cues)
    second_tokens = build_timeline(other_cues or [])
    master_english = [token for token in first_tokens if token.language == "en"]
    other_english = [token for token in second_tokens if token.language == "en"]
    use_master_english = master_english and (
        not other_english or len(master_english) >= len(other_english)
    )
    if use_master_english:
        english = master_english
        english_cues = cues
    else:
        english = other_english
        english_cues = other_cues or cues

    if any(token.language == "zh" for token in second_tokens):
        chinese = _merge_unique(
            second_tokens,
            [token for token in first_tokens if token.language == "zh"],
        )
        chinese_cues = other_cues or cues
    else:
        chinese = [token for token in first_tokens if token.language == "zh"]
        chinese_cues = cues
    return _monotonic(english), chinese, english_cues, chinese_cues


def _sentence_groups(tokens: Sequence[Token]) -> list[list[Token]]:
    groups: list[list[Token]] = []
    current: list[Token] = []
    for token in tokens:
        current.append(token)
        if _sentence_end(token.text):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _pair_sentence_groups(
    english_groups: Sequence[list[Token]],
    chinese_groups: Sequence[list[Token]],
    *,
    max_chars: int = EN_EVENT_CHARS,
) -> list[tuple[list[Token], list[Token]]]:
    """Globally pair sentence groups, merging adjacent groups as needed."""
    english_count = len(english_groups)
    chinese_count = len(chinese_groups)
    transitions = ((1, 1, 0.0), (1, 2, 1.3), (2, 1, 1.3))
    costs = [
        [math.inf] * (chinese_count + 1)
        for _ in range(english_count + 1)
    ]
    previous: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    costs[0][0] = 0.0

    for english_index in range(english_count + 1):
        for chinese_index in range(chinese_count + 1):
            current_cost = costs[english_index][chinese_index]
            if not math.isfinite(current_cost):
                continue
            for english_size, chinese_size, merge_penalty in transitions:
                next_english = english_index + english_size
                next_chinese = chinese_index + chinese_size
                if (
                    next_english > english_count
                    or next_chinese > chinese_count
                ):
                    continue
                english_part = english_groups[english_index:next_english]
                chinese_part = chinese_groups[chinese_index:next_chinese]
                start_delta = abs(
                    english_part[0][0].start - chinese_part[0][0].start
                )
                end_delta = abs(
                    english_part[-1][-1].end - chinese_part[-1][-1].end
                )
                english_text = " ".join(
                    token.text for group in english_part for token in group
                )
                chinese_text = "".join(
                    token.text for group in chinese_part for token in group
                )
                overflow = (
                    max(0, len(english_text) - max_chars) / max_chars
                    + max(0, len(chinese_text) - ZH_EVENT_CHARS)
                    / ZH_EVENT_CHARS
                )
                candidate_cost = (
                    current_cost
                    + end_delta
                    + 0.25 * start_delta
                    + merge_penalty
                    + 0.1 * overflow
                )
                if candidate_cost < costs[next_english][next_chinese]:
                    costs[next_english][next_chinese] = candidate_cost
                    previous[next_english, next_chinese] = (
                        english_index,
                        chinese_index,
                        english_size,
                        chinese_size,
                    )

    if not math.isfinite(costs[english_count][chinese_count]):
        # The transition set can only consume balanced tracks (one English
        # group per one or two Chinese groups). A translation track without
        # sentence punctuation collapses into one group, so fall back to the
        # monotonic pairing that attaches the unpaired tail to the last event.
        return _pair_sentence_groups_greedy(
            english_groups, chinese_groups, max_chars=max_chars
        )

    pairs: list[tuple[list[Token], list[Token]]] = []
    english_index = english_count
    chinese_index = chinese_count
    while english_index or chinese_index:
        step = previous.get((english_index, chinese_index))
        if step is None:
            raise ValueError(
                "Could not align complete English and Chinese sentence timelines."
            )
        previous_english, previous_chinese, english_size, chinese_size = step
        english = [
            token
            for group in english_groups[previous_english:english_index]
            for token in group
        ]
        chinese = [
            token
            for group in chinese_groups[previous_chinese:chinese_index]
            for token in group
        ]
        pairs.append((english, chinese))
        english_index = previous_english
        chinese_index = previous_chinese
    pairs.reverse()
    return pairs


def _pair_sentence_groups_greedy(
    english_groups: Sequence[list[Token]],
    chinese_groups: Sequence[list[Token]],
    *,
    max_chars: int = EN_EVENT_CHARS,
) -> list[tuple[list[Token], list[Token]]]:
    """Monotonically pair sentence groups, merging adjacent groups as needed.

    Used when the tracks are too unbalanced for the global dynamic program
    (for example a Chinese translation with no sentence punctuation at all).
    The unpaired tail is attached to the last event, so no spoken word is lost.
    """
    pairs: list[tuple[list[Token], list[Token]]] = []
    english_index = 0
    chinese_index = 0
    transitions = ((1, 1, 0.0), (1, 2, 1.3), (2, 1, 1.3))

    while english_index < len(english_groups) and chinese_index < len(chinese_groups):
        candidates: list[tuple[float, int, int]] = []
        for english_size, chinese_size, merge_penalty in transitions:
            if (
                english_index + english_size > len(english_groups)
                or chinese_index + chinese_size > len(chinese_groups)
            ):
                continue
            english_part = english_groups[
                english_index : english_index + english_size
            ]
            chinese_part = chinese_groups[
                chinese_index : chinese_index + chinese_size
            ]
            start_delta = abs(
                english_part[0][0].start - chinese_part[0][0].start
            )
            end_delta = abs(
                english_part[-1][-1].end - chinese_part[-1][-1].end
            )
            english_text = " ".join(
                token.text for group in english_part for token in group
            )
            chinese_text = "".join(
                token.text for group in chinese_part for token in group
            )
            overflow = (
                max(0, len(english_text) - max_chars) / max_chars
                + max(0, len(chinese_text) - ZH_EVENT_CHARS) / ZH_EVENT_CHARS
            )
            candidates.append(
                (
                    end_delta
                    + 0.25 * start_delta
                    + merge_penalty
                    + 0.1 * overflow,
                    english_size,
                    chinese_size,
                )
            )
        _, english_size, chinese_size = min(candidates)
        pairs.append(
            (
                [
                    token
                    for group in english_groups[
                        english_index : english_index + english_size
                    ]
                    for token in group
                ],
                [
                    token
                    for group in chinese_groups[
                        chinese_index : chinese_index + chinese_size
                    ]
                    for token in group
                ],
            )
        )
        english_index += english_size
        chinese_index += chinese_size

    if pairs:
        if english_index < len(english_groups):
            pairs[-1][0].extend(
                token
                for group in english_groups[english_index:]
                for token in group
            )
        if chinese_index < len(chinese_groups):
            pairs[-1][1].extend(
                token
                for group in chinese_groups[chinese_index:]
                for token in group
            )
    return pairs


def build_bilingual_sentence_events(
    cues: Sequence[dict],
    *,
    other_cues: Sequence[dict] | None = None,
    max_chars: int = EN_EVENT_CHARS,
) -> list[tuple[list[Token], list[Token]]]:
    """Pair complete English and Chinese sentence groups for ASS rendering."""
    english, chinese, _, _ = _language_timelines(cues, other_cues)
    if not english or not chinese:
        raise ValueError(
            "Bilingual ASS generation requires timed English and Chinese captions."
        )
    return _pair_sentence_groups(
        _sentence_groups(english),
        _sentence_groups(chinese),
        max_chars=max_chars,
    )


def build_cue_aligned_events(
    english_cues: Sequence[dict],
    chinese_cues: Sequence[dict],
) -> list[tuple[list[Token], list[Token]]]:
    """Keep each pre-aligned bilingual SRT cue as one display event."""
    if not english_cues or len(english_cues) != len(chinese_cues):
        raise ValueError("Cue-aligned ASS requires equal, non-empty language tracks.")

    events: list[tuple[list[Token], list[Token]]] = []
    previous_end = -math.inf
    for index, (english_cue, chinese_cue) in enumerate(
        zip(english_cues, chinese_cues)
    ):
        english_start = float(english_cue["start"])
        english_end = float(english_cue["end"])
        chinese_start = float(chinese_cue["start"])
        chinese_end = float(chinese_cue["end"])
        if (
            abs(english_start - chinese_start) > 0.001
            or abs(english_end - chinese_end) > 0.001
            or english_start < previous_end
        ):
            raise ValueError(
                f"Cue-aligned English/Chinese timestamps differ at cue {index + 1}."
            )

        english_tokens = tokenize_cue(english_cue, group=index)
        chinese_tokens = tokenize_cue(chinese_cue, group=index)
        if not english_tokens or not chinese_tokens:
            raise ValueError(f"Cue {index + 1} must contain both languages.")
        events.append(
            (
                [replace(token, language="en") for token in english_tokens],
                [replace(token, language="zh") for token in chinese_tokens],
            )
        )
        previous_end = english_end
    return events


def _cue_starts(cues: Sequence[dict]) -> list[float]:
    """Distinct caption start times, rounded to the millisecond."""
    starts: set[float] = set()
    for cue in cues:
        if not _clean(str(cue.get("text", ""))):
            continue
        try:
            start = float(cue.get("start", 0.0))
        except (TypeError, ValueError):
            continue
        if math.isfinite(start):
            starts.add(round(max(0.0, start), 3))
    return sorted(starts)


def _cue_windows(starts: Sequence[float]) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    for index, start in enumerate(starts):
        low = -math.inf if index == 0 else start
        high = starts[index + 1] if index + 1 < len(starts) else math.inf
        if high > low:
            windows.append((low, high))
    return windows


def _midpoint(token: Token) -> float:
    return (token.start + token.end) / 2


def _english_text(tokens: Sequence[Token]) -> str:
    return re.sub(r"\s+", " ", " ".join(token.text for token in tokens)).strip()


def _chinese_text(tokens: Sequence[Token]) -> str:
    return re.sub(r"\s+", " ", "".join(token.text for token in tokens)).strip()


def _coalesce_one_sided(
    units: Sequence[tuple[list[Token], list[Token]]],
) -> list[tuple[list[Token], list[Token]]]:
    """Attach a unit that only got one language to its neighbour.

    A translation cue can start a few milliseconds before the first English
    word and produce a Chinese-only sliver. Pairing it with the next unit keeps
    both languages on screen together; if no neighbour carries the missing
    language the caller rejects the cue-aligned path.
    """
    merged: list[tuple[list[Token], list[Token]]] = []
    for english, chinese in units:
        if merged and (not english or not chinese):
            previous_english, previous_chinese = merged[-1]
            merged[-1] = (
                [*previous_english, *english],
                [*previous_chinese, *chinese],
            )
        else:
            merged.append((english, chinese))
    if len(merged) > 1 and (not merged[-1][0] or not merged[-1][1]):
        last_english, last_chinese = merged.pop()
        previous_english, previous_chinese = merged[-1]
        merged[-1] = (
            [*previous_english, *last_english],
            [*previous_chinese, *last_chinese],
        )
    return merged


def _can_merge_units(
    left: tuple[list[Token], list[Token]],
    right: tuple[list[Token], list[Token]],
    *,
    max_chars: int = EN_EVENT_CHARS,
) -> bool:
    left_english, left_chinese = left
    right_english, right_chinese = right
    if len(_english_text([*left_english, *right_english])) > max_chars:
        return False
    if len(_chinese_text([*left_chinese, *right_chinese])) > ZH_EVENT_CHARS:
        return False
    start = min(left_english[0].start, left_chinese[0].start)
    end = max(
        max(token.end for token in left_english),
        max(token.end for token in left_chinese),
    )
    next_start = min(right_english[0].start, right_chinese[0].start)
    next_end = max(
        max(token.end for token in right_english),
        max(token.end for token in right_chinese),
    )
    if next_end - start > MAX_EVENT_SECONDS:
        return False
    # Only join cues that touch. A deliberate pause is a caption boundary and
    # must survive as a gap, even when the combined text would still fit.
    return next_start - end <= 0.001


def _merge_units(
    units: Sequence[tuple[list[Token], list[Token]]],
    *,
    max_chars: int = EN_EVENT_CHARS,
) -> list[tuple[list[Token], list[Token]]]:
    """Greedily join touching translation cues while both lines still fit."""
    merged: list[tuple[list[Token], list[Token]]] = []
    for english, chinese in units:
        if merged and _can_merge_units(merged[-1], (english, chinese), max_chars=max_chars):
            previous_english, previous_chinese = merged[-1]
            merged[-1] = (
                [*previous_english, *english],
                [*previous_chinese, *chinese],
            )
        else:
            merged.append((english, chinese))
    return merged


def _cue_aligned_events(
    english: Sequence[Token],
    chinese: Sequence[Token],
    *,
    chinese_cues: Sequence[dict],
    english_cue_count: int,
    max_chars: int = EN_EVENT_CHARS,
) -> list[tuple[list[Token], list[Token]]] | None:
    """Pair each translated cue with the English words it translates.

    YouTube's translated cue i covers exactly the words of English cue i, but
    the English cue itself can span several translation cues. Using the
    translation starts as display boundaries gives one coherent unit per
    translated phrase instead of assigning whole Chinese groups to long English
    segments (which produced English-only and four-line events).

    Returns ``None`` when this alignment cannot produce a clean one-line
    bilingual event for every unit; the caller then keeps the legacy segmenter.
    """
    starts = _cue_starts(chinese_cues)
    if len(starts) < 2:
        return None
    # A two-cue translation paired with a three-hour English track is not a
    # real parallel transcript; using its starts would make hour-long events.
    if english_cue_count and len(starts) * 2 < english_cue_count:
        return None
    # Overlapping translation cues are rolling windows, not one cue per
    # spoken phrase. Splitting them by start time would cut a cue's own text
    # in half, so those tracks keep the legacy rolling-caption segmenter.
    intervals = sorted(
        (
            (float(cue.get("start", 0.0)), float(cue.get("end", 0.0)))
            for cue in chinese_cues
            if _clean(str(cue.get("text", "")))
        ),
        key=lambda interval: interval[0],
    )
    for (_, end), (next_start, _) in zip(intervals, intervals[1:]):
        if end > next_start + 0.001:
            return None

    units: list[tuple[list[Token], list[Token]]] = []
    for low, high in _cue_windows(starts):
        english_window = [
            token for token in english if low - 1e-9 <= _midpoint(token) < high - 1e-9
        ]
        chinese_window = [
            token for token in chinese if low - 1e-9 <= _midpoint(token) < high - 1e-9
        ]
        if english_window or chinese_window:
            units.append((english_window, chinese_window))
    if not units:
        return None

    units = _coalesce_one_sided(units)
    if any(not unit_english or not unit_chinese for unit_english, unit_chinese in units):
        return None
    # Every translation unit must fit one line in both languages. If one does
    # not, fall back rather than silently splitting the phrase or wrapping.
    for unit_english, unit_chinese in units:
        if len(_english_text(unit_english)) > max_chars:
            return None
        if len(_chinese_text(unit_chinese)) > ZH_EVENT_CHARS:
            return None
    return _merge_units(units, max_chars=max_chars)


def build_display_events(
    cues: Sequence[dict],
    *,
    other_cues: Sequence[dict] | None = None,
    max_chars: int = EN_EVENT_CHARS,
) -> list[tuple[list[Token], list[Token]]]:
    """Return ``(english_tokens, chinese_tokens)`` for each display event.

    ``cues`` is the master track (normally English, because it carries word
    timings); ``other_cues`` is the second language. Both are classified by
    script, so a mixed cue still lands on the right line.
    """
    if not cues and not other_cues:
        return []

    english, chinese, english_cues, chinese_cues = _language_timelines(
        cues, other_cues
    )
    if not english and not chinese:
        return []

    if english and chinese:
        aligned = _cue_aligned_events(
            english,
            chinese,
            chinese_cues=chinese_cues,
            english_cue_count=len(_cue_starts(english_cues)),
            max_chars=max_chars,
        )
        if aligned is not None:
            return aligned

    if english:
        events = segment_timeline(english, max_chars=max_chars)
        english_events = events
        chinese_events = assign_tokens(events, chinese) if chinese else [[] for _ in events]
    elif chinese:
        events = segment_timeline(chinese, max_chars=ZH_EVENT_CHARS)
        english_events = [[] for _ in events]
        chinese_events = events
    else:
        return []
    return list(zip(english_events, chinese_events))
