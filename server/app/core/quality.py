import re
from typing import Tuple

MAX_REPLY_CHARS = 12000
_TOKEN_RE = re.compile(r"\S+\s*")
_WORD_RE = re.compile(r"\S+")
_REPEAT_SUBSTRING = re.compile(r"(?:^|(?<=\s))(.{8,80}?)(?:\s*\1){3,}", re.DOTALL)
_OPTION_LIST_RE = re.compile(r"(?m)^\s*(?:\*{0,2}\d+[\.\)]\s+|[-*]\s+)")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "about", "please", "can", "you", "me", "my", "your", "this", "that",
    "là", "của", "và", "cho", "với", "về", "bạn", "mình", "được", "không",
    "nói", "kỹ", "chi", "tiết", "đi", "du", "lịch",
}


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u202f", " ")
        .replace("\xa0", " ")
    )


def strip_consecutive_token_repeats(text: str, max_run: int = 3) -> str:
    tokens = _TOKEN_RE.findall(text or "")
    if not tokens:
        return text or ""
    out = []
    prev = None
    run = 0
    for token in tokens:
        key = token.strip().lower()
        if key and key == prev:
            run += 1
            if run > max_run:
                continue
        else:
            prev = key
            run = 1
        out.append(token)
    return "".join(out)


def collapse_repeated_token_runs(text: str, min_repeats: int = 4) -> str:
    tokens = _TOKEN_RE.findall(text or "")
    words = [token.strip() for token in tokens]
    total = len(words)
    if total < min_repeats * 2:
        return text or ""
    for length in range(1, 9):
        i = 0
        while i + length * min_repeats <= total:
            chunk = [word.lower() for word in words[i : i + length]]
            if length == 1 and len(chunk[0]) < 3:
                i += 1
                continue
            repeats = 1
            cursor = i + length
            while cursor + length <= total and [word.lower() for word in words[cursor : cursor + length]] == chunk:
                repeats += 1
                cursor += length
            if repeats >= (6 if length == 1 else min_repeats):
                kept = tokens[:i] or tokens[: i + length]
                return "".join(kept).rstrip(" ,;:-")
            i += 1
    return text or ""


def looks_like_option_list(text: str) -> bool:
    return len(_OPTION_LIST_RE.findall(text or "")) >= 3


def collapse_repeated_substrings(text: str) -> str:
    if not text:
        return ""
    if looks_like_option_list(text):
        return text
    collapsed = collapse_repeated_token_runs(text)
    match = _REPEAT_SUBSTRING.search(collapsed)
    if not match:
        return collapsed
    prefix = collapsed[: match.start()].rstrip(" ,;:-")
    if prefix:
        return prefix
    return match.group(1).rstrip(" ,;:-")


def has_ngram_loop(text: str, n: int = 4, threshold: int = 8) -> bool:
    tokens = _WORD_RE.findall(text or "")
    if len(tokens) < n * threshold:
        return False
    counts = {}
    for i in range(len(tokens) - n + 1):
        gram = tuple(token.lower() for token in tokens[i : i + n])
        counts[gram] = counts.get(gram, 0) + 1
        if counts[gram] >= threshold:
            return True
    return False


def unique_token_ratio(text: str) -> float:
    tokens = [token.lower() for token in _WORD_RE.findall(text or "")]
    if not tokens:
        return 1.0
    return len(set(tokens)) / len(tokens)


def is_degenerate(text: str) -> bool:
    if not text:
        return False
    if looks_like_option_list(text):
        return False
    tokens = _WORD_RE.findall(text)
    if len(text) > 24000:
        return True
    if len(tokens) >= 40 and unique_token_ratio(text) < 0.18:
        return True
    return has_ngram_loop(text) or bool(_REPEAT_SUBSTRING.search(text))


def sanitize_reply(text: str, max_chars: int = MAX_REPLY_CHARS) -> str:
    cleaned = collapse_repeated_substrings(
        strip_consecutive_token_repeats(_normalize_text(text or ""))
    )
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if len(cleaned) > max_chars:
        trimmed = cleaned[:max_chars]
        if " " in trimmed:
            trimmed = trimmed.rsplit(" ", 1)[0]
        cleaned = trimmed.rstrip() + "…"
    return cleaned.strip()


def sanitize_and_flag(text: str) -> Tuple[str, bool]:
    original = text or ""
    cleaned = sanitize_reply(original)
    collapsed = len(original) > 180 and len(cleaned) < len(original) * 0.55
    return cleaned, collapsed or is_degenerate(original) or is_degenerate(cleaned)


def significant_tokens(text: str) -> set:
    tokens = []
    for token in _WORD_RE.findall(text or ""):
        word = re.sub(r"[^\w]+", "", token, flags=re.UNICODE).lower()
        if len(word) < 3 or word in _STOPWORDS:
            continue
        tokens.append(word)
    return set(tokens)
