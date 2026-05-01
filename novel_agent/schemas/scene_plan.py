from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ScenePlan:
    goal: str
    anchor_context: str
    must_include: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    outline: list[str] = field(default_factory=list)
    target_word_count: int = 1200
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenePlan":
        goal = str(data.get("goal") or "")
        anchor_context = str(data.get("anchor_context") or "")
        must_include = [str(x).strip() for x in (data.get("must_include") or []) if str(x).strip()]
        forbidden = [str(x).strip() for x in (data.get("forbidden") or []) if str(x).strip()]
        outline = [str(x).strip() for x in (data.get("outline") or []) if str(x).strip()]
        raw_target = data.get("target_word_count")
        try:
            target_word_count = int(raw_target) if raw_target is not None else 1200
        except (TypeError, ValueError):
            target_word_count = 1200
        if target_word_count <= 0:
            target_word_count = 1200
        sources_raw = data.get("sources") or []
        sources: list[dict[str, Any]] = []
        if isinstance(sources_raw, list):
            for s in sources_raw:
                if isinstance(s, dict):
                    sources.append(dict(s))
        return cls(
            goal=goal,
            anchor_context=anchor_context,
            must_include=must_include,
            forbidden=forbidden,
            outline=outline,
            target_word_count=target_word_count,
            sources=sources,
        )
