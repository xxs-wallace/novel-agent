from __future__ import annotations

import json
from types import SimpleNamespace

from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.services.character_memory_correction_service import CharacterMemoryCorrectionService


def _profile_payload(
    *,
    book_id: str,
    canonical_name: str,
    aliases: list[str] | None = None,
    relationships: list[dict[str, object]] | None = None,
    story_events: list[dict[str, object]] | None = None,
    mentioned_doc_ids: list[int] | None = None,
    speaking_doc_ids: list[int] | None = None,
) -> dict[str, object]:
    mentioned = mentioned_doc_ids or [1]
    return {
        "book_id": book_id,
        "canonical_name": canonical_name,
        "aliases": aliases or [],
        "profile_summary_md": f"# {canonical_name}\n",
        "speaking_character_status": "confirmed_speaking" if speaking_doc_ids else "unknown",
        "personhood_evidence_summary": f"{canonical_name} 有人物性证据。",
        "evidence_level": "explicit",
        "personality": [],
        "occupations": [],
        "age_timeline": [],
        "abilities": [],
        "recent_activity": [],
        "relationships": relationships or [],
        "story_events": story_events or [],
        "chapter_indexes": [1],
        "mentioned_doc_ids": mentioned,
        "speaking_doc_ids": speaking_doc_ids or [],
        "first_seen_doc_id": min(mentioned),
        "last_seen_doc_id": max(mentioned),
        "first_seen_title_index": 1,
        "last_seen_title_index": 1,
        "importance_score": 0,
        "profile_version": 1,
        "created_at": "now",
        "updated_at": "now",
    }


def _json(row, field_name: str) -> list[object]:
    return list(json.loads(row[field_name] or "[]"))


def test_memory_correction_moves_misattributed_events_and_removes_bad_aliases(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "memory_correction.db")
    repo = CharacterProfilesRepo()
    service = CharacterMemoryCorrectionService(profiles_repo=repo)

    with db.connect() as conn:
        db.init_schema(conn)
        repo.upsert(
            conn,
            _profile_payload(
                book_id="book-1",
                canonical_name="路明非",
                aliases=["明非", "老唐", "诺顿"],
                mentioned_doc_ids=[1, 2, 40, 41],
                speaking_doc_ids=[1, 2, 40],
                story_events=[
                    {
                        "event_id": "lmf-school",
                        "label": "路明非入学",
                        "summary": "路明非进入学院。",
                        "outline_segment_id": "outline-segment:chapter-4:docs-7-8",
                        "role_in_segment": "main_driver",
                        "compression_level": "brief",
                        "source_chapter_indexes": [4],
                        "source_doc_ids": [7, 8],
                        "participants": ["路明非"],
                    },
                    {
                        "event_id": "wrong-norton-reveal",
                        "label": "诺顿身份揭示",
                        "summary": "误写在路明非档案里的诺顿相关经历。",
                        "outline_segment_id": "outline-segment:chapter-20:docs-40-41",
                        "role_in_segment": "main_driver",
                        "compression_level": "full",
                        "source_chapter_indexes": [20],
                        "source_doc_ids": [40, 41],
                        "participants": ["路明非", "诺顿"],
                    },
                ],
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
                        "source_doc_ids": [41],
                        "last_updated_chapter_index": 20,
                    }
                ],
                mentioned_doc_ids=[39, 40, 41],
            ),
        )

        result = service.apply_plan(
            conn,
            book_id="book-1",
            plan={
                "status": "approved",
                "correction_type": "false_attribution",
                "reason": "后文明确揭示诺顿相关经历不属于路明非。",
                "confidence": 0.96,
                "source_doc_ids": [41],
                "source_title_indexes": [20],
                "outline_segment_ids": ["outline-segment:chapter-20:docs-40-41"],
                "operations": [
                    {
                        "op": "remove_aliases",
                        "canonical_name": "路明非",
                        "aliases": ["老唐", "诺顿"],
                    },
                    {
                        "op": "move_story_events",
                        "canonical_name": "路明非",
                        "target_canonical_name": "老唐",
                        "aliases": ["诺顿"],
                        "outline_segment_ids": ["outline-segment:chapter-20:docs-40-41"],
                        "misattributed_names": ["路明非", "诺顿"],
                        "remove_source_doc_refs": True,
                    },
                    {
                        "op": "rewrite_relationship_target",
                        "old_names": ["诺顿"],
                        "new_name": "老唐",
                    },
                ],
            },
        )
        conn.commit()

        polluted = repo.get(conn, book_id="book-1", canonical_name="路明非")
        target = repo.get(conn, book_id="book-1", canonical_name="老唐")
        constantine = repo.get(conn, book_id="book-1", canonical_name="康斯坦丁")

    assert result.applied is True
    assert result.operations_applied == 3
    assert result.created_canonical_names == ["老唐"]
    assert polluted is not None
    assert _json(polluted, "aliases_json") == ["明非"]
    polluted_events = _json(polluted, "story_events_json")
    assert [event["event_id"] for event in polluted_events if isinstance(event, dict)] == ["lmf-school"]
    assert _json(polluted, "mentioned_doc_ids_json") == [1, 2]
    assert _json(polluted, "speaking_doc_ids_json") == [1, 2]
    assert target is not None
    assert _json(target, "aliases_json") == ["诺顿"]
    target_events = _json(target, "story_events_json")
    assert target_events[0]["event_id"] == "wrong-norton-reveal"
    assert target_events[0]["participants"] == ["老唐"]
    assert _json(target, "mentioned_doc_ids_json") == [40, 41]
    assert constantine is not None
    assert _json(constantine, "relationships_json")[0]["target_name"] == "老唐"


