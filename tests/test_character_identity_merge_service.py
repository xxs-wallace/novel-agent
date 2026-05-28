from __future__ import annotations

import json
from types import SimpleNamespace

from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.services.character_identity_merge_service import (
    CharacterIdentityMergeEvidence,
    CharacterIdentityMergeService,
)


def _profile_payload(
    *,
    book_id: str,
    canonical_name: str,
    aliases: list[str] | None = None,
    relationships: list[dict[str, object]] | None = None,
    story_events: list[dict[str, object]] | None = None,
    first_seen_doc_id: int = 1,
    last_seen_doc_id: int = 1,
) -> dict[str, object]:
    return {
        "book_id": book_id,
        "canonical_name": canonical_name,
        "aliases": aliases or [],
        "profile_summary_md": f"# {canonical_name}\n",
        "speaking_character_status": "confirmed_speaking",
        "personhood_evidence_summary": f"{canonical_name} 有明确人物性证据。",
        "evidence_level": "explicit",
        "personality": [],
        "occupations": [],
        "age_timeline": [],
        "abilities": [],
        "recent_activity": [],
        "relationships": relationships or [],
        "story_events": story_events or [],
        "chapter_indexes": [first_seen_doc_id],
        "mentioned_doc_ids": [first_seen_doc_id, last_seen_doc_id],
        "speaking_doc_ids": [first_seen_doc_id],
        "first_seen_doc_id": first_seen_doc_id,
        "last_seen_doc_id": last_seen_doc_id,
        "first_seen_title_index": first_seen_doc_id,
        "last_seen_title_index": last_seen_doc_id,
        "importance_score": 0,
        "profile_version": 1,
        "created_at": "now",
        "updated_at": "now",
    }


def _json(row, field_name: str) -> list[object]:
    return list(json.loads(row[field_name] or "[]"))


def test_identity_merge_service_merges_confirmed_profiles_and_rewrites_relationship_targets(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "identity_merge.db")
    repo = CharacterProfilesRepo()
    service = CharacterIdentityMergeService(profiles_repo=repo)

    with db.connect() as conn:
        db.init_schema(conn)
        old_id = repo.upsert(
            conn,
            _profile_payload(
                book_id="book-1",
                canonical_name="老唐",
                aliases=["Ronald"],
                story_events=[
                    {
                        "event_id": "old-tang-chat",
                        "label": "老唐与主角聊天",
                        "summary": "老唐以网友身份出现。",
                        "source_chapter_indexes": [2],
                        "source_doc_ids": [2],
                    }
                ],
                first_seen_doc_id=2,
                last_seen_doc_id=10,
            ),
        )
        norton_id = repo.upsert(
            conn,
            _profile_payload(
                book_id="book-1",
                canonical_name="诺顿",
                aliases=["龙王诺顿"],
                story_events=[
                    {
                        "event_id": "norton-reveal",
                        "label": "诺顿身份浮现",
                        "summary": "诺顿作为龙王身份被揭示。",
                        "source_chapter_indexes": [20],
                        "source_doc_ids": [58],
                    }
                ],
                first_seen_doc_id=58,
                last_seen_doc_id=60,
            ),
        )
        repo.upsert(
            conn,
            _profile_payload(
                book_id="book-1",
                canonical_name="康斯坦丁",
                relationships=[
                    {
                        "target_name": "诺顿",
                        "relation_type": "兄弟",
                        "sentiment_state": "依恋",
                        "status_summary": "康斯坦丁寻找诺顿。",
                        "field_type": "fact",
                        "evidence_level": "explicit",
                        "address_terms": [],
                        "source_chapter_indexes": [20],
                        "source_doc_ids": [58],
                        "last_updated_chapter_index": 20,
                    }
                ],
                first_seen_doc_id=1,
                last_seen_doc_id=58,
            ),
        )

        result = service.merge_confirmed_profiles(
            conn,
            book_id="book-1",
            survivor_character_id=old_id,
            duplicate_character_id=norton_id,
            aliases_to_keep=["诺顿"],
            evidence=CharacterIdentityMergeEvidence(
                summary="文本明确揭示老唐就是诺顿。",
                source_doc_ids=[60],
                source_title_indexes=[20],
                outline_segment_ids=["outline-segment:chapter-20:docs-58-60"],
                confidence=0.97,
                decision_source="model_identity_reveal",
            ),
        )
        conn.commit()

        rows = repo.list_by_book(conn, book_id="book-1")
        names = [str(row["canonical_name"]) for row in rows]
        survivor = repo.get(conn, book_id="book-1", canonical_name="老唐")
        constantine = repo.get(conn, book_id="book-1", canonical_name="康斯坦丁")

    assert result.merged is True
    assert "诺顿" not in names
    assert survivor is not None
    assert int(survivor["character_id"]) == old_id
    assert _json(survivor, "aliases_json") == ["Ronald", "诺顿", "龙王诺顿"]
    story_events = _json(survivor, "story_events_json")
    assert any(str(item.get("event_id", "")).startswith("identity-merge:") for item in story_events if isinstance(item, dict))
    assert constantine is not None
    relationships = _json(constantine, "relationships_json")
    assert relationships[0]["target_name"] == "老唐"


def test_identity_merge_service_refuses_low_confidence_or_unsourced_evidence(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "identity_merge_refuse.db")
    repo = CharacterProfilesRepo()
    service = CharacterIdentityMergeService(profiles_repo=repo)

    with db.connect() as conn:
        db.init_schema(conn)
        left_id = repo.upsert(conn, _profile_payload(book_id="book-1", canonical_name="甲"))
        right_id = repo.upsert(conn, _profile_payload(book_id="book-1", canonical_name="乙"))

        result = service.merge_confirmed_profiles(
            conn,
            book_id="book-1",
            survivor_character_id=left_id,
            duplicate_character_id=right_id,
            evidence=CharacterIdentityMergeEvidence(
                summary="只是疑似同一人。",
                source_doc_ids=[],
                confidence=0.72,
                decision_source="model_identity_reveal",
            ),
        )
        rows = repo.list_by_book(conn, book_id="book-1")

    assert result.merged is False
    assert [str(row["canonical_name"]) for row in rows] == ["乙", "甲"]


