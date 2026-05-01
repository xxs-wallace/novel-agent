from __future__ import annotations

import json
import re
from typing import Any


def extract_json_blob(text: str) -> dict[str, Any] | list[Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError('Empty model output')
    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", stripped, flags=re.IGNORECASE)
    candidates = fenced + [stripped]
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        parsed: list[tuple[object, str]] = []
        for snippet in _iter_balanced_json_snippets(candidate):
            try:
                parsed.append((json.loads(snippet), snippet))
            except json.JSONDecodeError:
                continue
        if parsed:
            # Prefer larger top-level objects (dicts) over small inner arrays like content_tags.
            def score(item: tuple[object, str]) -> int:
                obj, snippet = item
                if isinstance(obj, dict):
                    return 1_000_000 + len(snippet) + len(obj) * 10
                if isinstance(obj, list):
                    return len(snippet)
                return 0

            best_obj, _ = max(parsed, key=score)
            if isinstance(best_obj, (dict, list)):
                return best_obj
    raise ValueError('Could not extract JSON from model output')


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _iter_balanced_json_snippets(text: str) -> list[str]:
    snippets: list[str] = []
    for start_index, ch in enumerate(text):
        if ch not in "{[":
            continue
        snippet = _extract_balanced_json_from(text, start_index)
        if snippet:
            snippets.append(snippet)
    return snippets


def _extract_balanced_json_from(text: str, start_index: int) -> str | None:
    stack: list[str] = []
    in_string = False
    escaped = False
    for index in range(start_index, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            stack.append(ch)
            continue
        if ch in "}]":
            if not stack:
                return None
            opening = stack.pop()
            if (opening, ch) not in {("{", "}"), ("[", "]")}:
                return None
            if not stack:
                return text[start_index : index + 1].strip()
    return None