def test_memory_correction_rejects_unapproved_or_unsourced_plan(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "memory_correction_reject.db")
    service = CharacterMemoryCorrectionService(profiles_repo=CharacterProfilesRepo())

    with db.connect() as conn:
        db.init_schema(conn)
        result = service.apply_plan(
            conn,
            book_id="book-1",
            plan={
                "status": "approved",
                "correction_type": "false_attribution",
                "reason": "缺少回源。",
                "confidence": 0.99,
                "operations": [{"op": "remove_aliases", "canonical_name": "甲", "aliases": ["乙"]}],
            },
        )

    assert result.applied is False
    assert result.reason == "correction plan lacks source refs"


def test_memory_correction_review_prompt_returns_plan(tmp_path) -> None:
    service = CharacterMemoryCorrectionService(profiles_repo=CharacterProfilesRepo())

    class _FakeModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = fallback_factory, use_fallback_on_error
            assert "Character Memory Correction Review Agent" in system_prompt
            assert "候选修正" in system_prompt
            assert "输入数据如下" in user_prompt
            return (
                {
                    "status": "approved",
                    "correction_type": "false_attribution",
                    "reason": "证据明确支持修正。",
                    "confidence": 0.95,
                    "source_doc_ids": [10],
                    "source_title_indexes": [3],
                    "outline_segment_ids": [],
                    "operations": [{"op": "remove_aliases", "canonical_name": "甲", "aliases": ["乙"]}],
                },
                "",
            )

    plan = service.review_candidate(
        model_client=_FakeModel(),  # type: ignore[arg-type]
        prompt_input={"candidate_correction": {"summary": "甲的乙别名是误归因。"}},
    )

    assert plan["status"] == "approved"
    assert plan["operations"][0]["op"] == "remove_aliases"


def test_memory_correction_seed_prompt_routes_to_small_document_set() -> None:
    service = CharacterMemoryCorrectionService(profiles_repo=CharacterProfilesRepo())

    class _FakeModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = fallback_factory, use_fallback_on_error
            assert "Character Memory Correction Seed Agent" in system_prompt
            assert "不重读整本小说" in system_prompt
            assert "outline_root.summary" in system_prompt
            assert "输入数据如下" in user_prompt
            return (
                {
                    "next_action": "inspect_documents",
                    "selected_outline_root_ids": ["root-1"],
                    "selected_outline_segment_ids": [
                        "seg-1",
                        "seg-2",
                        "seg-3",
                        "seg-4",
                        "seg-5",
                        "seg-6",
                        "seg-7",
                    ],
                    "selected_doc_ids": [40, 41, 42, 43, 44, 45, 46, 47, 48],
                    "search_focus": "确认身份揭示是否推翻旧档案归属。",
                    "candidate_correction": {
                        "correction_type": "false_attribution",
                        "polluted_character": "路明非",
                        "target_character": "老唐",
                        "suspected_wrong_aliases": ["诺顿"],
                        "suspected_event_selectors": ["seg-2"],
                        "reason": "索引显示该身份揭示集中在少量 segment。",
                    },
                    "reason": "先展开最相关 docs。",
                    "confidence": 0.88,
                },
                "",
            )

    step = service.seed_next_step(
        model_client=_FakeModel(),  # type: ignore[arg-type]
        prompt_input={
            "suspected_pollution": {"polluted_character": "路明非", "wrong_aliases": ["老唐", "诺顿"]},
            "outline_roots": [{"outline_root_id": "root-1", "summary": "龙王身份揭示。"}],
        },
    )

    assert step["next_action"] == "inspect_documents"
    assert step["selected_outline_segment_ids"] == ["seg-1", "seg-2", "seg-3", "seg-4", "seg-5", "seg-6"]
    assert step["selected_doc_ids"] == [40, 41, 42, 43, 44, 45, 46, 47]
