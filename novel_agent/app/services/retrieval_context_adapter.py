from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..schemas.orchestration_schema import RetrievalContext, SceneBriefInput


def build_retrieval_context(
    character_hits: RetrievalContext | Mapping[str, Any] | Sequence[object] | None = None,
    timeline_hits: Sequence[object] | None = None,
    lore_hits: Sequence[object] | None = None,
) -> RetrievalContext:
    """Standardize basic retrieval outputs into RetrievalContext."""
    if isinstance(character_hits, RetrievalContext):
        return RetrievalContext(
            character_hits=_normalize_string_list(character_hits.character_hits),
            timeline_hits=_normalize_string_list(character_hits.timeline_hits),
            lore_hits=_normalize_string_list(character_hits.lore_hits),
        )

    if isinstance(character_hits, Mapping):
        return RetrievalContext(
            character_hits=_normalize_string_list(character_hits.get("character_hits")),
            timeline_hits=_normalize_string_list(character_hits.get("timeline_hits")),
            lore_hits=_normalize_string_list(character_hits.get("lore_hits")),
        )

    return RetrievalContext(
        character_hits=_normalize_string_list(character_hits),
        timeline_hits=_normalize_string_list(timeline_hits),
        lore_hits=_normalize_string_list(lore_hits),
    )


def prepare_scene_brief_input(
    *,
    anchor_context: str,
    recent_window_summary: str,
    goal: str,
    previous_generated_segment: str | None = None,
    retrieval_context: RetrievalContext | Mapping[str, Any] | None = None,
) -> SceneBriefInput:
    return SceneBriefInput(
        anchor_context=anchor_context,
        recent_window_summary=recent_window_summary,
        goal=goal,
        previous_generated_segment=previous_generated_segment,
        retrieval_context=build_retrieval_context(retrieval_context),
    )


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, Sequence):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
