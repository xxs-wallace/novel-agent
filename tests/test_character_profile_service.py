from __future__ import annotations

import json
import sqlite3

from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.schemas.character_profile_schema import (
    CharacterAbilityItem,
    CharacterAgeItem,
    CharacterProfileSnapshot,
    CharacterRelationshipItem,
    ProfileAttributeItem,
)
from novel_agent.app.services.character_profile_service import CharacterProfileService


def _load_json(row: sqlite3.Row, field_name: str) -> list[object]:
    return list(json.loads(row[field_name]))


def _build_service() -> CharacterProfileService:
    return CharacterProfileService(profiles_repo=CharacterProfilesRepo())


def _fetch_profile_row(conn: sqlite3.Connection, *, book_id: str, canonical_name: str) -> sqlite3.Row:
    row = CharacterProfilesRepo().get(conn, book_id=book_id, canonical_name=canonical_name)
    assert row is not None
    return row


def test_character_profile_snapshot_to_dict_contains_evidence_contract() -> None:
    snapshot = CharacterProfileSnapshot(
        canonical_name="路明非",
        aliases=["明非"],
        profile_summary_md="# 路明非\n",
        personality=[
            ProfileAttributeItem(
                value="敏感克制",
                field_type="inference",
                evidence_level="inferred",
                source_chapter_indexes=[3],
                source_doc_ids=[11],
            )
        ],
        occupations=[
            ProfileAttributeItem(
                value="学生",
                field_type="fact",
                evidence_level="explicit",
                source_chapter_indexes=[3],
                source_doc_ids=[11],
            )
        ],
        age_timeline=[
            CharacterAgeItem(
                label="高中阶段",
                chapter_range="3-4",
                reason="处于入学前后阶段",
                field_type="inference",
                evidence_level="inferred",
                source_chapter_indexes=[4],
                source_doc_ids=[12],
            )
        ],
        abilities=[
            CharacterAbilityItem(
                type="血统",
                name="言灵",
                summary="首次明确表现出特殊能力",
                field_type="fact",
                evidence_level="explicit",
                source_chapter_indexes=[5],
                source_doc_ids=[13],
            )
        ],
        recent_activity=[
            ProfileAttributeItem(
                value="在雨夜赶往医院",
                field_type="fact",
                evidence_level="explicit",
                source_chapter_indexes=[5],
                source_doc_ids=[13],
            )
        ],
        relationships=[
            CharacterRelationshipItem(
                target_name="楚子航",
                relation_type="同学",
                sentiment_state="疏离",
                status_summary="两人暂时保持距离",
                field_type="fact",
                evidence_level="explicit",
                source_chapter_indexes=[5],
                source_doc_ids=[13],
                last_updated_chapter_index=5,
            )
        ],
        chapter_indexes=[3, 4, 5],
    )

    payload = snapshot.to_dict()

    assert payload["personality"][0]["field_type"] == "inference"
    assert payload["personality"][0]["evidence_level"] == "inferred"
    assert payload["occupations"][0]["field_type"] == "fact"
    assert payload["abilities"][0]["evidence_level"] == "explicit"
    assert payload["relationships"][0]["last_updated_chapter_index"] == 5


def test_merge_updates_normalizes_aliases_and_promotes_canonical_name(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "character_profiles.db")
    service = _build_service()

    with db.connect() as conn:
        db.init_schema(conn)
        service.merge_updates(
            conn,
            book_id="book-1",
            chapter_index=1,
            doc_ids=[1],
            updates=[
                {
                    "canonical_name": "明非",
                    "aliases": [],
                    "occupations": ["学生"],
                    "recent_activity": "在教室里发呆",
                    "relationships": [],
                }
            ],
        )
        service.merge_updates(
            conn,
            book_id="book-1",
            chapter_index=2,
            doc_ids=[2],
            updates=[
                {
                    "canonical_name": "路明非",
                    "aliases": ["明非"],
                    "personality": ["敏感克制"],
                    "recent_activity": "在雨夜赶往医院",
                    "relationships": [],
                }
            ],
        )
        conn.commit()

        rows = CharacterProfilesRepo().list_by_book(conn, book_id="book-1")

    assert [str(row["canonical_name"]) for row in rows] == ["路明非"]
    row = rows[0]
    assert _load_json(row, "aliases_json") == ["明非"]

    personality = _load_json(row, "personality_json")
    recent_activity = _load_json(row, "recent_activity_json")

    assert personality[0]["value"] == "敏感克制"
    assert personality[0]["field_type"] == "inference"
    assert personality[0]["evidence_level"] == "inferred"
    assert recent_activity[-1]["value"] == "在雨夜赶往医院"
    assert recent_activity[-1]["field_type"] == "fact"
    assert "## 已确认事实" in str(row["profile_summary_md"])
    assert "## 审慎推断" in str(row["profile_summary_md"])


