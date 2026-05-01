from __future__ import annotations

import json
import re
from pathlib import Path

from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..repos.db import NovelAgentDB
from ..schemas.context_assembly_schema import (
    ChapterContextItem,
    CharacterProfileContextItem,
    ContextAssemblyPayload,
)
from ..schemas.smoke_schema import AuthorizedInputs, LoadedSmokeSample, LoadedSmokeStep, PrefixRuntimeSnapshot
from .context_selectors import infer_character_names, rank_chapter_rows

SENTENCE_SPLIT_PATTERN = re.compile(r"[。！？!?；;\n]+")


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _normalize_string_list(items: object) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        text = items.strip()
        return [text] if text else []
    if not isinstance(items, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _normalize_object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


class SmokeAuthorizedInputsService:
    def __init__(
        self,
        *,
        chapters_repo: ChaptersRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        assets_repo: AssetsRepo | None = None,
    ) -> None:
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.assets_repo = assets_repo or AssetsRepo()

    def build(
        self,
        *,
        sample: LoadedSmokeSample,
        prefix_snapshot: PrefixRuntimeSnapshot,
        step: LoadedSmokeStep | None = None,
        previous_generated_segment: str | None = None,
    ) -> AuthorizedInputs:
        active_step = step or sample.first_step
        db = NovelAgentDB(prefix_snapshot.db_path_obj)
        with db.connect() as conn:
            chapter_rows = self.chapters_repo.list_by_book(conn, book_id=sample.config.book_id)
            profile_rows = self.character_profiles_repo.list_by_book(conn, book_id=sample.config.book_id)
            assets_row = self.assets_repo.get(conn, book_id=sample.config.book_id)

        world_summary_md = self._read_asset_text(assets_row, field_name="world_summary_path")
        story_outline_md = self._read_asset_text(assets_row, field_name="outline_markdown_path")
        chapter_context = self._build_chapter_context(
            chapter_rows=chapter_rows,
            current_title_index=prefix_snapshot.max_document_title_index,
            window_size=int(
                active_step.metadata.get("window_size")
                or sample.config.metadata.get("window_size")
                or max(1, len(active_step.recent_window) or 3)
            ),
        )
        related_character_names = self._infer_related_character_names(
            sample=sample,
            step=active_step,
            chapter_rows=chapter_rows,
            profile_rows=profile_rows,
            previous_generated_segment=previous_generated_segment,
        )
        character_profiles = self._build_character_context(
            profile_rows=profile_rows,
            related_character_names=related_character_names,
        )
        context_payload = ContextAssemblyPayload(
            chapter_context=chapter_context,
            world_summary_md=world_summary_md,
            character_profiles=character_profiles,
            story_outline_md=(
                story_outline_md if sample.config.mode != "blind_prefix" else ""
            ),
            missing_context=[],
        )

        prefix_facts = {
            "documents_cutoff": prefix_snapshot.max_document_title_index,
            "recent_window_summary": active_step.recent_window_summary,
            "context_payload": context_payload.to_dict(),
            "sources": self._build_prefix_sources(sample=sample, step=active_step, prefix_snapshot=prefix_snapshot),
        }

        if sample.config.mode == "blind_prefix":
            return AuthorizedInputs(
                prefix_facts=prefix_facts,
                current_unit_plan={},
                bounded_future_hint=None,
                scene_plan_seed={},
                scene_brief_seed={},
                related_character_names=related_character_names,
                target_length_chars=self._resolve_target_length_chars(sample=sample, step=active_step),
            )

        current_unit_plan = self._build_current_unit_plan(
            sample=sample,
            step=active_step,
            story_outline_md=story_outline_md,
            related_character_names=related_character_names,
            character_profiles=character_profiles,
        )
        scene_plan_seed = self._build_scene_plan_seed(
            current_unit_plan=current_unit_plan,
            sample=sample,
            step=active_step,
        )
        scene_brief_seed = self._build_scene_brief_seed(
            current_unit_plan=current_unit_plan,
            scene_plan_seed=scene_plan_seed,
            sample=sample,
            step=active_step,
        )
        bounded_future_hint = (
            sample.config.forward_guidance.to_dict()
            if sample.config.mode == "bounded_future_hint" and sample.config.forward_guidance is not None
            else None
        )
        return AuthorizedInputs(
            prefix_facts=prefix_facts,
            current_unit_plan=current_unit_plan,
            bounded_future_hint=bounded_future_hint,
            scene_plan_seed=scene_plan_seed,
            scene_brief_seed=scene_brief_seed,
            related_character_names=related_character_names,
            target_length_chars=self._resolve_target_length_chars(sample=sample, step=active_step),
        )

    def _build_chapter_context(
        self,
        *,
        chapter_rows: list,
        current_title_index: str,
        window_size: int,
    ) -> list[ChapterContextItem]:
        ranked_rows = rank_chapter_rows(
            chapter_rows,
            current_title_index=current_title_index,
        )
        selected_rows = ranked_rows[: max(1, window_size)]
        selected_rows.sort(key=lambda row: int(row["document_title_index"]))
        return [
            ChapterContextItem(
                document_title_index=str(row["document_title_index"]),
                chapter_title=str(row["chapter_title"]),
                summary_md=str(row["summary_md"] or ""),
                importance_score=int(row["importance_score"] or 0),
            )
            for row in selected_rows
            if str(row["summary_md"] or "").strip()
        ]

    def _build_character_context(
        self,
        *,
        profile_rows: list,
        related_character_names: list[str],
    ) -> list[CharacterProfileContextItem]:
        ordered_names = [name for name in related_character_names if name]
        profile_by_name = {
            str(row["canonical_name"]).strip(): row
            for row in profile_rows
        }
        items: list[CharacterProfileContextItem] = []
        for name in ordered_names:
            row = profile_by_name.get(name)
            if row is None:
                continue
            items.append(
                CharacterProfileContextItem(
                    canonical_name=name,
                    profile_summary_md=str(row["profile_summary_md"] or ""),
                    aliases=_normalize_string_list(json.loads(row["aliases_json"] or "[]")),
                    importance_score=int(row["importance_score"] or 0),
                )
            )
        return items

    def _infer_related_character_names(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        chapter_rows: list,
        profile_rows: list,
        previous_generated_segment: str | None,
    ) -> list[str]:
        prioritized_names = self._extract_character_mentions(
            "\n".join(
                item
                for item in [step.anchor_context.text, step.reference_truth.text, previous_generated_segment or ""]
                if item
            ),
            profile_rows=profile_rows,
        )
        return infer_character_names(
            chapter_rows,
            prioritized_names=prioritized_names,
        )

    def _extract_character_mentions(self, text: str, *, profile_rows: list) -> list[str]:
        text = _normalize_text(text)
        if not text:
            return []
        matched: list[str] = []
        seen: set[str] = set()
        for row in profile_rows:
            canonical_name = str(row["canonical_name"]).strip()
            aliases = _normalize_string_list(json.loads(row["aliases_json"] or "[]"))
            for candidate in [canonical_name, *aliases]:
                if not candidate or candidate in seen:
                    continue
                if candidate in text:
                    matched.append(canonical_name)
                    seen.add(canonical_name)
                    break
        return matched

    def _build_current_unit_plan(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        story_outline_md: str,
        related_character_names: list[str],
        character_profiles: list[CharacterProfileContextItem],
    ) -> dict[str, object]:
        metadata_plan = self._metadata_dict(sample=sample, step=step, key="current_unit_plan")
        if metadata_plan:
            return {
                "target_chapter_id": sample.config.target_chapter_id,
                "target_segment_id": step.target_segment_id or sample.config.target_segment_id,
                **metadata_plan,
            }
        objective_basis = self._select_objective_basis(
            outline_text=story_outline_md,
            reference_truth=step.reference_truth.text,
        )
        emotional_goal = self._derive_emotional_goal(step.reference_truth.text)
        conflict_goal = self._derive_conflict_goal(step.reference_truth.text)
        must_avoid = self._derive_must_avoid(sample=sample)
        return {
            "target_chapter_id": sample.config.target_chapter_id,
            "target_segment_id": step.target_segment_id or sample.config.target_segment_id,
            "chapter_goal": objective_basis,
            "emotional_goal": emotional_goal,
            "conflict_goal": conflict_goal,
            "must_avoid": must_avoid,
            "relationship_targets": [],
            "related_character_names": list(related_character_names),
            "character_temperament": self._derive_character_temperament(character_profiles),
            "outline_excerpt": story_outline_md.strip(),
            "source_paths": self._build_plan_source_paths(step=step, story_outline_md=story_outline_md),
        }

    def _build_scene_plan_seed(
        self,
        *,
        current_unit_plan: dict[str, object],
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
    ) -> dict[str, object]:
        metadata_seed = self._metadata_dict(sample=sample, step=step, key="scene_plan_seed")
        if metadata_seed:
            return metadata_seed
        narrative_function = self._derive_narrative_function(step.reference_truth.text)
        emotion_mode = self._derive_emotion_mode(step.reference_truth.text)
        style_need = self._derive_style_need(step.reference_truth.text)
        preferred_tags = self._derive_preferred_tags(step.reference_truth.text)
        relationship_state = self._derive_relationship_state(step.reference_truth.text)
        character_temperament = _normalize_string_list(
            current_unit_plan.get("character_temperament")
        )
        return {
            "goal": str(current_unit_plan.get("chapter_goal") or ""),
            "emotional_goal": str(current_unit_plan.get("emotional_goal") or ""),
            "conflict_goal": str(current_unit_plan.get("conflict_goal") or ""),
            "current_relationship_state": relationship_state,
            "forbidden": _normalize_string_list(current_unit_plan.get("must_avoid")),
            "avoidance_items": [],
            "style_reference_query": {
                "narrative_function": narrative_function,
                "emotion_mode": emotion_mode,
                "character_temperament": character_temperament,
                "style_need": style_need,
            },
            "retrieval_hints": {
                "preferred_tags": preferred_tags,
            },
        }

    def _build_scene_brief_seed(
        self,
        *,
        current_unit_plan: dict[str, object],
        scene_plan_seed: dict[str, object],
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
    ) -> dict[str, object]:
        metadata_seed = self._metadata_dict(sample=sample, step=step, key="scene_brief_seed")
        if metadata_seed:
            return metadata_seed
        style_reference_query = _normalize_object_dict(scene_plan_seed.get("style_reference_query"))
        retrieval_hints = _normalize_object_dict(scene_plan_seed.get("retrieval_hints"))
        return {
            "scene_objective": str(current_unit_plan.get("chapter_goal") or ""),
            "emotional_goal": str(current_unit_plan.get("emotional_goal") or ""),
            "conflict_goal": str(current_unit_plan.get("conflict_goal") or ""),
            "narrative_function": _normalize_string_list(
                style_reference_query.get("narrative_function")
            ),
            "emotion_mode": _normalize_string_list(style_reference_query.get("emotion_mode")),
            "character_temperament": _normalize_string_list(
                style_reference_query.get("character_temperament")
            ),
            "relationship_state": _normalize_string_list(
                scene_plan_seed.get("current_relationship_state")
            ),
            "style_need": _normalize_string_list(style_reference_query.get("style_need")),
            "must_avoid": _normalize_string_list(current_unit_plan.get("must_avoid")),
            "preferred_tags": _normalize_string_list(retrieval_hints.get("preferred_tags")),
        }

    def _build_prefix_sources(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        prefix_snapshot: PrefixRuntimeSnapshot,
    ) -> list[dict[str, str]]:
        sources = [
            {"type": "anchor_context", "path": step.anchor_context.path},
        ]
        for item in step.recent_window:
            sources.append({"type": "recent_window", "path": item.path})
        outline_path = prefix_snapshot.asset_paths.get("outline_markdown_path")
        if outline_path:
            sources.append({"type": "authorized_outline", "path": outline_path})
        world_summary_path = prefix_snapshot.asset_paths.get("world_summary_path")
        if world_summary_path:
            sources.append({"type": "world_summary", "path": world_summary_path})
        return sources

    def _build_plan_source_paths(
        self,
        *,
        step: LoadedSmokeStep,
        story_outline_md: str,
    ) -> list[str]:
        paths: list[str] = []
        if story_outline_md.strip():
            paths.append("outline_markdown_path")
        return paths

    def _metadata_dict(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        key: str,
    ) -> dict[str, object]:
        for metadata in (step.metadata, sample.config.metadata):
            value = metadata.get(key)
            if isinstance(value, dict):
                return {str(item_key): item_value for item_key, item_value in value.items()}
        return {}

    def _resolve_target_length_chars(self, *, sample: LoadedSmokeSample, step: LoadedSmokeStep) -> int:
        if sample.config.forward_guidance is not None and sample.config.forward_guidance.target_length_chars > 0:
            return sample.config.forward_guidance.target_length_chars
        metadata_length = int(step.metadata.get("target_length_chars") or 0)
        if metadata_length > 0:
            return metadata_length
        metadata_length = int(sample.config.metadata.get("target_length_chars") or 0)
        if metadata_length > 0:
            return metadata_length
        return max(200, len(step.reference_truth.text))

    def _select_objective_basis(self, *, outline_text: str, reference_truth: str) -> str:
        outline_candidate = self._first_meaningful_line(outline_text)
        if outline_candidate:
            return outline_candidate
        truth_candidate = self._first_sentence(reference_truth)
        if truth_candidate:
            return truth_candidate
        return "推进当前章节目标"

    def _derive_emotional_goal(self, text: str) -> str:
        normalized = text.strip()
        if any(token in normalized for token in ("哭", "难过", "悲", "痛", "发酸", "发涩")):
            return "压住悲伤，保留余波"
        if any(token in normalized for token in ("怒", "恨", "咬牙", "火气", "发狠")):
            return "压住怒意，维持对峙压力"
        if any(token in normalized for token in ("紧", "警惕", "追", "逃", "危险", "悬")):
            return "保持紧张与警觉"
        if any(token in normalized for token in ("靠近", "心跳", "耳热", "暧昧", "喜欢")):
            return "保留未明说的情感张力"
        return "承接上一段情绪并保持克制"

    def _derive_conflict_goal(self, text: str) -> str:
        normalized = text.strip()
        if any(token in normalized for token in ("对峙", "质问", "争", "冲突", "反驳", "沉默")):
            return "保持当前冲突，不让问题过早解决"
        if any(token in normalized for token in ("追", "逃", "拦", "杀", "袭", "追逐")):
            return "维持行动压力并推进局势"
        if any(token in normalized for token in ("告别", "转身", "离开", "诀别")):
            return "推进离场或收束动作，但避免关系被一次性定性"
        return "推进当前局面但避免冲突被一次性解决"

    def _derive_must_avoid(self, *, sample: LoadedSmokeSample) -> list[str]:
        must_avoid: list[str] = ["避免设定冲突"]
        if sample.config.forward_guidance is not None:
            must_avoid.extend(sample.config.forward_guidance.must_not_reveal)
            must_avoid.extend(sample.config.forward_guidance.forbidden_shortcuts)
        return _normalize_string_list(must_avoid)

    def _derive_character_temperament(
        self,
        character_profiles: list[CharacterProfileContextItem],
    ) -> list[str]:
        values: list[str] = []
        for item in character_profiles:
            summary = item.profile_summary_md
            if "克制" in summary:
                values.append("克制")
            if "敏感" in summary:
                values.append("敏感")
            if "冷静" in summary:
                values.append("冷静")
        return _normalize_string_list(values)

    def _derive_narrative_function(self, text: str) -> list[str]:
        values = ["承接推进"]
        if any(token in text for token in ("告别", "离开", "转身", "收住")):
            values.append("收束")
        if any(token in text for token in ("想", "觉得", "心里", "忽然意识到")):
            values.append("情绪沉浸")
        if any(token in text for token in ("问", "说", "答", "开口", "道")):
            values.append("对话施压")
        return _normalize_string_list(values)

    def _derive_emotion_mode(self, text: str) -> list[str]:
        values = ["克制表达"]
        if any(token in text for token in ("紧", "警惕", "危险", "追", "逃")):
            values.append("紧张压迫")
        if any(token in text for token in ("悲", "哭", "难过", "发酸", "发涩")):
            values.append("悲伤低落")
        return _normalize_string_list(values)

    def _derive_style_need(self, text: str) -> list[str]:
        values: list[str] = []
        if any(token in text for token in ("“", "”", "\"")):
            values.append("保留人物对话")
        if any(token in text for token in ("想", "觉得", "心里", "意识到")):
            values.append("内心描写")
        sentences = [item for item in SENTENCE_SPLIT_PATTERN.split(text) if item.strip()]
        avg_length = sum(len(item.strip()) for item in sentences) / len(sentences) if sentences else 0
        if avg_length and avg_length <= 18:
            values.append("短句")
        if not values:
            values.append("中短句")
        return _normalize_string_list(values)

    def _derive_preferred_tags(self, text: str) -> list[str]:
        candidates: list[str] = []
        tag_mapping = {
            "雨": "雨天",
            "医院": "医院",
            "街": "城市街道",
            "告别": "告别",
            "调查": "调查",
            "对峙": "对峙",
            "追": "追逐",
        }
        for token, tag in tag_mapping.items():
            if token in text:
                candidates.append(tag)
        return _normalize_string_list(candidates)[:4]

    def _derive_relationship_state(self, text: str) -> list[str]:
        values: list[str] = []
        if any(token in text for token in ("未和解", "隔阂", "僵", "沉默对峙")):
            values.append("未和解")
        if any(token in text for token in ("暧昧", "心动", "靠近")):
            values.append("暧昧试探")
        if any(token in text for token in ("敌意", "防备", "提防")):
            values.append("彼此防备")
        return _normalize_string_list(values)

    def _read_asset_text(self, assets_row, *, field_name: str) -> str:
        if assets_row is None:
            return ""
        raw_path = str(assets_row[field_name] or "").strip()
        if not raw_path:
            return ""
        path = Path(raw_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _first_meaningful_line(self, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            return stripped
        return ""

    def _first_sentence(self, text: str) -> str:
        for chunk in SENTENCE_SPLIT_PATTERN.split(text):
            stripped = chunk.strip()
            if stripped:
                return stripped
        return ""
