from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..llm import JsonModelClient
from ..prompts.character_identity_merge_prompt import build_character_identity_merge_prompt
from ..repos.character_profiles_repo import CharacterProfilesRepo
from .character_profile_service import CharacterProfileService, _utc_now


@dataclass(slots=True)
class CharacterIdentityMergeEvidence:
    summary: str
    source_doc_ids: list[int] = field(default_factory=list)
    source_title_indexes: list[int] = field(default_factory=list)
    outline_segment_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    decision_source: str = "model_identity_reveal"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterIdentityMergeResult:
    merged: bool
    reason: str
    survivor_character_id: int | None = None
    survivor_canonical_name: str = ""
    merged_character_ids: list[int] = field(default_factory=list)
    deleted_canonical_names: list[str] = field(default_factory=list)
    aliases_added: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterIdentityMergeCandidateResult:
    candidate_id: str
    status: str
    gate_level: str
    recommended_action: str
    same_person_score: int
    confidence: float
    reason: str
    left_name: str = ""
    right_name: str = ""
    survivor_canonical_name: str = ""
    aliases_to_keep: list[str] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)
    outline_segment_ids: list[str] = field(default_factory=list)

    @property
    def blocks_close_read(self) -> bool:
        return self.status == "pending_user_confirmation"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CharacterIdentityMergeService:
    """Merges existing character profiles after an explicit identity reveal.

    Candidate discovery is intentionally separate from the deterministic merge.
    This service only mutates profiles when upstream evidence or a model review has
    already established that two existing profiles refer to the same person.
    """

    VALID_DECISION_SOURCES = {
        "model_identity_reveal",
        "character_evidence",
        "profile_update",
        "user_confirmed",
        "manual_repair",
    }
    LOW_SCORE_THRESHOLD = 75
    HIGH_SCORE_THRESHOLD = 90
    MERGE_RELATED_ACTIONS = {"merge_profiles", "memory_correction"}
    TERMINAL_CANDIDATE_STATUSES = {"merged", "rejected", "routed_to_memory_correction"}

    def __init__(
        self,
        *,
        profiles_repo: CharacterProfilesRepo,
        min_confidence: float = 0.9,
    ) -> None:
        self.profiles_repo = profiles_repo
        self.profile_service = CharacterProfileService(profiles_repo=profiles_repo)
        self.min_confidence = float(min_confidence)

    def review_candidate(
        self,
        conn,
        *,
        book_id: str,
        model_client: JsonModelClient,
        left_character_id: object = None,
        left_name: object = "",
        right_character_id: object = None,
        right_name: object = "",
        evidence: CharacterIdentityMergeEvidence,
    ) -> dict[str, Any]:
        left = self._resolve_profile(conn, book_id=book_id, character_id=left_character_id, canonical_name=left_name)
        right = self._resolve_profile(conn, book_id=book_id, character_id=right_character_id, canonical_name=right_name)
        if left is None or right is None:
            return {
                "action": "request_more_evidence",
                "survivor_canonical_name": "",
                "aliases_to_keep": [],
                "reason": "candidate profile missing",
                "confidence": 0.0,
            }
        system_prompt, user_prompt = build_character_identity_merge_prompt(
            {
                "book_id": book_id,
                "left_profile": self._profile_review_summary(left),
                "right_profile": self._profile_review_summary(right),
                "identity_reveal_evidence": evidence.to_dict(),
            }
        )
        payload, _ = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: {
                "action": "request_more_evidence",
                "survivor_canonical_name": "",
                "aliases_to_keep": [],
                "reason": "fallback cannot confirm identity merge",
                "confidence": 0.0,
            },
            use_fallback_on_error=model_client.settings.dry_run,
        )
        return self._normalize_review_decision(payload)

    def review_revelations(
        self,
        conn,
        *,
        book_id: str,
        model_client: JsonModelClient,
        revelations: object,
    ) -> list[CharacterIdentityMergeCandidateResult]:
        results: list[CharacterIdentityMergeCandidateResult] = []
        if not isinstance(revelations, list):
            return results
        for revelation in revelations:
            if not isinstance(revelation, Mapping):
                continue
            if not self._same_person_revelation(revelation):
                continue
            evidence = self._evidence_from_revelation(revelation)
            left = self._resolve_profile(
                conn,
                book_id=book_id,
                character_id=revelation.get("left_character_id"),
                canonical_name=revelation.get("left_name") or revelation.get("left_canonical_name"),
            )
            right = self._resolve_profile(
                conn,
                book_id=book_id,
                character_id=revelation.get("right_character_id"),
                canonical_name=revelation.get("right_name") or revelation.get("right_canonical_name"),
            )
            left_name = str(revelation.get("left_name") or revelation.get("left_canonical_name") or "").strip()
            right_name = str(revelation.get("right_name") or revelation.get("right_canonical_name") or "").strip()
            if left is None or right is None:
                decision = {
                    "recommended_action": "need_more_evidence",
                    "same_person_score": 0,
                    "confidence": 0.0,
                    "survivor_canonical_name": "",
                    "aliases_to_keep": [],
                    "evidence_summary": evidence.summary,
                    "evidence_strengths": [],
                    "evidence_gaps": ["candidate profile missing"],
                    "reason": "candidate profile missing",
                    "requires_user_confirmation": False,
                }
                results.append(
                    self._candidate_result_from_decision(
                        conn,
                        book_id=book_id,
                        left=left,
                        right=right,
                        left_name=left_name,
                        right_name=right_name,
                        evidence=evidence,
                        decision=decision,
                    )
                )
                continue
            if self._row_id(left) == self._row_id(right):
                results.append(
                    CharacterIdentityMergeCandidateResult(
                        candidate_id=self._candidate_id(
                            book_id=book_id,
                            left_id=self._row_id(left),
                            right_id=self._row_id(right),
                            left_name=left_name or self._row_name(left),
                            right_name=right_name or self._row_name(right),
                            evidence=evidence,
                        ),
                        status="already_same_profile",
                        gate_level="none",
                        recommended_action="keep_separate",
                        same_person_score=100,
                        confidence=1.0,
                        reason="candidate names already resolve to the same profile",
                        left_name=left_name or self._row_name(left),
                        right_name=right_name or self._row_name(right),
                        survivor_canonical_name=self._row_name(left),
                        aliases_to_keep=[],
                        source_doc_ids=evidence.source_doc_ids,
                        outline_segment_ids=evidence.outline_segment_ids,
                    )
                )
                continue
            decision = self.review_candidate(
                conn,
                book_id=book_id,
                model_client=model_client,
                left_character_id=self._row_id(left),
                right_character_id=self._row_id(right),
                evidence=evidence,
            )
            results.append(
                self._candidate_result_from_decision(
                    conn,
                    book_id=book_id,
                    left=left,
                    right=right,
                    left_name=left_name or self._row_name(left),
                    right_name=right_name or self._row_name(right),
                    evidence=evidence,
                    decision=decision,
                )
            )
        return results

    def score_name_identity(
        self,
        *,
        model_client: JsonModelClient,
        book_id: str,
        candidate_names: list[str],
        evidence_context: list[dict[str, Any]],
        profile_context: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Score whether several names refer to one person without mutating memory."""

        names = self._name_list(candidate_names)
        if len(names) < 2:
            raise ValueError("score_name_identity requires at least two candidate names")
        system_prompt, user_prompt = build_character_identity_merge_prompt(
            {
                "book_id": book_id,
                "candidate_names": names,
                "profile_context": profile_context or [],
                "identity_reveal_evidence": {
                    "summary": "Evaluate whether the candidate names refer to the same person based only on the supplied local context.",
                    "source_doc_ids": sorted(
                        {
                            doc_id
                            for item in evidence_context
                            for doc_id in self._int_list(item.get("source_doc_ids") or item.get("doc_id"))
                        }
                    ),
                    "outline_segment_ids": sorted(
                        {
                            segment_id
                            for item in evidence_context
                            for segment_id in self._name_list(item.get("outline_segment_ids") or item.get("outline_segment_id"))
                        }
                    ),
                },
                "evidence_context": evidence_context,
            }
        )
        payload, _ = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: {
                "recommended_action": "need_more_evidence",
                "same_person_score": 0,
                "confidence": 0.0,
                "survivor_canonical_name": "",
                "aliases_to_keep": [],
                "evidence_summary": "",
                "evidence_strengths": [],
                "evidence_gaps": ["fallback cannot score identity candidate"],
                "reason": "fallback cannot score identity candidate",
                "requires_user_confirmation": False,
            },
            use_fallback_on_error=model_client.settings.dry_run,
        )
        return self._normalize_review_decision(payload)

    def merge_revelations(
        self,
        conn,
        *,
        book_id: str,
        revelations: object,
    ) -> list[CharacterIdentityMergeResult]:
        results: list[CharacterIdentityMergeResult] = []
        if not isinstance(revelations, list):
            return results
        for revelation in revelations:
            if not isinstance(revelation, Mapping):
                continue
            evidence = self._evidence_from_revelation(revelation)
            if not self._same_person_revelation(revelation):
                results.append(CharacterIdentityMergeResult(merged=False, reason="revelation is not same_person"))
                continue
            left = self._resolve_profile(
                conn,
                book_id=book_id,
                character_id=revelation.get("left_character_id"),
                canonical_name=revelation.get("left_name") or revelation.get("left_canonical_name"),
            )
            right = self._resolve_profile(
                conn,
                book_id=book_id,
                character_id=revelation.get("right_character_id"),
                canonical_name=revelation.get("right_name") or revelation.get("right_canonical_name"),
            )
            if left is None or right is None:
                results.append(CharacterIdentityMergeResult(merged=False, reason="candidate profile missing"))
                continue
            survivor = self._choose_survivor(left, right, preferred_name=revelation.get("survivor_canonical_name"))
            duplicate = right if self._row_id(survivor) == self._row_id(left) else left
            aliases_to_keep = self._name_list(revelation.get("aliases_to_keep"))
            aliases_to_keep.extend(
                self._name_list(
                    [
                        revelation.get("left_name"),
                        revelation.get("left_canonical_name"),
                        revelation.get("right_name"),
                        revelation.get("right_canonical_name"),
                    ]
                )
            )
            results.append(
                self.merge_confirmed_profiles(
                    conn,
                    book_id=book_id,
                    survivor_character_id=self._row_id(survivor),
                    duplicate_character_id=self._row_id(duplicate),
                    evidence=evidence,
                    aliases_to_keep=aliases_to_keep,
                )
            )
        return results

    def _candidate_result_from_decision(
        self,
        conn,
        *,
        book_id: str,
        left: Any | None,
        right: Any | None,
        left_name: str,
        right_name: str,
        evidence: CharacterIdentityMergeEvidence,
        decision: Mapping[str, Any],
    ) -> CharacterIdentityMergeCandidateResult:
        score = self._score(decision.get("same_person_score"))
        confidence = self._float(decision.get("confidence"))
        recommended_action = str(decision.get("recommended_action") or "").strip()
        gate_level, status = self._gate_for_decision(score=score, recommended_action=recommended_action)
        left_id = self._row_id(left) if left is not None else 0
        right_id = self._row_id(right) if right is not None else 0
        candidate_id = self._candidate_id(
            book_id=book_id,
            left_id=left_id,
            right_id=right_id,
            left_name=left_name,
            right_name=right_name,
            evidence=evidence,
        )
        existing_pair_candidate = self._existing_candidate_for_pair(
            conn,
            book_id=book_id,
            left_id=left_id,
            right_id=right_id,
            left_name=left_name,
            right_name=right_name,
        )
        if existing_pair_candidate is not None:
            candidate_id = str(existing_pair_candidate["candidate_id"] or candidate_id)
        result = CharacterIdentityMergeCandidateResult(
            candidate_id=candidate_id,
            status=status,
            gate_level=gate_level,
            recommended_action=recommended_action,
            same_person_score=score,
            confidence=confidence,
            reason=str(decision.get("reason") or "").strip(),
            left_name=left_name,
            right_name=right_name,
            survivor_canonical_name=str(decision.get("survivor_canonical_name") or "").strip(),
            aliases_to_keep=self._name_list(decision.get("aliases_to_keep")),
            source_doc_ids=evidence.source_doc_ids,
            outline_segment_ids=evidence.outline_segment_ids,
        )
        existing = conn.execute(
            "SELECT status FROM character_identity_merge_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        existing_status = str(existing["status"] or "") if existing is not None else ""
        if existing_status in self.TERMINAL_CANDIDATE_STATUSES:
            result.status = existing_status
            result.gate_level = "none"
            return result
        if status in {"needs_more_evidence", "pending_user_confirmation"}:
            self._upsert_candidate(
                conn,
                book_id=book_id,
                result=result,
                left_id=left_id,
                right_id=right_id,
                evidence=evidence,
                decision=decision,
            )
        return result

    def mark_related_candidates_resolved(
        self,
        conn,
        *,
        book_id: str,
        resolved_candidate_id: str,
        left_character_id: object,
        right_character_id: object,
        left_name: object,
        right_name: object,
        status: str,
        resolution_reason: str,
    ) -> int:
        if status not in self.TERMINAL_CANDIDATE_STATUSES:
            raise ValueError("related identity candidates can only be resolved to a terminal status")
        names = self._name_list([left_name, right_name])
        ids = [item for item in [self._safe_int(left_character_id), self._safe_int(right_character_id)] if item > 0]
        if len(ids) < 2 and len(names) < 2:
            return 0
        rows = self._candidate_rows_for_pair(
            conn,
            book_id=book_id,
            left_id=ids[0] if len(ids) > 0 else 0,
            right_id=ids[1] if len(ids) > 1 else 0,
            left_name=names[0] if len(names) > 0 else "",
            right_name=names[1] if len(names) > 1 else "",
        )
        changed = 0
        now = _utc_now()
        for row in rows:
            candidate_id = str(row["candidate_id"] or "")
            if not candidate_id or candidate_id == resolved_candidate_id:
                continue
            if str(row["status"] or "") in self.TERMINAL_CANDIDATE_STATUSES:
                continue
            decision = self._load_json_dict(row, "decision_json")
            decision.update(
                {
                    "resolution_reason": resolution_reason,
                    "resolved_by_candidate_id": resolved_candidate_id,
                }
            )
            conn.execute(
                """
                UPDATE character_identity_merge_candidates
                SET status = ?, gate_level = ?, decision_json = ?, resolved_at = ?, updated_at = ?
                WHERE candidate_id = ?
                """,
                (status, "none", json.dumps(decision, ensure_ascii=False), now, now, candidate_id),
            )
            changed += 1
        return changed

    def _gate_for_decision(self, *, score: int, recommended_action: str) -> tuple[str, str]:
        if recommended_action not in self.MERGE_RELATED_ACTIONS:
            return "none", "skipped"
        if score >= self.HIGH_SCORE_THRESHOLD:
            return "high", "pending_user_confirmation"
        if score >= self.LOW_SCORE_THRESHOLD:
            return "medium", "needs_more_evidence"
        return "low", "skipped_low_score"

    def _upsert_candidate(
        self,
        conn,
        *,
        book_id: str,
        result: CharacterIdentityMergeCandidateResult,
        left_id: int,
        right_id: int,
        evidence: CharacterIdentityMergeEvidence,
        decision: Mapping[str, Any],
    ) -> None:
        now = _utc_now()
        existing = conn.execute(
            "SELECT candidate_id, created_at FROM character_identity_merge_candidates WHERE candidate_id = ?",
            (result.candidate_id,),
        ).fetchone()
        created_at = str(existing["created_at"] or "") if existing is not None else now
        conn.execute(
            """
            INSERT INTO character_identity_merge_candidates(
                candidate_id, book_id, status, gate_level, recommended_action,
                same_person_score, confidence, reason, evidence_summary,
                left_character_id, left_name, right_character_id, right_name,
                survivor_canonical_name, aliases_to_keep_json,
                source_doc_ids_json, source_title_indexes_json, outline_segment_ids_json,
                decision_json, created_at, updated_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                status = excluded.status,
                gate_level = excluded.gate_level,
                recommended_action = excluded.recommended_action,
                same_person_score = excluded.same_person_score,
                confidence = excluded.confidence,
                reason = excluded.reason,
                evidence_summary = excluded.evidence_summary,
                left_character_id = excluded.left_character_id,
                left_name = excluded.left_name,
                right_character_id = excluded.right_character_id,
                right_name = excluded.right_name,
                survivor_canonical_name = excluded.survivor_canonical_name,
                aliases_to_keep_json = excluded.aliases_to_keep_json,
                source_doc_ids_json = excluded.source_doc_ids_json,
                source_title_indexes_json = excluded.source_title_indexes_json,
                outline_segment_ids_json = excluded.outline_segment_ids_json,
                decision_json = excluded.decision_json,
                updated_at = excluded.updated_at
            """,
            (
                result.candidate_id,
                book_id,
                result.status,
                result.gate_level,
                result.recommended_action,
                result.same_person_score,
                result.confidence,
                result.reason,
                str(decision.get("evidence_summary") or evidence.summary or "").strip(),
                left_id or None,
                result.left_name,
                right_id or None,
                result.right_name,
                result.survivor_canonical_name,
                json.dumps(result.aliases_to_keep, ensure_ascii=False),
                json.dumps(evidence.source_doc_ids, ensure_ascii=False),
                json.dumps(evidence.source_title_indexes, ensure_ascii=False),
                json.dumps(evidence.outline_segment_ids, ensure_ascii=False),
                json.dumps(dict(decision), ensure_ascii=False),
                created_at,
                now,
                "",
            ),
        )

    def _normalize_review_decision(self, payload: object) -> dict[str, Any]:
        decision = dict(payload) if isinstance(payload, dict) else {}
        legacy_action = str(decision.get("action") or "").strip()
        recommended_action = str(decision.get("recommended_action") or "").strip()
        if not recommended_action and legacy_action:
            recommended_action = {
                "merge": "merge_profiles",
                "keep_separate": "keep_separate",
                "request_more_evidence": "need_more_evidence",
            }.get(legacy_action, "")
        if recommended_action not in {"merge_profiles", "memory_correction", "keep_separate", "need_more_evidence"}:
            raise RuntimeError("Character identity merge review model returned an invalid recommended_action")
        decision["recommended_action"] = recommended_action
        score = self._score(decision.get("same_person_score"))
        if "same_person_score" not in decision and recommended_action == "merge_profiles":
            score = self._score(self._float(decision.get("confidence")) * 100)
        decision["same_person_score"] = score
        decision["confidence"] = self._float(decision.get("confidence"))
        decision["aliases_to_keep"] = self._name_list(decision.get("aliases_to_keep"))
        for field_name in ("evidence_strengths", "evidence_gaps"):
            decision[field_name] = self._name_list(decision.get(field_name))
        pairwise_scores: list[dict[str, Any]] = []
        raw_pairwise = decision.get("pairwise_scores")
        if isinstance(raw_pairwise, list):
            for item in raw_pairwise:
                if not isinstance(item, Mapping):
                    continue
                left_name = str(item.get("left_name") or "").strip()
                right_name = str(item.get("right_name") or "").strip()
                if not left_name or not right_name:
                    continue
                pairwise_scores.append(
                    {
                        "left_name": left_name,
                        "right_name": right_name,
                        "score": self._score(item.get("score")),
                        "reason": str(item.get("reason") or "").strip(),
                    }
                )
        decision["pairwise_scores"] = pairwise_scores
        decision["requires_user_confirmation"] = bool(decision.get("requires_user_confirmation", score >= self.HIGH_SCORE_THRESHOLD))
        return decision

    def merge_confirmed_profiles(
        self,
        conn,
        *,
        book_id: str,
        survivor_character_id: object = None,
        survivor_canonical_name: object = "",
        duplicate_character_id: object = None,
        duplicate_canonical_name: object = "",
        evidence: CharacterIdentityMergeEvidence,
        aliases_to_keep: list[str] | None = None,
    ) -> CharacterIdentityMergeResult:
        invalid_reason = self._invalid_evidence_reason(evidence)
        if invalid_reason:
            return CharacterIdentityMergeResult(merged=False, reason=invalid_reason)
        survivor = self._resolve_profile(
            conn,
            book_id=book_id,
            character_id=survivor_character_id,
            canonical_name=survivor_canonical_name,
        )
        duplicate = self._resolve_profile(
            conn,
            book_id=book_id,
            character_id=duplicate_character_id,
            canonical_name=duplicate_canonical_name,
        )
        if survivor is None or duplicate is None:
            return CharacterIdentityMergeResult(merged=False, reason="candidate profile missing")
        survivor_id = self._row_id(survivor)
        duplicate_id = self._row_id(duplicate)
        if survivor_id <= 0 or duplicate_id <= 0 or survivor_id == duplicate_id:
            return CharacterIdentityMergeResult(merged=False, reason="profiles are identical or invalid")

        survivor_name = self._row_name(survivor)
        duplicate_name = self._row_name(duplicate)
        merged = self.profile_service._merge_existing_rows([survivor, duplicate])  # noqa: SLF001
        identity_event = self._identity_event(
            survivor_name=survivor_name,
            duplicate_name=duplicate_name,
            survivor_id=survivor_id,
            duplicate_id=duplicate_id,
            evidence=evidence,
        )
        story_events = self.profile_service._merge_story_events(  # noqa: SLF001
            merged["story_events"],
            [identity_event],
            chapter_index=self._latest_title_index(merged, evidence),
            doc_ids=evidence.source_doc_ids,
        )
        aliases = self.profile_service._merge_aliases(  # noqa: SLF001
            merged["aliases"],
            [
                duplicate_name,
                *self._load_json_list(duplicate, "aliases_json"),
                *(aliases_to_keep or []),
            ],
            canonical_name=survivor_name,
        )
        personhood_summary = self.profile_service._merge_personhood_evidence_summary(  # noqa: SLF001
            merged["personhood_evidence_summary"],
            f"身份揭示：{duplicate_name} 与 {survivor_name} 指向同一人物；{evidence.summary}",
        )
        snapshot = self._snapshot_payload(
            book_id=book_id,
            canonical_name=survivor_name,
            merged=merged,
            aliases=aliases,
            story_events=story_events,
            personhood_evidence_summary=personhood_summary,
            evidence=evidence,
        )
        self.profiles_repo.upsert(conn, snapshot)
        self.profiles_repo.delete_many(conn, book_id=book_id, canonical_names=[duplicate_name])
        rewritten = self._rewrite_profile_references(
            conn,
            book_id=book_id,
            old_names=[duplicate_name, *self._load_json_list(duplicate, "aliases_json")],
            new_name=survivor_name,
            exclude_character_id=survivor_id,
        )
        _ = rewritten
        aliases_added = [alias for alias in aliases if alias == duplicate_name or alias in self._load_json_list(duplicate, "aliases_json")]
        return CharacterIdentityMergeResult(
            merged=True,
            reason="merged confirmed same-person profiles",
            survivor_character_id=survivor_id,
            survivor_canonical_name=survivor_name,
            merged_character_ids=[survivor_id, duplicate_id],
            deleted_canonical_names=[duplicate_name],
            aliases_added=aliases_added,
        )

    def _snapshot_payload(
        self,
        *,
        book_id: str,
        canonical_name: str,
        merged: dict[str, Any],
        aliases: list[str],
        story_events: list[dict[str, Any]],
        personhood_evidence_summary: str,
        evidence: CharacterIdentityMergeEvidence,
    ) -> dict[str, Any]:
        chapter_indexes = self.profile_service._merge_chapter_indexes(  # noqa: SLF001
            merged["chapter_indexes"],
            evidence.source_title_indexes,
        )
        mentioned_doc_ids = self.profile_service._merge_chapter_indexes(  # noqa: SLF001
            merged["mentioned_doc_ids"],
            evidence.source_doc_ids,
        )
        from ..schemas.character_profile_schema import (
            CharacterAbilityItem,
            CharacterAgeItem,
            CharacterProfileSnapshot,
            CharacterRelationshipItem,
            CharacterStoryEventItem,
            ProfileAttributeItem,
        )

        snapshot = CharacterProfileSnapshot(
            canonical_name=canonical_name,
            aliases=aliases,
            speaking_character_status=merged["speaking_character_status"],
            personhood_evidence_summary=personhood_evidence_summary,
            evidence_level=merged["evidence_level"],
            personality=[ProfileAttributeItem(**item) for item in merged["personality"]],
            occupations=[ProfileAttributeItem(**item) for item in merged["occupations"]],
            age_timeline=[CharacterAgeItem(**item) for item in merged["age_timeline"]],
            abilities=[CharacterAbilityItem(**item) for item in merged["abilities"]],
            recent_activity=[ProfileAttributeItem(**item) for item in merged["recent_activity"]],
            relationships=[CharacterRelationshipItem(**item) for item in merged["relationships"]],
            story_events=[CharacterStoryEventItem(**item) for item in story_events],
            chapter_indexes=chapter_indexes,
        )
        profile_summary_md = self.profile_service._append_document_presence_summary(  # noqa: SLF001
            self.profile_service._build_summary(snapshot=snapshot),  # noqa: SLF001
            mentioned_doc_ids=mentioned_doc_ids,
            speaking_doc_ids=merged["speaking_doc_ids"],
        )
        return {
            "book_id": book_id,
            **snapshot.to_dict(),
            "story_events": story_events,
            "profile_summary_md": profile_summary_md,
            "mentioned_doc_ids": mentioned_doc_ids,
            "speaking_doc_ids": merged["speaking_doc_ids"],
            "first_seen_doc_id": self.profile_service._min_int(merged["first_seen_doc_id"], min(evidence.source_doc_ids) if evidence.source_doc_ids else None),  # noqa: SLF001
            "last_seen_doc_id": self.profile_service._max_int(merged["last_seen_doc_id"], max(evidence.source_doc_ids) if evidence.source_doc_ids else None),  # noqa: SLF001
            "first_seen_title_index": self.profile_service._min_int(merged["first_seen_title_index"], min(evidence.source_title_indexes) if evidence.source_title_indexes else None),  # noqa: SLF001
            "last_seen_title_index": self.profile_service._max_int(merged["last_seen_title_index"], max(evidence.source_title_indexes) if evidence.source_title_indexes else None),  # noqa: SLF001
            "importance_score": int(merged["importance_score"]),
            "profile_version": int(merged["profile_version"]) + 1,
            "created_at": merged["created_at"] or _utc_now(),
            "updated_at": _utc_now(),
        }

    def _identity_event(
        self,
        *,
        survivor_name: str,
        duplicate_name: str,
        survivor_id: int,
        duplicate_id: int,
        evidence: CharacterIdentityMergeEvidence,
    ) -> dict[str, Any]:
        source_key = ",".join(str(item) for item in evidence.source_doc_ids) or ",".join(evidence.outline_segment_ids)
        digest = hashlib.sha1(f"{survivor_id}:{duplicate_id}:{source_key}:{evidence.summary}".encode("utf-8")).hexdigest()[:10]
        outline_segment_id = evidence.outline_segment_ids[0] if evidence.outline_segment_ids else ""
        return {
            "event_id": f"identity-merge:{survivor_id}:{duplicate_id}:{digest}",
            "label": f"身份揭示：{duplicate_name} 与 {survivor_name} 为同一人物",
            "summary": evidence.summary,
            "outline_segment_id": outline_segment_id,
            "role_in_segment": "identity_reveal",
            "compression_level": "brief",
            "source_chapter_indexes": evidence.source_title_indexes,
            "source_doc_ids": evidence.source_doc_ids,
            "source_doc_range": self.profile_service._doc_range_text(evidence.source_doc_ids),  # noqa: SLF001
            "participants": self.profile_service._merge_aliases([], [survivor_name, duplicate_name], canonical_name=""),  # noqa: SLF001
        }

    def _rewrite_profile_references(
        self,
        conn,
        *,
        book_id: str,
        old_names: list[str],
        new_name: str,
        exclude_character_id: int,
    ) -> int:
        old_name_set = {name for name in self._name_list(old_names) if name != new_name}
        if not old_name_set:
            return 0
        changed = 0
        for row in self.profiles_repo.list_by_book(conn, book_id=book_id):
            if self._row_id(row) == exclude_character_id:
                continue
            relationships = self._load_json_list(row, "relationships_json")
            story_events = self._load_json_list(row, "story_events_json")
            did_change = False
            for relationship in relationships:
                if not isinstance(relationship, dict):
                    continue
                if str(relationship.get("target_name") or "").strip() in old_name_set:
                    relationship["target_name"] = new_name
                    did_change = True
            for event in story_events:
                if not isinstance(event, dict):
                    continue
                participants = self._name_list(event.get("participants"))
                if any(name in old_name_set for name in participants):
                    event["participants"] = self.profile_service._merge_aliases(  # noqa: SLF001
                        [],
                        [new_name if name in old_name_set else name for name in participants],
                        canonical_name="",
                    )
                    did_change = True
            if not did_change:
                continue
            conn.execute(
                """
                UPDATE character_profiles
                SET relationships_json = ?, story_events_json = ?, updated_at = ?
                WHERE book_id = ? AND character_id = ?
                """,
                (
                    json.dumps(relationships, ensure_ascii=False),
                    json.dumps(story_events, ensure_ascii=False),
                    _utc_now(),
                    book_id,
                    self._row_id(row),
                ),
            )
            changed += 1
        return changed

    def _invalid_evidence_reason(self, evidence: CharacterIdentityMergeEvidence) -> str:
        if evidence.decision_source not in self.VALID_DECISION_SOURCES:
            return "identity merge evidence source is not allowed"
        if evidence.confidence < self.min_confidence:
            return "identity merge confidence below threshold"
        if not str(evidence.summary or "").strip():
            return "identity merge evidence summary is empty"
        if not evidence.source_doc_ids and not evidence.outline_segment_ids:
            return "identity merge evidence lacks source refs"
        return ""

    def _existing_candidate_for_pair(
        self,
        conn,
        *,
        book_id: str,
        left_id: int,
        right_id: int,
        left_name: str,
        right_name: str,
    ) -> Any | None:
        rows = self._candidate_rows_for_pair(
            conn,
            book_id=book_id,
            left_id=left_id,
            right_id=right_id,
            left_name=left_name,
            right_name=right_name,
        )
        if not rows:
            return None
        rows.sort(
            key=lambda row: (
                0 if str(row["status"] or "") in self.TERMINAL_CANDIDATE_STATUSES else 1,
                str(row["updated_at"] or ""),
            ),
            reverse=False,
        )
        return rows[0]

    def _candidate_rows_for_pair(
        self,
        conn,
        *,
        book_id: str,
        left_id: int,
        right_id: int,
        left_name: str,
        right_name: str,
    ) -> list[Any]:
        left_id = self._safe_int(left_id)
        right_id = self._safe_int(right_id)
        names = self._name_list([left_name, right_name])
        clauses: list[str] = []
        args: list[Any] = [book_id]
        if left_id > 0 and right_id > 0:
            clauses.append(
                "((left_character_id = ? AND right_character_id = ?) OR (left_character_id = ? AND right_character_id = ?))"
            )
            args.extend([left_id, right_id, right_id, left_id])
        if len(names) >= 2:
            clauses.append("((left_name = ? AND right_name = ?) OR (left_name = ? AND right_name = ?))")
            args.extend([names[0], names[1], names[1], names[0]])
        if not clauses:
            return []
        return conn.execute(
            f"""
            SELECT *
            FROM character_identity_merge_candidates
            WHERE book_id = ? AND ({" OR ".join(clauses)})
            ORDER BY updated_at DESC
            """,
            args,
        ).fetchall()

    def _evidence_from_revelation(self, revelation: Mapping[str, Any]) -> CharacterIdentityMergeEvidence:
        return CharacterIdentityMergeEvidence(
            summary=str(revelation.get("evidence_summary") or revelation.get("summary") or "").strip(),
            source_doc_ids=self._int_list(revelation.get("source_doc_ids")),
            source_title_indexes=self._int_list(revelation.get("source_title_indexes")),
            outline_segment_ids=self._name_list(revelation.get("outline_segment_ids") or revelation.get("outline_segment_id")),
            confidence=self._float(revelation.get("confidence")),
            decision_source=str(revelation.get("decision_source") or "character_evidence").strip(),
        )

    def _same_person_revelation(self, revelation: Mapping[str, Any]) -> bool:
        relation = str(revelation.get("relation") or revelation.get("identity_relation") or "").strip().lower()
        status = str(revelation.get("resolution_status") or revelation.get("status") or "").strip().lower()
        return relation in {"same_person", "same_identity", "identity_reveal"} or status in {
            "confirmed_identity_reveal",
            "same_person",
        }

    def _choose_survivor(self, left: Any, right: Any, *, preferred_name: object = "") -> Any:
        preferred = str(preferred_name or "").strip()
        if preferred:
            if preferred == self._row_name(left):
                return left
            if preferred == self._row_name(right):
                return right
        return min(
            [left, right],
            key=lambda row: (
                self.profile_service._safe_int(row["first_seen_doc_id"]) or 10**9,  # noqa: SLF001
                self._row_id(row),
            ),
        )

    def _resolve_profile(
        self,
        conn,
        *,
        book_id: str,
        character_id: object = None,
        canonical_name: object = "",
    ) -> Any | None:
        try:
            normalized_id = int(character_id or 0)
        except (TypeError, ValueError):
            normalized_id = 0
        if normalized_id > 0:
            row = self.profiles_repo.get_by_id(conn, book_id=book_id, character_id=normalized_id)
            if row is not None:
                return row
        name = str(canonical_name or "").strip()
        if not name:
            return None
        exact = self.profiles_repo.get(conn, book_id=book_id, canonical_name=name)
        if exact is not None:
            return exact
        for row in self.profiles_repo.list_by_book(conn, book_id=book_id):
            aliases = {str(item).strip() for item in self._load_json_list(row, "aliases_json")}
            if name in aliases:
                return row
        return None

    def _profile_review_summary(self, row: Any) -> dict[str, Any]:
        return {
            "character_id": str(row["character_id"]),
            "canonical_name": self._row_name(row),
            "aliases": self._load_json_list(row, "aliases_json")[:12],
            "personhood_evidence_summary": str(row["personhood_evidence_summary"] or "")[:800],
            "profile_summary_md": str(row["profile_summary_md"] or "")[:1200],
            "first_seen_doc_id": row["first_seen_doc_id"],
            "last_seen_doc_id": row["last_seen_doc_id"],
        }

    def _latest_title_index(self, merged: Mapping[str, Any], evidence: CharacterIdentityMergeEvidence) -> int:
        candidates = [
            *(evidence.source_title_indexes or []),
            *(merged.get("chapter_indexes") or []),
        ]
        values = [value for value in (self.profile_service._safe_int(item) for item in candidates) if value is not None]  # noqa: SLF001
        return max(values) if values else 0

    def _load_json_list(self, row: Any, field_name: str) -> list[Any]:
        raw = row[field_name]
        if not raw:
            return []
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []

    def _load_json_dict(self, row: Any, field_name: str) -> dict[str, Any]:
        raw = row[field_name]
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _name_list(self, values: object) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, list):
            values = [values]
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    def _int_list(self, values: object) -> list[int]:
        result: list[int] = []
        for value in self._name_list(values):
            try:
                item = int(value)
            except (TypeError, ValueError):
                continue
            if item not in result:
                result.append(item)
        return result

    @staticmethod
    def _row_id(row: Any) -> int:
        try:
            return int(row["character_id"])
        except (KeyError, TypeError, ValueError):
            return 0

    @staticmethod
    def _row_name(row: Any) -> str:
        return str(row["canonical_name"] or "").strip()

    @staticmethod
    def _float(value: object) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _score(value: object) -> int:
        try:
            score = int(round(float(value or 0)))
        except (TypeError, ValueError):
            score = 0
        return max(0, min(100, score))

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _candidate_id(
        self,
        *,
        book_id: str,
        left_id: int,
        right_id: int,
        left_name: str,
        right_name: str,
        evidence: CharacterIdentityMergeEvidence,
    ) -> str:
        ordered_ids = sorted([left_id, right_id])
        ordered_names = sorted(self._name_list([left_name, right_name]))
        digest = hashlib.sha1(f"{book_id}:{ordered_ids}:{ordered_names}".encode("utf-8")).hexdigest()[:16]
        return f"identity-merge-candidate:{digest}"
