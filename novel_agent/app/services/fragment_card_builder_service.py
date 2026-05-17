from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal, Sequence, cast

from ..content_tags import ALLOWED_CONTENT_TAGS
from ..llm import JsonModelClient
from ..prompts.fragment_card_prompt import build_fragment_card_prompt
from ..repos.documents_repo import DocumentRow
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..schemas.creative_kb_schema import FragmentCard, FragmentCardBuildResult, StyleFeatures

FRAGMENT_CARD_SCHEMA_RETRY_ATTEMPTS = 3
SOURCE_EXCERPT_MAX_CHARS = 400
MAX_PREFERRED_TAGS = 4


class FragmentCardValidationError(ValueError):
    pass


class FragmentCardBuildError(RuntimeError):
    pass


@dataclass(slots=True)
class FragmentCardBuildStats:
    attempted_documents: int = 0
    built_cards: int = 0
    validation_retries: int = 0


class FragmentCardBuilderService:
    def __init__(
        self,
        *,
        model_client: JsonModelClient,
        fragment_cards_repo: FragmentCardsRepo,
    ) -> None:
        self.model_client = model_client
        self.fragment_cards_repo = fragment_cards_repo

    def build_card(self, document: DocumentRow) -> FragmentCard:
        result = self.build_card_result(document)
        if result.fragment_card is None:
            raise FragmentCardBuildError(
                f"Failed to build fragment card for doc_id={document.doc_id}: {result.failure_reason or 'unknown error'}"
            )
        return result.fragment_card

    def build_cards(self, documents: Sequence[DocumentRow]) -> tuple[list[FragmentCard], FragmentCardBuildStats]:
        results, stats = self.build_card_results(documents)
        failed_doc_ids = [str(document.doc_id) for document, result in zip(documents, results) if result.status == "failed"]
        if failed_doc_ids:
            raise FragmentCardBuildError(
                "Failed to build fragment cards for doc_ids: " + ", ".join(failed_doc_ids)
            )
        cards = [result.fragment_card for result in results if result.fragment_card is not None]
        return cards, stats

    def build_card_result(self, document: DocumentRow) -> FragmentCardBuildResult:
        return self._build_card_result_with_retries(document)

    def build_card_results(
        self,
        documents: Sequence[DocumentRow],
    ) -> tuple[list[FragmentCardBuildResult], FragmentCardBuildStats]:
        results: list[FragmentCardBuildResult] = []
        stats = FragmentCardBuildStats(attempted_documents=len(documents))
        for document in documents:
            result = self.build_card_result(document)
            results.append(result)
            if result.fragment_card is not None:
                stats.built_cards += 1
            stats.validation_retries += result.retry_count
        return results, stats

    def build_and_persist(
        self,
        conn: sqlite3.Connection,
        *,
        documents: Sequence[DocumentRow],
    ) -> tuple[list[FragmentCardBuildResult], FragmentCardBuildStats]:
        results, stats = self.build_card_results(documents)
        cards = [result.fragment_card for result in results if result.fragment_card is not None]
        self.fragment_cards_repo.upsert_cards(conn, cards)
        return results, stats

    def _build_card_result_with_retries(self, document: DocumentRow) -> FragmentCardBuildResult:
        system_prompt, user_prompt = build_fragment_card_prompt(document)
        last_error: Exception | None = None
        last_failure_stage = ""
        last_payload: dict[str, Any] | list[Any] | None = None
        last_raw_text = ""
        for attempt in range(1, FRAGMENT_CARD_SCHEMA_RETRY_ATTEMPTS + 1):
            try:
                payload, raw_text = self.model_client.generate_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    fallback_factory=lambda document=document: self._fallback_payload(document),
                    use_fallback_on_error=self.model_client.settings.dry_run,
                )
                last_payload = payload
                last_raw_text = raw_text
                card = self._payload_to_card(document=document, payload=payload)
                return FragmentCardBuildResult(
                    status="success",
                    fragment_card=card,
                    retry_count=max(0, attempt - 1),
                )
            except Exception as exc:
                last_error = exc
                last_failure_stage = self._infer_failure_stage(exc)

        failure_reason = self._summarize_failure(last_error, last_payload=last_payload, last_raw_text=last_raw_text)
        return FragmentCardBuildResult(
            status="failed",
            retry_count=max(0, FRAGMENT_CARD_SCHEMA_RETRY_ATTEMPTS - 1),
            used_fallback=False,
            failure_stage=cast(Any, last_failure_stage or "schema_validate"),
            failure_reason=failure_reason,
            warnings=[f"fragment_card build failed for doc_id={document.doc_id}"],
        )

    def _payload_to_card(self, *, document: DocumentRow, payload: dict[str, Any] | list[Any]) -> FragmentCard:
        if not isinstance(payload, dict):
            raise FragmentCardValidationError("fragment_card payload must be a JSON object")
        style_features_payload = payload.get("style_features")
        if not isinstance(style_features_payload, dict):
            raise FragmentCardValidationError("style_features must be a JSON object")
        model_preferred_tags = self._validate_allowed_tags(payload.get("preferred_tags"), field_name="preferred_tags")
        final_preferred_tags = self._sync_preferred_tags(
            document_tags=self._validate_allowed_tags(document.content_tags, field_name="document.content_tags"),
            model_tags=model_preferred_tags,
        )
        card = FragmentCard(
            fragment_id=self._build_fragment_id(document),
            doc_id=str(document.doc_id),
            document_title=document.document_title,
            document_title_index=str(document.document_title_index),
            source_path=document.source_path or document.path,
            source_offsets=(document.source_start_offset, document.source_end_offset),
            source_excerpt=self._build_source_excerpt(document.content),
            content_summary=self._require_text(payload, "content_summary"),
            narrative_function=self._string_list(payload.get("narrative_function"), field_name="narrative_function"),
            narrative_function_text=self._require_text(payload, "narrative_function_text"),
            scene_space_tags=self._string_list(payload.get("scene_space_tags"), field_name="scene_space_tags"),
            event_tags=self._string_list(payload.get("event_tags"), field_name="event_tags"),
            emotion_tags=self._string_list(payload.get("emotion_tags"), field_name="emotion_tags"),
            emotion_mechanism_text=self._require_text(payload, "emotion_mechanism_text"),
            expression_mode_tags=self._string_list(
                payload.get("expression_mode_tags"),
                field_name="expression_mode_tags",
            ),
            preferred_tags=final_preferred_tags,
            pov_mode=self._require_text(payload, "pov_mode"),
            character_focus=self._string_list(payload.get("character_focus"), field_name="character_focus"),
            character_temperament=self._string_list(
                payload.get("character_temperament"),
                field_name="character_temperament",
            ),
            character_relation_text=self._require_text(payload, "character_relation_text"),
            relationship_state=self._string_list(payload.get("relationship_state"), field_name="relationship_state"),
            continuity_phase=self._require_text(payload, "continuity_phase"),
            style_features=StyleFeatures(
                sentence_rhythm=self._require_text(style_features_payload, "sentence_rhythm"),
                dialogue_density=self._require_text(style_features_payload, "dialogue_density"),
                interiority_density=self._require_text(style_features_payload, "interiority_density"),
                imagery_density=self._require_text(style_features_payload, "imagery_density"),
            ),
            style_profile_text=self._require_text(payload, "style_profile_text"),
            transferability_score=self._score(payload.get("transferability_score")),
            context_dependency_level=self._dependency_level(payload.get("context_dependency_level")),
        )
        return card

    def _fallback_payload(self, document: DocumentRow) -> dict[str, Any]:
        preferred_tags = self._sync_preferred_tags(
            document_tags=self._validate_allowed_tags(document.content_tags, field_name="document.content_tags"),
            model_tags=[],
        )
        return {
            "content_summary": self._fallback_summary(document),
            "narrative_function": ["收束过渡"] if "告别" in preferred_tags else ["信息揭示"],
            "narrative_function_text": "用简短可检索描述概括该桥段承担的叙事功能。",
            "scene_space_tags": preferred_tags[:2],
            "event_tags": preferred_tags[:2],
            "emotion_tags": preferred_tags[-2:],
            "emotion_mechanism_text": "通过动作、对白和心理停顿呈现当前片段的主要情绪机制。",
            "expression_mode_tags": ["动作描写", "人物对话"] if "人物对话" in preferred_tags else ["动作描写"],
            "preferred_tags": preferred_tags,
            "pov_mode": "近距离第三人称",
            "character_focus": [],
            "character_temperament": [],
            "character_relation_text": "关系描述证据不足时保持空泛但不编造具体设定。",
            "relationship_state": [],
            "continuity_phase": "承接推进",
            "style_features": {
                "sentence_rhythm": "中",
                "dialogue_density": "中",
                "interiority_density": "中",
                "imagery_density": "低",
            },
            "style_profile_text": "保底卡片：使用简短检索句描述节奏、对白与心理密度。",
            "transferability_score": 0.55,
            "context_dependency_level": "medium",
        }

    def _build_fragment_id(self, document: DocumentRow) -> str:
        source_key = (
            f"{document.doc_id}:{document.source_path}:{document.source_start_offset}:{document.source_end_offset}:"
            f"{document.document_title_index}"
        )
        digest = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:12]
        return f"fragment-{document.doc_id}-{digest}"

    def _build_source_excerpt(self, content: str) -> str:
        return content[:SOURCE_EXCERPT_MAX_CHARS].strip()

    def _fallback_summary(self, document: DocumentRow) -> str:
        excerpt = self._build_source_excerpt(document.content)
        if excerpt:
            return excerpt[:120]
        return document.document_title

    def _require_text(self, payload: dict[str, Any], field_name: str) -> str:
        value = payload.get(field_name)
        text = str(value).strip() if value is not None else ""
        if not text:
            raise FragmentCardValidationError(f"{field_name} must be a non-empty string")
        return text

    def _string_list(self, value: Any, *, field_name: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise FragmentCardValidationError(f"{field_name} must be a list")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if not text or text in seen:
                continue
            cleaned.append(text)
            seen.add(text)
        return cleaned

    def _validate_allowed_tags(self, value: Any, *, field_name: str) -> list[str]:
        tags = self._string_list(value, field_name=field_name)
        invalid = [tag for tag in tags if tag not in ALLOWED_CONTENT_TAGS]
        if invalid:
            raise FragmentCardValidationError(
                f"{field_name} contains tags outside the predefined dictionary: {', '.join(invalid)}"
            )
        return tags[:MAX_PREFERRED_TAGS]

    def _sync_preferred_tags(self, *, document_tags: list[str], model_tags: list[str]) -> list[str]:
        if document_tags:
            return document_tags[:MAX_PREFERRED_TAGS]
        return model_tags[:MAX_PREFERRED_TAGS]

    def _score(self, value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError) as exc:
            raise FragmentCardValidationError("transferability_score must be numeric") from exc
        if not 0.0 <= score <= 1.0:
            raise FragmentCardValidationError("transferability_score must be within [0.0, 1.0]")
        return score

    def _dependency_level(self, value: Any) -> Literal["low", "medium", "high"]:
        text = str(value).strip().lower()
        if text not in {"low", "medium", "high"}:
            raise FragmentCardValidationError("context_dependency_level must be low, medium, or high")
        return cast(Literal["low", "medium", "high"], text)

    def _infer_failure_stage(self, exc: Exception) -> str:
        if isinstance(exc, FragmentCardValidationError):
            return "schema_validate"
        message = str(exc).lower()
        if "json" in message:
            return "json_parse"
        if "persist" in message:
            return "persist"
        return "postprocess"

    def _summarize_failure(
        self,
        exc: Exception | None,
        *,
        last_payload: dict[str, Any] | list[Any] | None = None,
        last_raw_text: str = "",
    ) -> str:
        if exc is not None and str(exc).strip():
            return str(exc).strip()
        preview = last_raw_text or str(last_payload or "")
        preview = preview.strip()
        if preview:
            return preview[:200]
        return "unknown error"
