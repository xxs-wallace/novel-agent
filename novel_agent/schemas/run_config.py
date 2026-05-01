from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RunConfig:
    prompt: str | None
    model_type: str
    model_id: str
    provider: str | None
    api_base: str | None
    api_key: str | None
    thinking: str | None
    reasoning_effort: str | None
    save_reasoning: bool
    action_type: str
    tools: list[str]
    imports: list[str]
    verbosity_level: int
    dry_run: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
