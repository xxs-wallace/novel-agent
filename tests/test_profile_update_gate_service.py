from __future__ import annotations

from novel_agent.app.services.profile_update_gate_service import CharacterImportanceTracker, ProfileUpdateGateService


def test_profile_update_gate_combines_current_segment_and_rolling_history() -> None:
    service = ProfileUpdateGateService(
        tracker=CharacterImportanceTracker(
            detailed_min_doc_count=2,
            detailed_min_total_chars=1000,
        )
    )
    current_gates = service.gates_for_evidence(
        evidence_payload={
            "character_evidence_batches": [
                {
                    "doc_ids": [21],
                    "characters": [
                        {
                            "character_id": "7",
                            "canonical_name": "核心角色",
                            "is_speaking_character": True,
                            "speaking_evidence": "核心角色说出判断。",
                            "candidate_type": "character",
                            "confidence": 0.92,
                        }
                    ],
                }
            ]
        },
        current_total_chars=5000,
    )
    gate = service.gate_for_profile(
        {
            "character_id": "7",
            "canonical_name": "核心角色",
            "aliases": [],
            "mentioned_doc_ids": list(range(1, 20)),
            "speaking_doc_ids": [1, 2, 3, 4, 5],
            "story_events": [
                {"role_in_segment": "main_driver", "source_doc_ids": [doc_id]}
                for doc_id in range(1, 8)
            ],
            "last_seen_doc_id": 19,
            "importance_score": 5,
        },
        profile_gates=current_gates,
    )

    assert current_gates["id:7"]["detail_level"] == "compact"
    assert gate["detail_level"] == "detailed"
    assert gate["update_policy"] == "reduce_now"
    assert gate["reason"] == "rolling_core_character_with_current_direct_signal"
    assert gate["rolling_importance"]["rolling_tier"] == "high"


def test_profile_update_gate_marks_stale_low_importance_profile_for_index_only_compaction() -> None:
    service = ProfileUpdateGateService(
        tracker=CharacterImportanceTracker(stale_after_docs=4, cold_after_docs=8)
    )

    gate = service.gate_for_profile(
        {
            "character_id": "9",
            "canonical_name": "过场角色",
            "aliases": [],
            "mentioned_doc_ids": [1],
            "speaking_doc_ids": [],
            "story_events": [],
            "last_seen_doc_id": 1,
            "importance_score": 0,
        },
        profile_gates={
            "id:9": {
                "detail_level": "index_only",
                "update_policy": "defer_index_only",
                "reason": "low_frequency_or_background_role",
                "current_doc_count": 1,
                "current_total_docs": 1,
                "speaking_doc_count": 0,
                "action_doc_count": 0,
                "relationship_doc_count": 0,
                "source_doc_ids": [20],
                "source_title_indexes": [20],
            }
        },
    )

    assert gate["detail_level"] == "index_only"
    assert gate["update_policy"] == "defer_index_only"
    assert gate["state_transition"] == "compact_recent_to_older_and_cool_down"
    assert gate["rolling_importance"]["inactive_doc_gap"] == 19
