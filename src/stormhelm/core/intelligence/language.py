from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Iterable


_WORD_REPLACEMENTS = {
    "tmrw": "tomorrow",
    "tmr": "tomorrow",
    "rn": "right now",
    "bat": "battery",
    "batt": "battery",
    "wifi": "wi-fi",
    "pkg": "packaging",
    "proj": "project",
    "mc": "minecraft",
}

_WORD_CORRECTIONS = {
    "packging": "packaging",
    "packagin": "packaging",
    "stormhlem": "stormhelm",
    "stomhelm": "stormhelm",
    "wether": "weather",
    "weahter": "weather",
    "locaiton": "location",
    "wrokspace": "workspace",
    "workpsace": "workspace",
    "mincraft": "minecraft",
}

_FUZZY_VOCABULARY = {
    "assistant",
    "battery",
    "browser",
    "controls",
    "current",
    "deck",
    "docs",
    "downloads",
    "externally",
    "files",
    "forecast",
    "home",
    "location",
    "minecraft",
    "packaging",
    "pdf",
    "project",
    "right",
    "stormhelm",
    "systems",
    "tasks",
    "tomorrow",
    "weather",
    "weekend",
    "workspace",
}

_LOOKUP_STRIP_PATTERNS = (
    r"\b(?:open|show|pull up|bring back|restore|continue|set up|setup|assemble|gather|resume)\b",
    r"\b(?:a|an|my|the|this|that|again|please|from last week|from before|from yesterday|from earlier)\b",
    r"\b(?:workspace|workspaces|project|setup|environment|stuff|thing|bearings)\b",
)


def normalize_phrase(text: str) -> str:
    phrase = " ".join(str(text or "").strip().lower().split())
    if not phrase:
        return ""
    parts = re.findall(r"[a-z0-9%]+|[^a-z0-9%]+", phrase)
    normalized: list[str] = []
    for part in parts:
        if not re.fullmatch(r"[a-z0-9%]+", part):
            normalized.append(part)
            continue
        normalized.append(_normalize_token(part))
    return " ".join("".join(normalized).split())


def normalize_lookup_phrase(text: str) -> str:
    phrase = normalize_phrase(text)
    if not phrase:
        return ""
    for pattern in _LOOKUP_STRIP_PATTERNS:
        phrase = re.sub(pattern, " ", phrase)
    phrase = re.sub(r"^\s*(?:for|to|of)\b", " ", phrase)
    phrase = re.sub(r"\b(?:in|for|to|of)\b$", "", phrase)
    return " ".join(phrase.split()).strip(" ,.;:!?")


def fuzzy_ratio(left: str, right: str) -> float:
    normalized_left = normalize_lookup_phrase(left) or normalize_phrase(left)
    normalized_right = normalize_lookup_phrase(right) or normalize_phrase(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def token_overlap(left: str, right: str) -> float:
    left_tokens = set(_meaningful_tokens(normalize_lookup_phrase(left) or normalize_phrase(left)))
    right_tokens = set(_meaningful_tokens(normalize_lookup_phrase(right) or normalize_phrase(right)))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    return overlap / float(max(len(left_tokens), len(right_tokens)))


def best_fuzzy_candidate(query: str, candidates: Iterable[str], *, threshold: float = 0.86) -> str | None:
    normalized_query = " ".join(str(query or "").strip().lower().split())
    best_value = None
    best_ratio = 0.0
    for candidate in candidates:
        normalized_candidate = " ".join(str(candidate or "").strip().lower().split())
        ratio = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_value = candidate
    if best_value is None or best_ratio < threshold:
        return None
    return best_value


def _normalize_token(token: str) -> str:
    if token in _WORD_REPLACEMENTS:
        return _WORD_REPLACEMENTS[token]
    if token in _WORD_CORRECTIONS:
        return _WORD_CORRECTIONS[token]
    if len(token) >= 5:
        corrected = best_fuzzy_candidate(token, _FUZZY_VOCABULARY, threshold=0.9)
        if corrected:
            return corrected
    return token


def _meaningful_tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text) if len(token) > 1]
