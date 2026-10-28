#!/usr/bin/env python3
"""Subtitle line layout: wrap bilingual text before it reaches libass.

The burn repeated the same defect: a caption wider than the frame because the
generator measured the whole cue with optimistic per-character widths and never
inserted line breaks. ``WrapStyle: 2`` told libass not to wrap either, so long
sentences ran off both edges.

Rules implemented here come from Module 2 ergonomics (see
``organization/module-2-ergonomics.md``):

* Simplified Chinese: at most 16 full-width characters per line, 9 CPS.
* English: at most 42 characters per line, 20 CPS.
* At most two lines per language; balanced lines read better than a full line
  followed by an orphan.
* Latin width is measured at 0.56 em per character and CJK at 1.0 em, so the
  font shrinks *before* text can leave the safe area.

The functions are pure and shared by the ASS writer and the QC analyser.
"""

from __future__ import annotations

import math
import re

CJK = re.compile(
    r"[\u2e80-\u2fff\u3000-\u30ff\u3100-\u312f\u3130-\u318f"
    r"\u31a0-\u31bf\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff"
    r"\ua960-\ua97f\uac00-\ud7ff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]"
)

# Conservative advance widths: Arial averages ~0.50 em, punctuation and
# capitals push it higher; libass may pick a wider fallback font.
CJK_EM = 1.0
LATIN_EM = 0.56

ZH_MAX_CHARS = 16
EN_MAX_CHARS = 42
MAX_LINES = 2

# A line may not start with these; they belong to the previous clause.
NO_LINE_START = set("，。、；：！？…）〕〉》」』】’”%,.;:!?)]}")
BREAK_AFTER = set("，。、；：！？…）〕〉》」』】—– \t")
SENTENCE_END = set("。！？!?…")


def is_cjk(char: str) -> bool:
    return bool(CJK.match(char))


def max_chars_for(language: str) -> int:
    code = (language or "en").lower()
    return ZH_MAX_CHARS if code.startswith("zh") else EN_MAX_CHARS


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()


def line_units(text: str) -> float:
    """Width of one line in em units, counting CJK as full-width."""
    return sum(CJK_EM if is_cjk(char) else LATIN_EM for char in text)


def _trim_punctuation_orphans(lines: list[str]) -> list[str]:
    """Move closing punctuation from the start of a line to the previous one."""
    fixed = [lines[0]] if lines else []
    for line in lines[1:]:
        while line and line[0] in NO_LINE_START:
            fixed[-1] += line[0]
            line = line[1:]
        if line:
            fixed.append(line)
    return fixed


def _split_cjk(text: str, limit: int) -> list[str]:
    lines: list[str] = []
    remaining = text
    while len(remaining) > limit:
        target = limit
        # Prefer a clause boundary near the limit so a line does not end
        # mid-phrase; fall back to a hard break for unpunctuated speech.
        for index in range(target, max(0, int(target * 0.55)) - 1, -1):
            if remaining[index - 1] in BREAK_AFTER:
                target = index
                break
        while target < len(remaining) and remaining[target] in NO_LINE_START:
            target += 1
        if target <= 0:
            target = limit
        lines.append(remaining[:target].strip())
        remaining = remaining[target:].strip()
    if remaining:
        lines.append(remaining)
    return lines


def _balance_cjk(text: str, limit: int) -> list[str]:
    """Split a two-line CJK cue near the middle, at a clause if possible."""
    middle = len(text) // 2
    lowest = max(1, len(text) - limit)
    highest = min(limit, len(text) - 1)
    target = middle
    for offset in range(0, max(middle, len(text) - middle) + 1):
        for candidate in (middle - offset, middle + offset):
            if lowest <= candidate <= highest and text[candidate - 1] in BREAK_AFTER:
                target = candidate
                break
        else:
            continue
        break
    if not (lowest <= target <= highest):
        target = min(highest, max(lowest, middle))
    return [text[:target].strip(), text[target:].strip()]


def _split_latin_word(word: str, limit: int) -> list[str]:
    return [word[index : index + limit] for index in range(0, len(word), limit)]


def _split_latin(text: str, limit: int) -> list[str]:
    words: list[str] = []
    for word in text.split():
        if len(word) > limit:
            words.extend(_split_latin_word(word, limit))
        else:
            words.append(word)
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > limit:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _balance_latin(text: str, limit: int) -> list[str]:
    """Prefer two balanced lines over one full line plus a short orphan."""
    if len(text) > limit and len(text.split()) == 1:
        return _split_latin(text, limit)
    words = text.split()
    if len(words) < 2:
        return [text]
    best: tuple[int, int] | None = None
    for index in range(1, len(words)):
        left = " ".join(words[:index])
        right = " ".join(words[index:])
        if len(left) > limit or len(right) > limit:
            continue
        score = abs(len(left) - len(right))
        if best is None or score < best[0]:
            best = (score, index)
    if best is None:
        return _split_latin(text, limit)
    index = best[1]
    return [" ".join(words[:index]), " ".join(words[index:])]


def wrap_caption(
    text: str,
    language: str,
    *,
    max_chars: int | None = None,
    max_lines: int = MAX_LINES,
    hard_limit: bool = False,
) -> list[str]:
    """Wrap one language's caption into display lines.

    Two-line cues are balanced; longer cues keep the requested line length and
    return more than ``max_lines`` so the caller can shrink or flag them rather
    than silently dropping text. With ``hard_limit`` the budget grows instead,
    which is what the timeline segmenter uses to guarantee that a rendered
    block never spills past the safe area.
    """
    value = normalize(text)
    if not value:
        return []
    limit = max_chars or max_chars_for(language)
    chinese = (language or "").lower().startswith("zh")
    if hard_limit and len(value) > limit * max_lines:
        limit = max(limit, math.ceil(len(value) / max_lines))
    if chinese:
        if len(value) <= limit:
            return [value]
        if len(value) <= limit * max_lines:
            return [line for line in _balance_cjk(value, limit) if line]
        return [line for line in _trim_punctuation_orphans(_split_cjk(value, limit)) if line]
    if len(value) <= limit:
        return [value]
    if len(value) <= limit * max_lines:
        return [line for line in _balance_latin(value, limit) if line]
    return [line for line in _split_latin(value, limit) if line]


def fit_font_size(
    lines: list[str],
    base_size: float,
    available_width: float,
    *,
    minimum: float = 28.0,
) -> float:
    """Shrink the font until the widest wrapped line fits the safe area."""
    if not lines or base_size <= 0 or available_width <= 0:
        return float(base_size)
    widest = max(line_units(line) for line in lines)
    if widest <= 0:
        return float(base_size)
    fitted = available_width / widest
    return round(max(minimum, min(base_size, fitted)), 1)
