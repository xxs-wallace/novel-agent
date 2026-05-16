from __future__ import annotations

import json
from types import SimpleNamespace

from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.services.character_canonical_name_service import CharacterCanonicalNameService


def _profile_payload(
    *,
    book_id: str,
    canonical_name: str,
    aliases: list[str] | None = None,
    last_seen_doc_id: int | None = None,
    last_seen_title_index: int | None = None,
) -> dict[str, object]:
    return {
        "book_id": book_id,
        "canonical_name": canonical_name,
        "aliases": aliases or [],
        "profile_summary_md": f"# {canonical_name}\n",
        "speaking_character_status": "unknown",
        "personhood_evidence_summary": "",
        "evidence_level": "inferred",
        "personality": [],
        "occupations": [],
        "age_timeline": [],
        "abilities": [],
        "recent_activity": [],
        "relationships": [],
        "story_events": [],
        "chapter_indexes": [],
        "mentioned_doc_ids": [],
        "speaking_doc_ids": [],
        "first_seen_doc_id": last_seen_doc_id,
        "last_seen_doc_id": last_seen_doc_id,
        "first_seen_title_index": last_seen_title_index,
        "last_seen_title_index": last_seen_title_index,
        "importance_score": 0,
        "profile_version": 1,
        "created_at": "now",
        "updated_at": "now",
    }


class _CanonicalNameModel:
    settings = SimpleNamespace(dry_run=False)

    def __init__(self) -> None:
        self.prompt_payloads: list[dict[str, object]] = []

    def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
        _ = fallback_factory, use_fallback_on_error
        assert "Character Canonical Name Agent" in system_prompt
        payload = json.loads(str(user_prompt).split("输入数据如下：\n", 1)[1])
        self.prompt_payloads.append(payload)
        assert payload["candidate_names"] == ["老板", "张大", "丈夫"]
        return (
            {
                "preferred_canonical_name": "张大",
                "aliases_to_keep": ["老板", "丈夫"],
                "reason": "张大更像正式姓名。",
                "confidence": 0.93,
            },
            "",
        )


def test_canonical_name_agent_selects_formal_name_from_aliases(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "canonical_name.db")
    service = CharacterCanonicalNameService(profiles_repo=CharacterProfilesRepo())
    model = _CanonicalNameModel()

    with db.connect() as conn:
        db.init_schema(conn)
        resolved = service.resolve_updates(
            conn,
            book_id="book-1",
            model_client=model,  # type: ignore[arg-type]
            updates=[
                {
                    "canonical_name": "老板",
                    "aliases": ["张大", "丈夫"],
                    "recent_activity": "继续处理家庭冲突。",
                    "relationships": [],
                }
            ],
        )

    assert len(model.prompt_payloads) == 1
    assert resolved == [
        {
            "canonical_name": "张大",
            "aliases": ["老板", "丈夫"],
            "recent_activity": "继续处理家庭冲突。",
            "relationships": [],
            "preferred_canonical_name": "张大",
        }
    ]


def test_profile_merge_honors_preferred_canonical_name(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "preferred_profile_name.db")

    with db.connect() as conn:
        db.init_schema(conn)
        from novel_agent.app.services.character_profile_service import CharacterProfileService

        CharacterProfileService(profiles_repo=CharacterProfilesRepo()).merge_updates(
            conn,
            book_id="book-1",
            chapter_index=1,
            doc_ids=[1],
            updates=[
                {
                    "canonical_name": "老板",
                    "preferred_canonical_name": "张大",
                    "aliases": ["张大", "丈夫"],
                    "recent_activity": "处理家庭冲突。",
                    "relationships": [],
                }
            ],
        )
        rows = CharacterProfilesRepo().list_by_book(conn, book_id="book-1")

    assert [row["canonical_name"] for row in rows] == ["张大"]
    assert json.loads(rows[0]["aliases_json"]) == ["老板", "丈夫"]


def test_canonical_name_agent_reruns_when_new_alias_updates_existing_profile(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "canonical_name_reveal.db")
    repo = CharacterProfilesRepo()
    service = CharacterCanonicalNameService(profiles_repo=repo)

    class _RevealNameModel:
        settings = SimpleNamespace(dry_run=False)

        def __init__(self) -> None:
            self.prompt_payloads: list[dict[str, object]] = []

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = system_prompt, fallback_factory, use_fallback_on_error
            payload = json.loads(str(user_prompt).split("输入数据如下：\n", 1)[1])
            self.prompt_payloads.append(payload)
            assert payload["current_canonical_name"] == "周先生"
            assert payload["candidate_names"] == ["周先生", "沈砚", "周渡"]
            assert payload["existing_profiles"][0]["canonical_name"] == "周先生"
            return (
                {
                    "preferred_canonical_name": "沈砚",
                    "aliases_to_keep": ["周先生", "周渡"],
                    "reason": "新剧情确认周先生此前使用假名，沈砚才是正式姓名。",
                    "confidence": 0.94,
                },
                "",
            )

    with db.connect() as conn:
        db.init_schema(conn)
        repo.upsert(
            conn,
            _profile_payload(
                book_id="book-1",
                canonical_name="周先生",
                aliases=["周渡"],
                last_seen_doc_id=3,
                last_seen_title_index=1,
            ),
        )
        model = _RevealNameModel()
        resolved = service.resolve_updates(
            conn,
            book_id="book-1",
            model_client=model,  # type: ignore[arg-type]
            updates=[
                {
                    "canonical_name": "周先生",
                    "aliases": ["沈砚"],
                    "recent_activity": "承认此前使用假名周渡。",
                    "relationships": [],
                }
            ],
        )

    assert len(model.prompt_payloads) == 1
    assert resolved[0]["canonical_name"] == "沈砚"
    assert resolved[0]["aliases"] == ["周先生", "周渡"]