def test_merge_updates_resolves_relationship_conflicts_and_alias_targets(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "character_relationships.db")
    service = _build_service()

    with db.connect() as conn:
        db.init_schema(conn)
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-2",
                "canonical_name": "楚子航",
                "aliases": ["楚师兄"],
                "profile_summary_md": "# 楚子航\n",
                "personality": [],
                "occupations": [],
                "age_timeline": [],
                "abilities": [],
                "recent_activity": [],
                "relationships": [],
                "chapter_indexes": [1],
                "first_seen_doc_id": 1,
                "last_seen_doc_id": 1,
                "first_seen_title_index": 1,
                "last_seen_title_index": 1,
                "importance_score": 0,
                "profile_version": 1,
                "created_at": "now",
                "updated_at": "now",
            },
        )
        service.merge_updates(
            conn,
            book_id="book-2",
            chapter_index=2,
            doc_ids=[20],
            updates=[
                {
                    "canonical_name": "路明非",
                    "aliases": [],
                    "personality": [],
                    "occupations": [],
                    "recent_activity": "",
                    "relationships": [
                        {
                            "target_name": "楚师兄",
                            "relation_type": "同学",
                            "sentiment_state": "疏离",
                            "status_summary": "与楚师兄保持距离",
                        }
                    ],
                }
            ],
        )
        service.merge_updates(
            conn,
            book_id="book-2",
            chapter_index=5,
            doc_ids=[50, 51],
            updates=[
                {
                    "canonical_name": "路明非",
                    "aliases": [],
                    "personality": [],
                    "occupations": [],
                    "recent_activity": "",
                    "relationships": [
                        {
                            "target_name": "楚子航",
                            "relation_type": "搭档",
                            "sentiment_state": "信任回升",
                            "status_summary": "和楚子航并肩应对袭击",
                        }
                    ],
                }
            ],
        )
        conn.commit()

        row = _fetch_profile_row(conn, book_id="book-2", canonical_name="路明非")

    relationships = _load_json(row, "relationships_json")

    assert len(relationships) == 1
    assert relationships[0]["target_name"] == "楚子航"
    assert relationships[0]["relation_type"] == "搭档"
    assert relationships[0]["sentiment_state"] == "信任回升"
    assert relationships[0]["last_updated_chapter_index"] == 5
    assert relationships[0]["source_chapter_indexes"] == [2, 5]


def test_merge_updates_filters_style_metadata_from_profile_fields(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "character_filtering.db")
    service = _build_service()

    with db.connect() as conn:
        db.init_schema(conn)
        service.merge_updates(
            conn,
            book_id="book-3",
            chapter_index=3,
            doc_ids=[31],
            updates=[
                {
                    "canonical_name": "沈青",
                    "aliases": [],
                    "personality": ["作者借这段对话制造悬念", "冷静克制"],
                    "occupations": ["学生"],
                    "recent_activity": "本章通过雨夜描写强化了她的孤独",
                    "relationships": [
                        {
                            "target_name": "周渡",
                            "relation_type": "同学",
                            "sentiment_state": "紧张",
                            "status_summary": "这一章通过对比制造张力",
                        }
                    ],
                }
            ],
        )
        conn.commit()

        row = _fetch_profile_row(conn, book_id="book-3", canonical_name="沈青")

    personality = _load_json(row, "personality_json")
    recent_activity = _load_json(row, "recent_activity_json")
    relationships = _load_json(row, "relationships_json")

    assert [item["value"] for item in personality] == ["冷静克制"]
    assert recent_activity == []
    assert relationships == []
