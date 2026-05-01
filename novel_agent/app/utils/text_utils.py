from __future__ import annotations

import re
from pathlib import Path


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def safe_excerpt(text: str, limit: int = 200) -> str:
    compact = normalize_whitespace(text)
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return fallback


def file_stem_title(path: Path) -> str:
    stem = path.stem.replace("-", " ").replace("_", " ").strip()
    return re.sub(r"\s+", " ", stem) or path.name


def clamp_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n"


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?])\s*", text)
    return [part.strip() for part in parts if part.strip()]
