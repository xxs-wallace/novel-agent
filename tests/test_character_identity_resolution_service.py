from __future__ import annotations

import json
from types import SimpleNamespace

from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.services.character_identity_resolution_service import CharacterIdentityResolutionService


class _FakeIdentityModel:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(dry_run=False)
        self.prompts: list[dict[str, object]] = []

    def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
        _ = fallback_factory, use_fallback_on_error
        assert "Character Identity Resolution Agent" in system_prompt
        marker = "输入数据如下：\n"
        payload = json.loads(str(user_prompt).split(marker, 1)[1])
        self.prompts.append(payload)
        if payload["resolution_round"] == "initial":
            assert payload["all_character_profiles"] == []
            assert [item["canonical_name"] for item in payload["existing_character_roster"]] == ["张大"]
            return (
                {
                    "action": "request_all_profiles",
                    "canonical_name": "",
                    "existing_canonical_name": "",
                    "aliases_to_add": [],
                    "reason": "候选名未被源文验证，需要查看已有角色表。",
                    "confidence": 0.72,
                },
                "",
            )
        assert payload["resolution_round"] == "with_all_profiles"
        assert [item["canonical_name"] for item in payload["all_character_profiles"]] == ["张大"]
        return (
            {
                "action": "merge_existing",
                "canonical_name": "",
                "existing_canonical_name": "张大",
                "aliases_to_add": [],
                "reason": "候选是模型概括标签，应并入既有第一人称人物。",
                "confidence": 0.91,
            },
            "",
        )


def test_identity_resolution_agent_loop_queries_all_profiles_on_demand(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "identity_resolution.db")
    service = CharacterIdentityResolutionService(profiles_repo=CharacterProfilesRepo())
    model = _FakeIdentityModel()

    with db.connect() as conn:
        db.init_schema(conn)
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-1",
                "canonical_name": "张大",
                "aliases": ["我"],
                "profile_summary_md": "# 张大\n\n- 人物性证据：第一人称叙述者，有稳定行动。\n",
                "speaking_character_status": "confirmed_speaking",
                "personhood_evidence_summary": "第一人称叙述者，有稳定行动。",
                "evidence_level": "explicit",
                "personality": [],
                "occupations": [],
                "age_timeline": [],
                "abilities": [],
                "recent_activity": [],
                "relationships": [],
                "story_events": [],
                "chapter_indexes": [1],
                "mentioned_doc_ids": [1],
                "speaking_doc_ids": [1],
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

        resolved = service.resolve_updates(
            conn,
            book_id="book-1",
            model_client=model,  # type: ignore[arg-type]
            updates=[
                {
                    "canonical_name": "叙述者",
                    "aliases": [],
                    "recent_activity": "候选来自模型概括，而不是源文人名。",
                    "relationships": [],
                }
            ],
            source_verified_names=["我"],
            source_verified_speakers=["我"],
        )

    assert len(model.prompts) == 2
    assert resolved == [
        {
            "canonical_name": "张大",
            "aliases": [],
            "recent_activity": "候选来自模型概括，而不是源文人名。",
            "relationships": [],
        }
    ]


def test_identity_resolution_rejects_create_new_without_source_verified_name(tmp_path) -> None:
    db = NovelAgentDB(tmp_path / "identity_reject.db")
    service = CharacterIdentityResolutionService(profiles_repo=CharacterProfilesRepo())

    class _BadCreateModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, **_kwargs):  # type: ignore[no-untyped-def]
            return (
                {
                    "action": "create_new",
                    "canonical_name": "临时称谓",
                    "existing_canonical_name": "",
                    "aliases_to_add": [],
                    "reason": "bad decision",
                    "confidence": 0.9,
                },
                "",
            )

    with db.connect() as conn:
        db.init_schema(conn)
        resolved = service.resolve_updates(
            conn,
            book_id="book-1",
            model_client=_BadCreateModel(),  # type: ignore[arg-type]
            updates=[{"canonical_name": "临时称谓", "aliases": [], "recent_activity": "没有源文人名支撑。"}],
            source_verified_names=[],
            source_verified_speakers=[],
        )

    assert resolved == []
