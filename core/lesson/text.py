"""Language-aware text helpers for lessons (pure functions, no I/O)."""

from __future__ import annotations

import re

# Letters that only occur in Vietnamese (vowels with tone/shape marks + đ).
_VI_CHARS = (
    "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡ"
    "ùúụủũưừứựửữỳýỵỷỹđ"
)
_VI_RE = re.compile(f"[{_VI_CHARS}]", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
BLANK_RE = re.compile(r"_{3,}")


def is_vietnamese(text: str) -> bool:
    """Heuristic: True if *text* contains Vietnamese-specific letters."""
    return bool(_VI_RE.search(text or ""))


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text or "") if s.strip()]


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def _inflections(token: str) -> set[str]:
    """Regular English inflections of a single *token* (lower-case)."""
    t = token.lower()
    forms = {t, t + "s", t + "es", t + "ed", t + "d", t + "ing", t + "er", t + "est"}
    if t.endswith("e"):
        forms |= {t[:-1] + "ing"}
    if t.endswith("y") and len(t) > 2:
        forms |= {t[:-1] + "ies", t[:-1] + "ied"}
    if re.fullmatch(r".*[^aeiou][aeiou][bdgklmnprt]", t):  # stop → stopped
        forms |= {t + t[-1] + "ed", t + t[-1] + "ing"}
    return forms


def term_patterns(term: str, extra_forms: list[str] | None = None) -> list[re.Pattern]:
    """Regex patterns that match *term* (single word or phrase) incl. inflections.

    Only the *last* token of a phrase is inflected (``pick up`` → ``picks up``
    is not covered; add irregular forms via *extra_forms*).
    """
    patterns: list[re.Pattern] = []
    for candidate in [term, *(extra_forms or [])]:
        tokens = candidate.lower().split()
        if not tokens:
            continue
        first = [re.escape(t) for t in tokens[:-1]]
        last_alts = "|".join(sorted((re.escape(f) for f in _inflections(tokens[-1])), key=len, reverse=True))
        body = r"\s+".join([*first, f"(?:{last_alts})"]) if first else f"(?:{last_alts})"
        patterns.append(re.compile(rf"(?<![\w'’]){body}(?![\w'’])", re.IGNORECASE))
        if len(tokens) > 1:  # also inflect the first token of a phrase (pick up → picked up)
            head = "|".join(sorted((re.escape(f) for f in _inflections(tokens[0])), key=len, reverse=True))
            rest = [re.escape(t) for t in tokens[1:]]
            body2 = r"\s+".join([f"(?:{head})", *rest])
            patterns.append(re.compile(rf"(?<![\w'’]){body2}(?![\w'’])", re.IGNORECASE))
    return patterns


def find_term_spans(text: str, term: str, extra_forms: list[str] | None = None) -> list[tuple[int, int]]:
    """Return non-overlapping ``(start, end)`` spans where *term* occurs in *text*."""
    spans: list[tuple[int, int]] = []
    for pat in term_patterns(term, extra_forms):
        spans.extend(m.span() for m in pat.finditer(text or ""))
    return merge_spans(spans)


def merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def contains_term(text: str, term: str, extra_forms: list[str] | None = None) -> bool:
    return bool(find_term_spans(text, term, extra_forms))


def blank_to_speech(text: str) -> str:
    """Replace ``____`` with a spoken placeholder for TTS."""
    return BLANK_RE.sub("blank", text or "")


# ---------------------------------------------------------------------------
# Language segmentation (English ↔ Vietnamese) for TTS voice routing
# ---------------------------------------------------------------------------
# Tokens: words (letters, inner apostrophes), numbers, whitespace, single symbols.
_TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*|\d+(?:[.,]\d+)*|\s+|.", re.UNICODE)
# Symbols that separate "phrases": a run never takes its language across them.
_HARD_BOUNDARIES = set('"“”«»=:;()[]{}—–/|\n')
_SPOKEN_STRIP = re.compile(r'["“”«»=|/()\[\]{}]')
# Vietnamese syllable written without diacritics (e.g. "anh", "em", "nhanh", "trong").
_VI_SYLLABLE = re.compile(
    r"^(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|b|c|d|g|h|k|l|m|n|p|r|s|t|v|x)?"
    r"[aeiouy]{1,3}(?:ng|nh|ch|c|m|n|p|t)?$"
)
# Short English words that also look like Vietnamese syllables.
_EN_FUNCTION_WORDS = {
    "a", "an", "the", "to", "in", "on", "at", "of", "for", "by", "is", "it", "be", "me",
    "he", "she", "we", "you", "my", "so", "no", "do", "go", "up", "say", "can", "may",
    "not", "but", "and", "or", "his", "her", "they", "them", "this", "that", "i",
}


