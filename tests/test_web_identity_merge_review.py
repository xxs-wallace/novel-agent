from __future__ import annotations

import asyncio
import json

from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.web.schemas import WebActionRequest
from novel_agent.app.web.services.artifact_view_service import ArtifactViewService
from novel_agent.app.web.services.job_manager import JobManager
from novel_agent.app.web.services.web_action_service import WebActionService
from novel_agent.app.web.services.web_session_service import WebSessionService


def _profile_payload(*, book_id: str, canonical_name: str, first_doc_id: int) -> dict[str, object]:
    return {
        "book_id": book_id,
        "canonical_name": canonical_name,
        "aliases": [],
        "profile_summary_md": f"# {canonical_name}\n",
        "speaking_character_status": "confirmed_speaking",
        "personhood_evidence_summary": f"{canonical_name} 有明确人物性证据。",
        "evidence_level": "explicit",
        "personality": [],
        "occupations": [],
        "age_timeline": [],
        "abilities": [],
        "recent_activity": [],
        "relationships": [],
        "story_events": [
            {
                "event_id": f"{canonical_name}-event",
                "label": f"{canonical_name} 出场",
                "summary": f"{canonical_name} 有独立经历。",
                "source_chapter_indexes": [first_doc_id],
                "source_doc_ids": [first_doc_id],
            }
        ],
        "chapter_indexes": [first_doc_id],
        "mentioned_doc_ids": [first_doc_id],
        "speaking_doc_ids": [first_doc_id],
        "first_seen_doc_id": first_doc_id,
        "last_seen_doc_id": first_doc_id,
        "first_seen_title_index": first_doc_id,
        "last_seen_title_index": first_doc_id,
        "importance_score": 0,
        "profile_version": 1,
        "created_at": "now",
        "updated_at": "now",
    }


def _prepare_identity_candidate(repo_root, *, book_id: str = "book-1") -> tuple[WebSessionService, WebActionService, str]:
    session = WebSessionService(repo_root=repo_root)
    session.facade.ensure_task(book_id=book_id, source_path="")
    db_path = session.facade.db_path_for_book(book_id)
    db = NovelAgentDB(db_path)
    candidate_id = "identity-merge-candidate:test"
    with db.connect() as conn:
        db.init_schema(conn)
        repo = CharacterProfilesRepo()
        left_id = repo.upsert(conn, _profile_payload(book_id=book_id, canonical_name="甲", first_doc_id=1))
        right_id = repo.upsert(conn, _profile_payload(book_id=book_id, canonical_name="乙", first_doc_id=2))
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
            """,
            (
                candidate_id,
                book_id,
                "pending_user_confirmation",
                "high",
                "merge_profiles",
                94,
                0.95,
                "证据足够进入人工确认。",
                "文本明确揭示甲与乙为同一人物。",
                left_id,
                "甲",
                right_id,
                "乙",
                "甲",
                json.dumps(["乙"], ensure_ascii=False),
                json.dumps([3], ensure_ascii=False),
                json.dumps([3], ensure_ascii=False),
                json.dumps(["outline-segment:test"], ensure_ascii=False),
                json.dumps({"same_person_score": 94}, ensure_ascii=False),
                "now",
                "now",
                "",
            ),
        )
        conn.execute(
            """
            INSERT INTO reading_progress(
                book_id, agent_stage, current_doc_id, current_document_title_index,
                current_source_path, current_source_offset, last_completed_doc_id,
                last_completed_title_index, last_completed_chapter_id, status_json,
                checkpoint_token, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                "close_reading",
                3,
                3,
                "",
                0,
                2,
                2,
                None,
                json.dumps(
                    {
                        "state": "blocked_identity_merge_review",
                        "candidate_ids": [candidate_id],
                    },
                    ensure_ascii=False,
                ),
                "3:3:identity_merge_review",
                "now",
            ),
        )
        conn.commit()
    action_service = WebActionService(
        session_service=session,
        job_manager=JobManager(repo_root=repo_root),
        artifact_view_service=ArtifactViewService(repo_root=repo_root, facade=session.facade),
    )
    return session, action_service, candidate_id


def test_web_session_exposes_identity_merge_confirmation_card(tmp_path) -> None:
    session, _action_service, candidate_id = _prepare_identity_candidate(tmp_path)

    messages = session.messages("book-1")
    cards = [card for message in messages for card in message.decision_cards]

    assert any("甲 / 乙" in message.content and "合并为「甲」" in message.content for message in messages)
    assert any(card.card_id.endswith(candidate_id) for card in cards)
    assert any(card.title == "待确认人物身份合并：甲 / 乙" for card in cards)
    assert any("候选：甲 / 乙" in card.body and "建议保留档案：甲" in card.body for card in cards)
    assert {action["action"] for card in cards for action in card.actions} >= {
        "confirm_identity_merge",
        "reject_identity_merge",
        "request_identity_merge_more_evidence",
        "route_identity_merge_to_correction",
    }
    assert any(action["label"] == "确认合并为甲" for card in cards for action in card.actions)
    progress = session.task_progress("book-1")
    assert progress.step == "确认人物身份合并候选"


def test_web_session_refreshes_stale_identity_merge_message_with_candidate_names(tmp_path) -> None:
    session, _action_service, candidate_id = _prepare_identity_candidate(tmp_path)
    session.append_message(
        "book-1",
        role="assistant",
        content="阅读已暂停：发现高置信人物身份候选，需要你确认后再继续。",
        payload={"channel": "identity_merge_review", "candidate_id": candidate_id},
    )

    messages = session.messages("book-1")
    identity_messages = [
        message
        for message in messages
        if message.payload.get("channel") == "identity_merge_review" and message.payload.get("candidate_id") == candidate_id
    ]

    assert len(identity_messages) == 1
    assert "甲 / 乙" in identity_messages[0].content
    assert identity_messages[0].decision_cards[0].title == "待确认人物身份合并：甲 / 乙"


def test_web_confirm_identity_merge_action_merges_profiles_and_resolves_block(tmp_path) -> None:
    session, action_service, candidate_id = _prepare_identity_candidate(tmp_path)

    result = asyncio.run(
        action_service.execute(
            task_id="book-1",
            request=WebActionRequest(action="confirm_identity_merge", payload={"candidate_id": candidate_id}),
        )
    )

    assert result.status == "ok"
    assert "甲 / 乙" in result.message
    assert "保留为「甲」" in result.message
    db = NovelAgentDB(session.facade.db_path_for_book("book-1"))
    with db.connect() as conn:
        db.init_schema(conn)
        rows = conn.execute("SELECT canonical_name FROM character_profiles WHERE book_id = ? ORDER BY canonical_name", ("book-1",)).fetchall()
        candidate = conn.execute("SELECT status FROM character_identity_merge_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        progress = conn.execute("SELECT status_json FROM reading_progress WHERE book_id = ? AND agent_stage = ?", ("book-1", "close_reading")).fetchone()

    assert [row["canonical_name"] for row in rows] == ["甲"]
    assert candidate["status"] == "merged"
    assert json.loads(progress["status_json"])["state"] == "identity_merge_review_resolved"
