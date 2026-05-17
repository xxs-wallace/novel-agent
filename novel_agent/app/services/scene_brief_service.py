from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ..llm import JsonModelClient
from ..prompts.scene_brief_prompt import build_scene_brief_prompt
from ..schemas.creative_kb_schema import SceneBrief
from ..schemas.orchestration_schema import CreativeKBRetrievalInput
from .retrieval_context_adapter import build_retrieval_context, prepare_scene_brief_input
from .scene_plan_adapter import (
    adapt_scene_plan_to_scene_brief,
    coerce_scene_plan_subset,
    normalize_scene_brief,
    resolve_scene_brief,
)

SCENE_BRIEF_SCHEMA_RETRY_ATTEMPTS = 3


class SceneBriefService:
    """Builds retrieval-oriented SceneBrief from orchestration input."""

    def __init__(self, *, model_client: JsonModelClient | None = None) -> None:
        self.model_client = model_client

    def build(self, retrieval_input: CreativeKBRetrievalInput, *, scene_brief: SceneBrief | None = None) -> SceneBrief:
        normalized_input = self._normalize_retrieval_input(retrieval_input)

        if not normalized_input.anchor_context.strip():
            raise ValueError("anchor_context is required for SceneBrief generation")
        if not normalized_input.goal.strip() and scene_brief is None:
            raise ValueError("goal is required when scene_brief is not provided")

        if scene_brief is not None:
            return normalize_scene_brief(scene_brief)

        fallback_brief = self._build_fallback_scene_brief(normalized_input)
        if self.model_client is None:
            raise RuntimeError("SceneBriefService requires an available model_client when scene_brief is not provided")
        return self._build_scene_brief_with_prompt(
            retrieval_input=normalized_input,
            fallback_brief=fallback_brief,
        )

    def _build_scene_brief_with_prompt(
        self,
        *,
        retrieval_input: CreativeKBRetrievalInput,
        fallback_brief: SceneBrief,
    ) -> SceneBrief:
        system_prompt, user_prompt = build_scene_brief_prompt(
            retrieval_input=retrieval_input,
            fallback_scene_brief=fallback_brief.to_dict(),
        )
        last_payload: dict[str, Any] | list[Any] | None = None
        last_raw_text = ""
        for attempt in range(1, SCENE_BRIEF_SCHEMA_RETRY_ATTEMPTS + 1):
            payload, raw_text = self.model_client.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                fallback_factory=fallback_brief.to_dict,
                use_fallback_on_error=self.model_client.settings.dry_run,
            )
            last_payload = payload
            last_raw_text = raw_text
            try:
                return self._scene_brief_from_payload(payload)
            except Exception:
                if attempt >= SCENE_BRIEF_SCHEMA_RETRY_ATTEMPTS:
                    preview = last_raw_text or str(last_payload)
                    raise ValueError(
                        "Failed to build SceneBrief from model output after "
                        f"{SCENE_BRIEF_SCHEMA_RETRY_ATTEMPTS} attempts. Raw output preview:\n{preview[:800]}"
                    )
        raise RuntimeError("SceneBrief generation exhausted retry attempts")

    def _scene_brief_from_payload(self, payload: dict[str, Any] | list[Any]) -> SceneBrief:
        if not isinstance(payload, dict):
            raise ValueError("SceneBrief payload must be a JSON object")
        return normalize_scene_brief(
            SceneBrief(
                scene_objective=self._normalize_text(payload.get("scene_objective")),
                emotional_goal=self._normalize_text(payload.get("emotional_goal")),
                conflict_goal=self._normalize_text(payload.get("conflict_goal")),
                narrative_function=self._require_list(payload.get("narrative_function"), field_name="narrative_function"),
                emotion_mode=self._require_list(payload.get("emotion_mode"), field_name="emotion_mode"),
                character_temperament=self._normalize_string_list(payload.get("character_temperament")),
                relationship_state=self._normalize_string_list(payload.get("relationship_state")),
                style_need=self._normalize_string_list(payload.get("style_need")),
                must_avoid=self._require_list(payload.get("must_avoid"), field_name="must_avoid"),
                preferred_tags=self._normalize_string_list(payload.get("preferred_tags")),
            )
        )

    def _normalize_retrieval_input(self, retrieval_input: CreativeKBRetrievalInput) -> CreativeKBRetrievalInput:
        scene_brief_input = prepare_scene_brief_input(
            anchor_context=retrieval_input.anchor_context,
            recent_window_summary=retrieval_input.recent_window_summary,
            goal=retrieval_input.goal,
            previous_generated_segment=retrieval_input.previous_generated_segment,
            retrieval_context=retrieval_input.retrieval_context,
        )
        return CreativeKBRetrievalInput(
            anchor_context=scene_brief_input.anchor_context,
            recent_window_summary=scene_brief_input.recent_window_summary,
            goal=scene_brief_input.goal,
            documents=[dict(item) for item in retrieval_input.documents],
            previous_generated_segment=scene_brief_input.previous_generated_segment,
            retrieval_context=scene_brief_input.retrieval_context,
            scene_plan=dict(retrieval_input.scene_plan),
        )

    def _build_fallback_scene_brief(self, retrieval_input: CreativeKBRetrievalInput) -> SceneBrief:
        scene_plan_subset = coerce_scene_plan_subset(retrieval_input.scene_plan)
        if not scene_plan_subset.goal:
            scene_plan_subset = replace(scene_plan_subset, goal=retrieval_input.goal.strip())
        return resolve_scene_brief(None, scene_plan_subset)

    def _normalize_text(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _normalize_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if not isinstance(value, list):
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

    def _require_list(self, value: Any, *, field_name: str) -> list[str]:
        normalized = self._normalize_string_list(value)
        if not normalized:
            raise ValueError(f"SceneBrief.{field_name} is required")
        return normalized