def _looks_vietnamese_ascii(word: str) -> bool:
    w = word.lower()
    return bool(_VI_SYLLABLE.match(w)) and w not in _EN_FUNCTION_WORDS


def split_by_language(text: str, default: str = "en") -> list[tuple[str, str]]:
    """Split *text* into ``[(lang, chunk), …]`` with ``lang`` ∈ {"en", "vi"}.

    Rules (deterministic):

    1. A word containing Vietnamese-only letters is ``vi``.
    2. Other (ASCII) words are resolved per phrase – phrases are delimited by
       quotes, ``=``, ``:``, brackets, dashes:

       * a single word with Vietnamese on *both* sides is a loanword spoken
         in Vietnamese (``đặt taxi ra sân bay``);
       * a run next to Vietnamese whose words all look like Vietnamese
         syllables without diacritics is ``vi`` (``Bao nhiêu``, ``cho sinh viên``);
       * everything else is ``en``.
    3. Numbers take the language of the neighbouring word in the same phrase.
    """
    tokens = _TOKEN_RE.findall(text or "")
    if not tokens:
        return []

    labels: list[str | None] = [None] * len(tokens)
    span = [0] * len(tokens)
    current_span = 0
    for i, tok in enumerate(tokens):
        if tok in _HARD_BOUNDARIES:
            current_span += 1
        span[i] = current_span
        if tok[0].isalpha():
            labels[i] = "vi" if is_vietnamese(tok) else "?"
        elif tok[0].isdigit():
            labels[i] = "#"

    # Resolve unknown words, phrase by phrase.
    for sid in sorted(set(span)):
        words = [i for i in range(len(tokens)) if span[i] == sid and labels[i] in ("vi", "?")]
        k = 0
        while k < len(words):
            if labels[words[k]] != "?":
                k += 1
                continue
            run_end = k
            while run_end + 1 < len(words) and labels[words[run_end + 1]] == "?":
                run_end += 1
            left = labels[words[k - 1]] if k > 0 else None
            right = labels[words[run_end + 1]] if run_end + 1 < len(words) else None
            lo, hi = k, run_end
            # Peel Vietnamese-looking syllables off the edges touching Vietnamese.
            if left == "vi":
                while lo <= hi and _looks_vietnamese_ascii(tokens[words[lo]]):
                    labels[words[lo]] = "vi"
                    lo += 1
            if right == "vi":
                while hi >= lo and _looks_vietnamese_ascii(tokens[words[hi]]):
                    labels[words[hi]] = "vi"
                    hi -= 1
            if lo <= hi:
                inner_left = "vi" if lo > k else left
                inner_right = "vi" if hi < run_end else right
                # A single foreign word inside Vietnamese = loanword / name
                # ("đặt taxi", "Anna nói", "mở minibar.") → Vietnamese voice.
                lang = "vi" if (lo == hi and "vi" in (inner_left, inner_right)) else "en"
                for j in range(lo, hi + 1):
                    labels[words[j]] = lang
            k = run_end + 1

    # Numbers follow a neighbouring word in the same phrase.
    for i, lab in enumerate(labels):
        if lab != "#":
            continue
        prev = next((labels[j] for j in range(i - 1, -1, -1) if span[j] == span[i] and labels[j] in ("en", "vi")), None)
        nxt = next((labels[j] for j in range(i + 1, len(tokens)) if span[j] == span[i] and labels[j] in ("en", "vi")), None)
        labels[i] = prev or nxt or default

    # Group tokens into chunks; symbols/spaces stick to the current chunk.
    chunks: list[list] = []  # [lang, text]
    pending = ""
    for tok, lab in zip(tokens, labels):
        if lab in ("en", "vi"):
            if chunks and chunks[-1][0] == lab:
                chunks[-1][1] += pending + tok
            else:
                chunks.append([lab, pending + tok])
            pending = ""
        elif chunks:
            chunks[-1][1] += tok
        else:
            pending += tok

    result: list[tuple[str, str]] = []
    for lang, chunk in chunks:
        spoken = re.sub(r"\s+", " ", _SPOKEN_STRIP.sub(" ", chunk)).strip(" :;—–-")
        spoken = re.sub(r"\s+([?.!,;])", r"\1", spoken)
        if not re.search(r"\w", spoken):
            continue
        if result and result[-1][0] == lang:
            result[-1] = (lang, f"{result[-1][1]} {spoken}")
        else:
            result.append((lang, spoken))
    return result
