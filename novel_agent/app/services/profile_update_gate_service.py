from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping


LOW_VALUE_CANDIDATE_TYPES = {
    "abstract",
    "concept",
    "low_confidence",
    "non_person",
    "object",
    "place",
    "scene",
    "setting",
    "weak_cooccurrence",
}


@dataclass(slots=True)
class CharacterCurrentImportance:
    detail_level: str
    update_policy: str
    reason: str
    current_segment_score: int
    current_segment_tier: str
    current_doc_frequency: float
    current_doc_count: int
    current_total_docs: int
    speaking_doc_count: int
    action_doc_count: int
    relationship_doc_count: int
    source_doc_ids: list[int]
    source_title_indexes: list[int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterRollingImportance:
    rolling_score: int
    rolling_tier: str
    historical_mention_doc_count: int
    historical_speaking_doc_count: int
    historical_story_event_count: int
    historical_main_event_count: int
    last_seen_doc_id: int | None
    inactive_doc_gap: int | None
    state_transition: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CharacterImportanceTracker:
    """Scores current and rolling character importance for profile update gating."""

    MAIN_EVENT_ROLES = {
        "direct_opponent",
        "identity_reveal",
        "main_driver",
        "main_subject",
        "speaker_source",
        "trigger",
    }

    def __init__(
        self,
        *,
        detailed_min_doc_count: int = 2,
        detailed_min_total_chars: int = 1000,
        stale_after_docs: int = 8,
        cold_after_docs: int = 24,
        name_normalizer: Callable[[object, Mapping[str, Any] | None], str] | None = None,
    ) -> None:
        self.detailed_min_doc_count = max(1, int(detailed_min_doc_count))
        self.detailed_min_total_chars = max(0, int(detailed_min_total_chars))
        self.stale_after_docs = max(1, int(stale_after_docs))
        self.cold_after_docs = max(self.stale_after_docs, int(cold_after_docs))
        self.name_normalizer = name_normalizer or self._default_name_normalizer

    def current_importance_by_key(
        self,
        *,
        evidence_payload: Mapping[str, Any],
        current_total_chars: int = 0,
    ) -> dict[str, dict[str, Any]]:
        stats_by_key: dict[str, dict[str, Any]] = {}
        batch_doc_ids = set(self._int_list(evidence_payload.get("doc_ids")))
        for batch_item in evidence_payload.get("character_evidence_batches", []):
            if isinstance(batch_item, Mapping):
                batch_doc_ids.update(self._int_list(batch_item.get("doc_ids")))
        total_docs = max(1, len(batch_doc_ids))
        for character in self.flatten_evidence_items(evidence_payload):
            character_id = str(character.get("character_id") or "").strip()
            name = self.name_normalizer(character.get("canonical_name"), character)
            raw_aliases = character.get("aliases", [])
            aliases = [
                self.name_normalizer(alias, character)
                for alias in (raw_aliases if isinstance(raw_aliases, list) else [])
            ]
            keys = []
            if character_id:
                keys.append(f"id:{character_id}")
            if name:
                keys.append(f"name:{name}")
            keys.extend(f"name:{alias}" for alias in aliases if alias)
            if not keys:
                continue
            doc_ids = self._int_list(character.get("source_doc_ids") or character.get("doc_ids"))
            if not doc_ids:
                doc_ids = self._int_list(evidence_payload.get("doc_ids"))
            title_indexes = self._int_list(character.get("source_title_indexes") or character.get("document_title_indexes"))
            has_speaking = bool(character.get("is_speaking_character"))
            has_action = bool(str(character.get("activity_or_state_evidence") or "").strip())
            has_relationship = bool(str(character.get("relationship_evidence") or "").strip())
            confidence = self._float(character.get("confidence"))
            candidate_type = str(character.get("candidate_type") or "character").strip().lower()
            for key in keys:
                stats = stats_by_key.setdefault(
                    key,
                    {
                        "doc_ids": set(),
                        "title_indexes": set(),
                        "speaking_doc_ids": set(),
                        "action_doc_ids": set(),
                        "relationship_doc_ids": set(),
                        "confidences": [],
                        "candidate_types": set(),
                        "evidence_items": 0,
                    },
                )
                stats["doc_ids"].update(doc_ids)
                stats["title_indexes"].update(title_indexes)
                if has_speaking:
                    stats["speaking_doc_ids"].update(doc_ids or [0])
                if has_action:
                    stats["action_doc_ids"].update(doc_ids or [0])
                if has_relationship:
                    stats["relationship_doc_ids"].update(doc_ids or [0])
                if confidence > 0:
                    stats["confidences"].append(confidence)
                if candidate_type:
                    stats["candidate_types"].add(candidate_type)
                stats["evidence_items"] += 1
        return {
            key: self._current_importance_from_stats(
                stats,
                total_docs=total_docs,
                current_total_chars=current_total_chars,
            ).to_dict()
            for key, stats in stats_by_key.items()
        }

    def rolling_importance(
        self,
        profile: Mapping[str, Any],
        *,
        current_doc_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        mentioned_doc_ids = set(self._int_list(profile.get("mentioned_doc_ids")))
        speaking_doc_ids = set(self._int_list(profile.get("speaking_doc_ids")))
        story_events = [item for item in self._list(profile.get("story_events")) if isinstance(item, Mapping)]
        main_events = [
            item
            for item in story_events
            if str(item.get("role_in_segment") or "").strip() in self.MAIN_EVENT_ROLES
        ]
        last_seen = self._int(profile.get("last_seen_doc_id"))
        if last_seen is None and mentioned_doc_ids:
            last_seen = max(mentioned_doc_ids)
        current_min_doc = min(current_doc_ids) if current_doc_ids else None
        inactive_gap = current_min_doc - last_seen if current_min_doc is not None and last_seen is not None else None
        raw_score = (
            min(30, len(mentioned_doc_ids) * 2)
            + min(20, len(speaking_doc_ids) * 4)
            + min(30, len(story_events) * 5)
            + min(20, len(main_events) * 7)
            + min(20, max(0, self._int(profile.get("importance_score")) or 0) * 4)
        )
        if inactive_gap is not None and inactive_gap > self.cold_after_docs:
            raw_score = max(0, raw_score - 30)
        elif inactive_gap is not None and inactive_gap > self.stale_after_docs:
            raw_score = max(0, raw_score - 12)
        score = max(0, min(100, raw_score))
        if score >= 65:
            tier = "high"
        elif score >= 30:
            tier = "medium"
        else:
            tier = "low"
        if inactive_gap is not None and inactive_gap > self.cold_after_docs:
            transition = "compact_recent_to_older_and_cool_down"
        elif inactive_gap is not None and inactive_gap > self.stale_after_docs:
            transition = "downgrade_recent_activity"
        elif tier == "high":
            transition = "keep_hot"
        else:
            transition = "keep_cold"
        return CharacterRollingImportance(
            rolling_score=score,
            rolling_tier=tier,
            historical_mention_doc_count=len(mentioned_doc_ids),
            historical_speaking_doc_count=len(speaking_doc_ids),
            historical_story_event_count=len(story_events),
            historical_main_event_count=len(main_events),
            last_seen_doc_id=last_seen,
            inactive_doc_gap=inactive_gap,
            state_transition=transition,
        ).to_dict()

    def flatten_evidence_items(self, evidence_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        characters = evidence_payload.get("characters")
        if isinstance(characters, list):
            batch_doc_ids = self._int_list(evidence_payload.get("doc_ids"))
            batch_title_indexes = self._int_list(evidence_payload.get("document_title_indexes"))
            flattened: list[dict[str, Any]] = []
            for item in characters:
                if not isinstance(item, Mapping):
                    continue
                character = dict(item)
                character.setdefault("source_doc_ids", batch_doc_ids)
                character.setdefault("source_title_indexes", batch_title_indexes)
                flattened.append(character)
            return flattened
        flattened: list[dict[str, Any]] = []
        for evidence_batch in evidence_payload.get("character_evidence_batches", []):
            if not isinstance(evidence_batch, Mapping):
                continue
            batch_doc_ids = self._int_list(evidence_batch.get("doc_ids"))
            batch_title_indexes = self._int_list(evidence_batch.get("document_title_indexes"))
            for item in evidence_batch.get("characters", []):
                if isinstance(item, Mapping):
                    character = dict(item)
                    character.setdefault("source_doc_ids", batch_doc_ids)
                    character.setdefault("source_title_indexes", batch_title_indexes)
                    flattened.append(character)
        return flattened

    def _current_importance_from_stats(
        self,
        stats: Mapping[str, Any],
        *,
        total_docs: int,
        current_total_chars: int,
    ) -> CharacterCurrentImportance:
        doc_ids = sorted(int(item) for item in stats["doc_ids"])
        title_indexes = sorted(int(item) for item in stats["title_indexes"])
        doc_count = len(doc_ids)
        frequency = doc_count / max(1, total_docs)
        speaking_count = len(stats["speaking_doc_ids"])
        action_count = len(stats["action_doc_ids"])
        relationship_count = len(stats["relationship_doc_ids"])
        confidences = [float(item) for item in stats.get("confidences", [])]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        candidate_types = {str(item) for item in stats.get("candidate_types", set())}
        low_value = bool(candidate_types and candidate_types.issubset(LOW_VALUE_CANDIDATE_TYPES))
        score = self._current_segment_score(
            frequency=frequency,
            speaking_count=speaking_count,
            action_count=action_count,
            relationship_count=relationship_count,
            avg_confidence=avg_confidence,
            low_value=low_value,
        )
        tier = "high" if score >= 70 else "medium" if score >= 35 else "low"
        has_detailed_doc_span = doc_count >= self.detailed_min_doc_count
        has_enough_text = current_total_chars <= 0 or current_total_chars >= self.detailed_min_total_chars or doc_count >= 3
        has_direct_plot_signal = speaking_count > 0 or action_count >= 2 or relationship_count > 0
        if low_value:
            detail_level = "index_only"
            update_policy = "drop_for_profile"
            reason = "low_value_candidate_type"
        elif has_detailed_doc_span and has_enough_text and frequency >= 0.6 and has_direct_plot_signal:
            detail_level = "detailed"
            update_policy = "reduce_now"
            reason = "appears_in_most_current_documents_with_direct_plot_signal"
        elif has_detailed_doc_span and has_enough_text and frequency >= 0.75:
            detail_level = "detailed"
            update_policy = "reduce_now"
            reason = "appears_in_most_current_documents"
        elif speaking_count > 0 or action_count > 0 or relationship_count > 0:
            detail_level = "compact"
            update_policy = "reduce_now"
            reason = "has_current_direct_signal_but_not_batch_wide"
        else:
            detail_level = "index_only"
            update_policy = "defer_index_only"
            reason = "low_frequency_or_background_role"
        return CharacterCurrentImportance(
            detail_level=detail_level,
            update_policy=update_policy,
            reason=reason,
            current_segment_score=score,
            current_segment_tier=tier,
            current_doc_frequency=round(frequency, 3),
            current_doc_count=doc_count,
            current_total_docs=total_docs,
            speaking_doc_count=speaking_count,
            action_doc_count=action_count,
            relationship_doc_count=relationship_count,
            source_doc_ids=doc_ids,
            source_title_indexes=title_indexes,
        )

    @staticmethod
    def _current_segment_score(
        *,
        frequency: float,
        speaking_count: int,
        action_count: int,
        relationship_count: int,
        avg_confidence: float,
        low_value: bool,
    ) -> int:
        score = min(40, round(frequency * 40))
        score += min(35, speaking_count * 14 + action_count * 10 + relationship_count * 10)
        score += min(15, round(max(0.0, min(1.0, avg_confidence)) * 15))
        if low_value:
            score = min(score, 20)
        return max(0, min(100, score))

    @staticmethod
    def _default_name_normalizer(value: object, _character: Mapping[str, Any] | None = None) -> str:
        return str(value or "").strip()

    @staticmethod
    def _list(value: Any) -> list[Any]:
        return list(value) if isinstance(value, list) else []

    @staticmethod
    def _int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _int_list(cls, value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        for item in value:
            number = cls._int(item)
            if number is not None and number not in result:
                result.append(number)
        return result

    @staticmethod
    def _float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0


class ProfileUpdateGateService:
    """Combines current segment, rolling history, and state transition gates."""

    def __init__(self, *, tracker: CharacterImportanceTracker | None = None) -> None:
        self.tracker = tracker or CharacterImportanceTracker()

    def gates_for_evidence(
        self,
        *,
        evidence_payload: Mapping[str, Any],
        current_total_chars: int = 0,
    ) -> dict[str, dict[str, Any]]:
        return self.tracker.current_importance_by_key(
            evidence_payload=evidence_payload,
            current_total_chars=current_total_chars,
        )

    def gate_for_profile(
        self,
        profile: Mapping[str, Any],
        *,
        profile_gates: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        current_gate = self._current_gate_for_profile(profile, profile_gates=profile_gates)
        rolling = self.tracker.rolling_importance(
            profile,
            current_doc_ids=self._int_list(current_gate.get("source_doc_ids")),
        )
        combined = self._combine(current_gate=current_gate, rolling=rolling)
        return {
            **combined,
            "current_importance": dict(current_gate),
            "rolling_importance": rolling,
            "state_transition": combined["state_transition"],
        }

    def _current_gate_for_profile(
        self,
        profile: Mapping[str, Any],
        *,
        profile_gates: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        keys = [f"id:{profile.get('character_id')}"]
        canonical_name = str(profile.get("canonical_name") or "").strip()
        if canonical_name:
            keys.append(f"name:{canonical_name}")
        keys.extend(f"name:{alias}" for alias in profile.get("aliases", []) if str(alias).strip())
        for key in keys:
            gate = profile_gates.get(key)
            if gate:
                return dict(gate)
        return {
            "detail_level": "index_only",
            "update_policy": "defer_index_only",
            "reason": "matched_profile_not_confirmed_as_current_core_character",
            "current_segment_score": 0,
            "current_segment_tier": "low",
            "current_doc_frequency": 0.0,
            "current_doc_count": 0,
            "current_total_docs": 0,
            "speaking_doc_count": 0,
            "action_doc_count": 0,
            "relationship_doc_count": 0,
            "source_doc_ids": [],
            "source_title_indexes": [],
        }

    def _combine(self, *, current_gate: Mapping[str, Any], rolling: Mapping[str, Any]) -> dict[str, Any]:
        detail_level = str(current_gate.get("detail_level") or "index_only")
        update_policy = str(current_gate.get("update_policy") or "defer_index_only")
        reason = str(current_gate.get("reason") or "profile_update_gate")
        rolling_tier = str(rolling.get("rolling_tier") or "low")
        current_doc_count = int(current_gate.get("current_doc_count") or 0)
        direct_signal = (
            int(current_gate.get("speaking_doc_count") or 0) > 0
            or int(current_gate.get("action_doc_count") or 0) > 0
            or int(current_gate.get("relationship_doc_count") or 0) > 0
        )
        if detail_level == "compact" and rolling_tier == "high" and direct_signal:
            detail_level = "detailed"
            update_policy = "reduce_now"
            reason = "rolling_core_character_with_current_direct_signal"
        elif detail_level == "index_only" and rolling_tier == "high" and current_doc_count > 0:
            detail_level = "compact"
            update_policy = "reduce_now"
            reason = "rolling_core_character_with_current_mention"
        elif update_policy == "drop_for_profile":
            detail_level = "index_only"
        state_transition = self._state_transition(
            detail_level=detail_level,
            update_policy=update_policy,
            rolling_transition=str(rolling.get("state_transition") or ""),
        )
        return {
            **dict(current_gate),
            "detail_level": detail_level,
            "update_policy": update_policy,
            "reason": reason,
            "rolling_score": rolling.get("rolling_score"),
            "rolling_tier": rolling_tier,
            "state_transition": state_transition,
        }

    @staticmethod
    def _state_transition(*, detail_level: str, update_policy: str, rolling_transition: str) -> str:
        if update_policy == "drop_for_profile":
            return "drop_for_profile"
        if detail_level == "detailed":
            return "promote_or_keep_hot_reduce_now"
        if detail_level == "compact":
            return "compact_reduce_now"
        if rolling_transition in {"compact_recent_to_older_and_cool_down", "downgrade_recent_activity"}:
            return rolling_transition
        return "defer_index_only"

    @staticmethod
    def _int_list(value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        for item in value:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if number not in result:
                result.append(number)
        return result
