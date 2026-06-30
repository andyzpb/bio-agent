from __future__ import annotations

import re


_SENTENCE_ABBREVIATIONS = {
    "al",
    "dr",
    "e.g",
    "fig",
    "i.e",
    "mr",
    "mrs",
    "ms",
    "prof",
    "vs",
}


def split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    paren_depth = 0
    bracket_depth = 0
    for index, char in enumerate(text):
        if char == "(":
            paren_depth += 1
            continue
        if char == ")":
            paren_depth = max(0, paren_depth - 1)
            continue
        if char == "[":
            bracket_depth += 1
            continue
        if char == "]":
            bracket_depth = max(0, bracket_depth - 1)
            continue
        if char not in ".!?":
            continue
        if not _is_sentence_boundary(
            text,
            index,
            paren_depth=paren_depth,
            bracket_depth=bracket_depth,
        ):
            continue
        end = index + 1
        citation_start = end
        while citation_start < len(text) and text[citation_start].isspace():
            citation_start += 1
        if citation_start < len(text) and text[citation_start] == "[":
            citation_end = text.find("]", citation_start + 1)
            if citation_end != -1:
                end = citation_end + 1
                if end < len(text) and text[end] in ".!?":
                    end += 1
        while end < len(text) and text[end] in ")]":
            end += 1
        part = text[start:end].strip()
        if part:
            parts.append(part)
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _is_sentence_boundary(
    text: str,
    index: int,
    *,
    paren_depth: int,
    bracket_depth: int,
) -> bool:
    char = text[index]
    previous = text[index - 1] if index > 0 else ""
    next_char = text[index + 1] if index + 1 < len(text) else ""
    if paren_depth or bracket_depth:
        return False
    if char == "." and previous.isdigit() and next_char.isdigit():
        return False
    token_match = re.search(r"([A-Za-z](?:[A-Za-z.]*)?)$", text[:index])
    token = token_match.group(1).lower().rstrip(".") if token_match else ""
    if char == "." and token in _SENTENCE_ABBREVIATIONS:
        return False
    lookahead = index + 1
    while lookahead < len(text) and text[lookahead] in ")]":
        lookahead += 1
    while lookahead < len(text) and text[lookahead].isspace():
        lookahead += 1
    if lookahead >= len(text):
        return True
    return text[lookahead] == "[" or text[lookahead].isupper() or text[lookahead].isdigit()