def test_identity_merge_review_prompt_requires_explicit_merge_evidence(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "identity_merge_review.db")
    repo = CharacterProfilesRepo()
    service = CharacterIdentityMergeService(profiles_repo=repo)

    class _FakeModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = fallback_factory, use_fallback_on_error
            assert "Character Identity Merge Review Agent" in system_prompt
            assert "明确揭示" in system_prompt
            assert "identity_reveal_evidence" in user_prompt
            return (
                {
                    "recommended_action": "merge_profiles",
                    "same_person_score": 96,
                    "survivor_canonical_name": "老唐",
                    "aliases_to_keep": ["诺顿"],
                    "evidence_summary": "当前证据明确揭示二者为同一人物。",
                    "evidence_strengths": ["明确身份揭示"],
                    "evidence_gaps": [],
                    "reason": "当前证据明确揭示同一人物。",
                    "confidence": 0.96,
                    "requires_user_confirmation": True,
                },
                "",
            )

    with db.connect() as conn:
        db.init_schema(conn)
        repo.upsert(conn, _profile_payload(book_id="book-1", canonical_name="老唐"))
        repo.upsert(conn, _profile_payload(book_id="book-1", canonical_name="诺顿"))
        decision = service.review_candidate(
            conn,
            book_id="book-1",
            model_client=_FakeModel(),  # type: ignore[arg-type]
            left_name="老唐",
            right_name="诺顿",
            evidence=CharacterIdentityMergeEvidence(
                summary="文本明确揭示二者同一。",
                source_doc_ids=[60],
                confidence=0.96,
            ),
        )

    assert decision["recommended_action"] == "merge_profiles"
    assert decision["same_person_score"] == 96


def test_identity_merge_review_revelations_persists_high_score_candidate_without_merging(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "identity_merge_candidate.db")
    repo = CharacterProfilesRepo()
    service = CharacterIdentityMergeService(profiles_repo=repo)

    class _FakeModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = system_prompt, user_prompt, fallback_factory, use_fallback_on_error
            return (
                {
                    "recommended_action": "merge_profiles",
                    "same_person_score": 93,
                    "confidence": 0.94,
                    "survivor_canonical_name": "老唐",
                    "aliases_to_keep": ["诺顿"],
                    "evidence_summary": "文本明确揭示二者同一。",
                    "evidence_strengths": ["同一人物揭示"],
                    "evidence_gaps": [],
                    "reason": "证据足够进入人工确认。",
                    "requires_user_confirmation": True,
                },
                "",
            )

    with db.connect() as conn:
        db.init_schema(conn)
        repo.upsert(conn, _profile_payload(book_id="book-1", canonical_name="老唐"))
        repo.upsert(conn, _profile_payload(book_id="book-1", canonical_name="诺顿"))

        results = service.review_revelations(
            conn,
            book_id="book-1",
            model_client=_FakeModel(),  # type: ignore[arg-type]
            revelations=[
                {
                    "relation": "same_person",
                    "left_name": "老唐",
                    "right_name": "诺顿",
                    "evidence_summary": "文本明确揭示二者同一。",
                    "source_doc_ids": [60],
                    "source_title_indexes": [20],
                    "confidence": 0.96,
                }
            ],
        )
        conn.commit()
        candidates = conn.execute("SELECT * FROM character_identity_merge_candidates").fetchall()
        names = [str(row["canonical_name"]) for row in repo.list_by_book(conn, book_id="book-1")]

    assert len(results) == 1
    assert results[0].blocks_close_read is True
    assert results[0].same_person_score == 93
    assert len(candidates) == 1
    assert candidates[0]["status"] == "pending_user_confirmation"
    assert sorted(names) == ["老唐", "诺顿"]


def test_identity_merge_review_revelations_skips_low_score_candidate(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "identity_merge_low_score.db")
    repo = CharacterProfilesRepo()
    service = CharacterIdentityMergeService(profiles_repo=repo)

    class _FakeModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = system_prompt, user_prompt, fallback_factory, use_fallback_on_error
            return (
                {
                    "recommended_action": "keep_separate",
                    "same_person_score": 30,
                    "confidence": 0.8,
                    "survivor_canonical_name": "",
                    "aliases_to_keep": [],
                    "evidence_summary": "只有共现。",
                    "evidence_strengths": [],
                    "evidence_gaps": ["缺少身份揭示"],
                    "reason": "证据不足。",
                    "requires_user_confirmation": False,
                },
                "",
            )

    with db.connect() as conn:
        db.init_schema(conn)
        repo.upsert(conn, _profile_payload(book_id="book-1", canonical_name="甲"))
        repo.upsert(conn, _profile_payload(book_id="book-1", canonical_name="乙"))
        results = service.review_revelations(
            conn,
            book_id="book-1",
            model_client=_FakeModel(),  # type: ignore[arg-type]
            revelations=[
                {
                    "relation": "same_person",
                    "left_name": "甲",
                    "right_name": "乙",
                    "evidence_summary": "疑似相似。",
                    "source_doc_ids": [2],
                    "confidence": 0.95,
                }
            ],
        )
        candidates = conn.execute("SELECT * FROM character_identity_merge_candidates").fetchall()

    assert len(results) == 1
    assert results[0].status == "skipped"
    assert results[0].blocks_close_read is False
    assert candidates == []
