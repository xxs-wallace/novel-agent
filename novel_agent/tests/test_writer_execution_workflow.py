from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from novel_agent.app.orchestrators import (
    RestrictedWriterExecutor,
    WriterInteractiveWorkflow,
    WriterLayeredGenerationOrchestrator,
    WriterRollbackManager,
)
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.run_interactive import build_writer_workflow
from novel_agent.runs.layout import RunLayout
from novel_agent.runs.writer import RunWriter
from novel_agent.schemas import (
    ChapterReplanRequest,
    GenerationReviewDecision,
    LengthPlanUpdate,
)
from novel_agent.app.schemas.orchestration_schema import (
    BookContinuationPlan,
    ModelingStatus,
    WorldExpansionPack,
)
from novel_agent.app.orchestrators.writer_planning_types import (
    CharacterRequirementReport,
    NamedNewCharacter,
)
from novel_agent.tests.test_writer_layered_generation_orchestrator import (
    _build_orchestrator,
    _seed_assets,
    _seed_document,
    _seed_fragment_card,
    _seed_profile,
)


def _load_run_artifact_data(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def test_generation_review_decision_status_variants_are_available_from_runtime_exports() -> None:
    accepted = GenerationReviewDecision(
        schema_version="1.0",
        decision_id="review-001",
        run_id="run-001",
        chapter_id="chapter-001",
        draft_id="draft-001",
        status="accepted",
        reason_code="approved",
        feedback_text=" 当前稿可进入正式验收。 ",
        next_action_checkpoint="freeze_e",
        reviewer_type="user",
        created_at="2026-05-03T12:00:00Z",
    )
    discarded = GenerationReviewDecision(
        schema_version="1.0",
        decision_id="review-002",
        chapter_id="chapter-001",
        draft_id="draft-002",
        status="discarded",
        reason_code="user_abandoned",
        feedback_text=" 当前版本作废。 ",
        next_action_checkpoint="halted",
        reviewer_type="user",
        created_at="2026-05-03T12:05:00Z",
    )

    assert accepted.to_dict()["status"] == "accepted"
    assert accepted.to_dict()["feedback_text"] == "当前稿可进入正式验收。"
    assert accepted.to_dict()["next_action_checkpoint"] == "freeze_e"
    assert discarded.to_dict()["status"] == "discarded"
    assert discarded.to_dict()["next_action_checkpoint"] == "halted"


def test_generation_review_decision_revise_length_requires_length_plan_update() -> None:
    length_update = LengthPlanUpdate(
        schema_version="1.0",
        update_id="length-001",
        decision_id="review-003",
        chapter_id="chapter-001",
        target_chars=3200,
        min_chars=2800,
        max_chars=3600,
        reason_code="length_too_short",
        feedback_text=" 保留当前方向，补足高潮前铺垫。 ",
        created_at="2026-05-03T12:10:00Z",
    )
    decision = GenerationReviewDecision(
        schema_version="1.0",
        decision_id="review-003",
        chapter_id="chapter-001",
        draft_id="draft-003",
        status="revise_length",
        reason_code="length_too_short",
        feedback_text=" 字数偏短，需要重调预算。 ",
        next_action_checkpoint="wait_length_review",
        length_plan_update=length_update,
        reviewer_type="user",
        created_at="2026-05-03T12:10:00Z",
    )

    assert decision.to_dict()["status"] == "revise_length"
    assert decision.to_dict()["length_plan_update"]["target_chars"] == 3200
    assert decision.to_dict()["next_action_checkpoint"] == "wait_length_review"

    with pytest.raises(ValueError, match="length_plan_update"):
        GenerationReviewDecision(
            schema_version="1.0",
            decision_id="review-004",
            chapter_id="chapter-001",
            draft_id="draft-004",
            status="revise_length",
            reason_code="length_too_short",
            feedback_text="缺少长度修订对象。",
            next_action_checkpoint="wait_length_review",
            reviewer_type="user",
            created_at="2026-05-03T12:11:00Z",
        )


def test_generation_review_decision_replan_chapter_requires_replan_request() -> None:
    replan_request = ChapterReplanRequest(
        schema_version="1.0",
        request_id="replan-001",
        decision_id="review-005",
        chapter_id="chapter-001",
        reason_code="structure_mismatch",
        feedback_text=" 需要重排章节结构并延后关系推进。 ",
        must_preserve=["本章仍需保留联手脱险"],
        must_change=["提前进入行动段"],
        forbidden_carryover=["不得沿用当前稿的升温节奏"],
        requested_length_direction={"keep_default_plan": False, "suggested_target_chars": 2600},
        created_at="2026-05-03T12:15:00Z",
    )
    decision = GenerationReviewDecision(
        schema_version="1.0",
        decision_id="review-005",
        chapter_id="chapter-001",
        draft_id="draft-005",
        status="replan_chapter",
        reason_code="structure_mismatch",
        feedback_text=" 当前章方向需要回退重规划。 ",
        next_action_checkpoint="wait_chapter_review",
        chapter_replan_request=replan_request,
        reviewer_type="user",
        created_at="2026-05-03T12:15:00Z",
    )

    assert decision.to_dict()["status"] == "replan_chapter"
    assert decision.to_dict()["chapter_replan_request"]["replan_scope"] == "current_chapter"
    assert decision.to_dict()["next_action_checkpoint"] == "wait_chapter_review"

    with pytest.raises(ValueError, match="chapter_replan_request"):
        GenerationReviewDecision(
            schema_version="1.0",
            decision_id="review-006",
            chapter_id="chapter-001",
            draft_id="draft-006",
            status="replan_chapter",
            reason_code="direction_mismatch",
            feedback_text="缺少章节重规划请求。",
            next_action_checkpoint="wait_chapter_review",
            reviewer_type="user",
            created_at="2026-05-03T12:16:00Z",
        )


def test_requirement_coverage_accepts_runtime_writer_aliases(tmp_path: Path) -> None:
    executor = RestrictedWriterExecutor(
        repo_root=tmp_path,
        run_writer=RunWriter(RunLayout(tmp_path / "runs")),
    )
    executor._runtime_requirement_aliases = {  # noqa: SLF001
        "密令": ("暗号", "口令"),
        "会合": ("碰头", "汇合"),
        "信物": ("钥匙", "令牌"),
    }

    draft = "他用暗号通知同伴，约定天亮前在旧桥碰头。"

    assert executor._requirement_covered(  # noqa: SLF001
        draft_text=draft,
        requirement="队长通过密令安排会合",
    )
    assert executor._requirement_covered(  # noqa: SLF001
        draft_text="她把钥匙交给守门人。",
        requirement="交付信物",
    )
    assert executor._requirement_covered(  # noqa: SLF001
        draft_text="守门人按约定说出口令，确认对方身份。",
        requirement="密令验证身份",
    )
    prompt = executor._build_execution_prompt(  # noqa: SLF001
        {
            "chapter_title": "视角测试",
            "chapter_brief": {},
            "length_budget": {},
            "writer_rules": [],
        }
    )
    assert "不得擅自更换叙述者或视角机制" in prompt["system_prompt"]
    assert "固定第一人称或固定限知视角" in prompt["user_prompt"]
    assert "男主角" not in prompt["user_prompt"]
    assert "女主角" not in prompt["user_prompt"]


def test_restricted_writer_executor_exposes_draft_generation_interface(tmp_path: Path) -> None:
    executor = RestrictedWriterExecutor(
        repo_root=tmp_path,
        run_writer=RunWriter(RunLayout(tmp_path / "runs")),
    )
    execution_input = {
        "chapter_title": "测试扩写",
        "chapter_brief": {
            "title": "测试扩写",
            "goal": "主角收到录取信。",
            "must_include": ["录取信", "手机"],
        },
        "length_budget": {"target_chars": 240, "min_chars": 200, "max_chars": 280},
        "writer_rules": ["只能根据梗概扩写。"],
    }

    prompt = executor.build_draft_prompt(execution_input)
    draft = executor.generate_draft_from_execution_input(execution_input)

    assert "主角收到录取信" in prompt["user_prompt"]
    assert "测试扩写" in draft
    assert "录取信" in draft


def test_restricted_writer_executor_prompts_for_merged_reference_document_synopses(tmp_path: Path) -> None:
    executor = RestrictedWriterExecutor(
        repo_root=tmp_path,
        run_writer=RunWriter(RunLayout(tmp_path / "runs")),
    )
    prompt = executor.build_draft_prompt(
        {
            "chapter_title": "长段扩写",
            "chapter_brief": {
                "title": "长段扩写",
                "goal": "按连续梗概扩写目标窗口。",
                "combined_synopsis": "第一段承接邀请，第二段推进试衣和赴约。",
                "reference_document_synopses": [
                    {"order": 1, "summary": "主角收到邀请。"},
                    {"order": 2, "summary": "主角换上西装准备赴约。"},
                ],
            },
            "length_budget": {"target_chars": 1200, "min_chars": 1000, "max_chars": 1400},
            "writer_rules": [],
        }
    )

    assert "连续多个 document 梗概" in prompt["system_prompt"]
    assert "reference_document_synopses" in prompt["user_prompt"]
    assert "必须按 order 顺序" in prompt["user_prompt"]


def test_prepare_freeze_a_can_disable_character_cast_planning(tmp_path: Path) -> None:
    run_writer = RunWriter(RunLayout(tmp_path / "runs"))
    orchestrator = WriterLayeredGenerationOrchestrator(repo_root=tmp_path, run_writer=run_writer)

    orchestrator.check_modeling_status = lambda _conn, *, book_id: ModelingStatus(  # type: ignore[method-assign]
        book_id=book_id,
        ready_for_continuation=True,
    )
    orchestrator.plan_book_continuation = lambda _conn, *, book_id, intent: BookContinuationPlan(  # type: ignore[method-assign]
        plan_id="plan-1",
        book_id=book_id,
        continuation_goal="承接目标剧情。",
    )
    orchestrator.plan_world_expansion = lambda _conn, *, book_id, intent, book_plan, user_world_notes: WorldExpansionPack(  # type: ignore[method-assign]
        pack_id="world-1",
        book_id=book_id,
    )
    orchestrator.analyze_character_requirements = lambda _conn, *, book_id, intent, book_plan: CharacterRequirementReport(  # type: ignore[method-assign]
        named_new_characters=[NamedNewCharacter(name="误识别角色", reason="测试")],
        named_existing_characters=[],
        unfilled_role_slots=[],
    )
    orchestrator.plan_character_cast = lambda **_kwargs: pytest.fail(  # type: ignore[method-assign]
        "character cast planning should be skipped"
    )

    conn = NovelAgentDB(tmp_path / "memory.db").connect()
    try:
        result = orchestrator.prepare_freeze_a(
            conn,
            run_id="run-1",
            book_id="book-1",
            intent_payload={
                "allow_character_cast": False,
                "desired_actions": ["承接目标剧情。"],
            },
        )
    finally:
        conn.close()

    assert result["character_cast_plan"] is None
    assert result["character_introduction_plan"] is None
    assert not (run_writer.layout.run_dir("run-1") / "character_introduction_plan.json").exists()


def test_run_writer_generation_review_decision_persists_traceable_defaults(tmp_path: Path) -> None:
    writer = RunWriter(layout=RunLayout(base_dir=tmp_path / "runs"))
    path = writer.write_generation_review_decision(
        "run-1",
        {
            "status": "accepted",
            "reason_code": "approved",
            "feedback_text": "当前稿通过验收。",
            "next_action_checkpoint": "freeze_e",
        },
        defaults={
            "decision_id": "review-chapter-001-draft-001",
            "chapter_id": "chapter-001",
            "draft_id": "draft-001",
            "reviewer_type": "user",
        },
    )

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["run_id"] == "run-1"
    assert doc["data"]["schema_version"] == "1.0"
    assert doc["data"]["run_id"] == "run-1"
    assert doc["data"]["chapter_id"] == "chapter-001"
    assert doc["data"]["draft_id"] == "draft-001"
    assert doc["data"]["decision_id"] == "review-chapter-001-draft-001"
    assert doc["data"]["created_at"]


def test_run_writer_rework_artifacts_persist_contract_defaults(tmp_path: Path) -> None:
    writer = RunWriter(layout=RunLayout(base_dir=tmp_path / "runs"))

    length_update_path = writer.write_length_plan_update(
        "run-1",
        {
            "target_chars": 3200,
            "min_chars": 2800,
            "max_chars": 3600,
        },
        defaults={
            "update_id": "length-update-review-001",
            "decision_id": "review-001",
            "chapter_id": "chapter-001",
            "reason_code": "length_too_short",
            "feedback_text": "保留现有方向，但需要补足关键段落。",
        },
    )
    length_update_doc = json.loads(length_update_path.read_text(encoding="utf-8"))
    assert length_update_doc["data"] == {
        "schema_version": "1.0",
        "update_id": "length-update-review-001",
        "decision_id": "review-001",
        "chapter_id": "chapter-001",
        "target_chars": 3200,
        "min_chars": 2800,
        "max_chars": 3600,
        "reason_code": "length_too_short",
        "feedback_text": "保留现有方向，但需要补足关键段落。",
        "preserve_story_direction": True,
        "created_at": length_update_doc["data"]["created_at"],
    }

    replan_request_path = writer.write_chapter_replan_request(
        "run-1",
        {
            "must_change": ["提前进入行动段"],
            "requested_length_direction": {
                "keep_default_plan": False,
                "suggested_target_chars": 2600,
            },
        },
        defaults={
            "request_id": "replan-review-002",
            "decision_id": "review-002",
            "chapter_id": "chapter-001",
            "reason_code": "structure_mismatch",
            "feedback_text": "当前结构不合适，需要退回章节重规划。",
        },
    )
    replan_request_doc = json.loads(replan_request_path.read_text(encoding="utf-8"))
    assert replan_request_doc["data"] == {
        "schema_version": "1.0",
        "request_id": "replan-review-002",
        "decision_id": "review-002",
        "chapter_id": "chapter-001",
        "reason_code": "structure_mismatch",
        "feedback_text": "当前结构不合适，需要退回章节重规划。",
        "replan_scope": "current_chapter",
        "must_preserve": [],
        "must_change": ["提前进入行动段"],
        "forbidden_carryover": [],
        "requested_length_direction": {
            "keep_default_plan": False,
            "suggested_target_chars": 2600,
        },
        "created_at": replan_request_doc["data"]["created_at"],
    }


def _prepare_freeze_c_chain(
    tmp_path: Path,
) -> tuple[NovelAgentDB, WriterLayeredGenerationOrchestrator]:
    db, orchestrator = _build_orchestrator(tmp_path)
    book_id = "book-1"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        _seed_profile(conn, book_id=book_id, canonical_name="沈青")
        _seed_fragment_card(conn)
        conn.commit()
        orchestrator.prepare_freeze_a(
            conn,
            run_id="run-1",
            book_id=book_id,
            intent_payload={
                "major_characters": ["沈青", "顾迟"],
                "desired_actions": ["安排援军接应并继续追查旧案"],
                "avoidances": ["不要突然告白"],
                "preferred_outcome": "阶段性脱险但留下更深疑点",
                "notes": "需要一个新的反派压力位。",
            },
            character_seed_payloads=[
                {
                    "seed_id": "seed-1",
                    "display_name_hint": "顾迟",
                    "faction": "友方",
                    "core_concept": "外冷内热的情报中间人",
                    "must_keep": ["冷静", "克制"],
                    "must_avoid": ["喧宾夺主"],
                    "relationship_entry": {
                        "target_character": "沈青",
                        "initial_state": "互相试探",
                        "allowed_target_state_in_this_batch": "有限合作",
                    },
                    "world_constraints": ["不得拥有超出现有体系的能力"],
                }
            ],
        )
        orchestrator.confirm_freeze_a(run_id="run-1")
        orchestrator.prepare_batch_plan(conn, run_id="run-1", book_id=book_id, target_chapter_count=2)
        orchestrator.confirm_batch_plan(run_id="run-1")
        orchestrator.prepare_chapter_package(run_id="run-1", book_id=book_id, chapter_count=2)
    return db, orchestrator


def _write_accepted_review_decision(
    orchestrator: WriterLayeredGenerationOrchestrator,
    *,
    run_id: str,
    chapter_id: str,
    draft_id: str = "draft-001",
) -> None:
    decision = GenerationReviewDecision(
        schema_version="1.0",
        decision_id=f"{run_id}-accepted",
        run_id=run_id,
        chapter_id=chapter_id,
        draft_id=draft_id,
        status="accepted",
        reason_code="approved",
        feedback_text="当前稿通过验收。",
        next_action_checkpoint="freeze_e",
        reviewer_type="user",
        created_at="2026-05-03T12:30:00Z",
    )
    orchestrator.run_writer.write_generation_review_decision(run_id, decision)


def _write_discarded_review_decision(
    orchestrator: WriterLayeredGenerationOrchestrator,
    *,
    run_id: str,
    chapter_id: str,
    draft_id: str = "draft-001",
) -> None:
    decision = GenerationReviewDecision(
        schema_version="1.0",
        decision_id=f"{run_id}-discarded",
        run_id=run_id,
        chapter_id=chapter_id,
        draft_id=draft_id,
        status="discarded",
        reason_code="user_abandoned",
        feedback_text="当前稿不采纳。",
        next_action_checkpoint="halted",
        reviewer_type="user",
        created_at="2026-05-03T12:35:00Z",
    )
    orchestrator.run_writer.write_generation_review_decision(run_id, decision)


def _write_revise_length_review_decision(
    orchestrator: WriterLayeredGenerationOrchestrator,
    *,
    run_id: str,
    chapter_id: str,
    draft_id: str = "draft-001",
) -> None:
    length_update = LengthPlanUpdate(
        schema_version="1.0",
        update_id=f"{run_id}-length-update",
        decision_id=f"{run_id}-revise-length",
        chapter_id=chapter_id,
        target_chars=3200,
        min_chars=2800,
        max_chars=3600,
        reason_code="length_too_short",
        feedback_text="保留现有方向，但需要补足关键段落。",
        created_at="2026-05-03T12:40:00Z",
    )
    decision = GenerationReviewDecision(
        schema_version="1.0",
        decision_id=f"{run_id}-revise-length",
        run_id=run_id,
        chapter_id=chapter_id,
        draft_id=draft_id,
        status="revise_length",
        reason_code="length_too_short",
        feedback_text="字数偏短，先回到长度审阅。",
        next_action_checkpoint="wait_length_review",
        length_plan_update=length_update,
        reviewer_type="user",
        created_at="2026-05-03T12:40:00Z",
    )
    orchestrator.run_writer.write_generation_review_decision(run_id, decision)


def _write_replan_review_decision(
    orchestrator: WriterLayeredGenerationOrchestrator,
    *,
    run_id: str,
    chapter_id: str,
    draft_id: str = "draft-001",
) -> None:
    replan_request = ChapterReplanRequest(
        schema_version="1.0",
        request_id=f"{run_id}-replan-request",
        decision_id=f"{run_id}-replan",
        chapter_id=chapter_id,
        reason_code="structure_mismatch",
        feedback_text="当前结构不合适，需要退回章节重规划。",
        must_preserve=["本章仍需保留联手脱险"],
        must_change=["提前进入行动段"],
        forbidden_carryover=["不得沿用当前稿的节奏"],
        requested_length_direction={"keep_default_plan": False, "suggested_target_chars": 2600},
        created_at="2026-05-03T12:45:00Z",
    )
    decision = GenerationReviewDecision(
        schema_version="1.0",
        decision_id=f"{run_id}-replan",
        run_id=run_id,
        chapter_id=chapter_id,
        draft_id=draft_id,
        status="replan_chapter",
        reason_code="structure_mismatch",
        feedback_text="当前章需要回退到章节梗概重规划。",
        next_action_checkpoint="wait_chapter_review",
        chapter_replan_request=replan_request,
        reviewer_type="user",
        created_at="2026-05-03T12:45:00Z",
    )
    orchestrator.run_writer.write_generation_review_decision(run_id, decision)


def test_restricted_writer_executor_blocks_illegal_relationship_progression(tmp_path: Path) -> None:
    db, orchestrator = _prepare_freeze_c_chain(tmp_path)
    chapter_package_path = orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json"
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
    chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["共同危机", "公开站队"]
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    orchestrator.confirm_chapter_package(run_id="run-1")

    executor = RestrictedWriterExecutor(
        repo_root=orchestrator.repo_root,
        run_writer=orchestrator.run_writer,
        model_client=None,
    )
    with db.connect() as conn:
        result = executor.prepare_execution_input(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
        )
        assert result["execution_checkpoint"]["status"] == "ready_for_freeze_d"
        executor.confirm_freeze_d(run_id="run-1")
        execution_result = executor.execute_frozen_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            commit_writeback=False,
            auto_freeze_e=False,
        )

    assert execution_result["canon_ready"] is False
    issue_types = {item["type"] for item in execution_result["continuity_report"]["issues"]}
    assert "missing_relationship_bridge" in issue_types


def test_execute_current_chapter_persists_pending_generation_review_decision_artifact(tmp_path: Path) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    chapter_package_path = planner_orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json"
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
    chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
    chapter_package_doc["data"]["chapters"][0]["must_include"].append("沈青")
    chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    planner_orchestrator.confirm_chapter_package(run_id="run-1")

    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        workflow.initialize_workflow(run_id="run-1", book_id="book-1", product_mode="assist")
        workflow.prepare_execution(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
            product_mode="assist",
        )
        workflow.continue_after_execution_review(run_id="run-1")
        result = workflow.execute_current_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            product_mode="assist",
        )

    assert result["canon_ready"] is True
    assert result["draft_path"].endswith("draft.md")
    assert result["mentioned_character_profiles_path"].endswith("mentioned_character_profiles.json")
    checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-1")
    assert checkpoint is not None
    assert checkpoint["stage"] == "wait_chapter_acceptance"
    assert checkpoint["artifact_path"].endswith("generation_review_decision.json")

    decision_path = workflow.run_writer.layout.run_dir("run-1") / "generation_review_decision.json"
    decision_doc = json.loads(decision_path.read_text(encoding="utf-8"))
    decision = decision_doc["data"]
    assert decision["schema_version"] == "1.0"
    assert decision["run_id"] == "run-1"
    assert decision["chapter_id"] == chapter_id
    assert decision["draft_id"] == "draft-001"
    assert decision["decision_id"] == f"review-{chapter_id}-draft-001"
    assert decision["status"] == ""
    assert decision["next_action_checkpoint"] == ""
    profiles_path = workflow.run_writer.layout.run_dir("run-1") / "mentioned_character_profiles.json"
    profiles_doc = json.loads(profiles_path.read_text(encoding="utf-8"))
    matched_names = {
        profile["canonical_name"]
        for profile in profiles_doc["data"]["matched_profiles"]
    }
    assert "沈青" in matched_names


def test_executor_requires_accepted_review_decision_before_auto_writeback(tmp_path: Path) -> None:
    db, orchestrator = _prepare_freeze_c_chain(tmp_path)
    chapter_package_path = orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json"
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
    chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
    chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    orchestrator.confirm_chapter_package(run_id="run-1")

    executor = RestrictedWriterExecutor(
        repo_root=orchestrator.repo_root,
        run_writer=orchestrator.run_writer,
        model_client=None,
    )
    with db.connect() as conn:
        executor.prepare_execution_input(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
        )
        executor.confirm_freeze_d(run_id="run-1")
        result = executor.execute_frozen_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            commit_writeback=True,
            auto_freeze_e=True,
        )
        conn.commit()

    assert result["canon_ready"] is True
    assert result["accepted_for_writeback"] is False
    assert result["writeback_committed"] is False
    assert result["review_decision_status"] == ""
    assert result["memory_writeback"] == {}
    assert result["continuity_report"]["accepted_for_writeback"] is False
    assert result["continuity_report"]["writeback_blocked_reason"] == "review_not_accepted"
    memory_writeback_path = orchestrator.run_writer.layout.run_dir("run-1") / "memory_writeback.json"
    assert not memory_writeback_path.exists()
    registry_path = orchestrator.run_writer.layout.run_dir("run-1") / "planned_character_registry.json"
    assert not registry_path.exists()
    with db.connect() as conn:
        profile = CharacterProfilesRepo().get(conn, book_id="book-1", canonical_name="顾迟")
        assert profile is None
    freeze_e = orchestrator.run_writer.get_freeze_record("run-1", "freeze_e")
    assert freeze_e is None


def test_executor_writeback_promotes_planned_character_to_formal_memory_after_acceptance(tmp_path: Path) -> None:
    db, orchestrator = _prepare_freeze_c_chain(tmp_path)
    chapter_package_path = orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json"
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
    chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
    chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    orchestrator.confirm_chapter_package(run_id="run-1")
    _write_accepted_review_decision(orchestrator, run_id="run-1", chapter_id=chapter_id)

    executor = RestrictedWriterExecutor(
        repo_root=orchestrator.repo_root,
        run_writer=orchestrator.run_writer,
        model_client=None,
    )
    with db.connect() as conn:
        executor.prepare_execution_input(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
        )
        executor.confirm_freeze_d(run_id="run-1")
        result = executor.execute_frozen_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            commit_writeback=True,
            auto_freeze_e=True,
        )
        conn.commit()

    assert result["canon_ready"] is True
    assert result["accepted_for_writeback"] is True
    assert result["writeback_committed"] is True
    assert result["review_decision_status"] == "accepted"
    assert "顾迟" in result["memory_writeback"]["activated_planned_characters"]
    assert result["continuity_report"]["accepted_for_writeback"] is True
    assert result["continuity_report"]["writeback_blocked_reason"] == ""
    memory_writeback_path = orchestrator.run_writer.layout.run_dir("run-1") / "memory_writeback.json"
    assert memory_writeback_path.exists()
    registry_path = orchestrator.run_writer.layout.run_dir("run-1") / "planned_character_registry.json"
    registry_doc = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry_doc["data"]["顾迟"]["status"] == "canon_active"
    with db.connect() as conn:
        profile = CharacterProfilesRepo().get(conn, book_id="book-1", canonical_name="顾迟")
        assert profile is not None
    freeze_e = orchestrator.run_writer.get_freeze_record("run-1", "freeze_e")
    assert freeze_e is not None
    assert freeze_e.status == "frozen"


def test_batch_workflow_execute_current_chapter_freezes_e_and_persists_memory_writeback_after_acceptance(
    tmp_path: Path,
) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    chapter_package_path = planner_orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json"
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
    chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
    chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    planner_orchestrator.confirm_chapter_package(run_id="run-1")
    _write_accepted_review_decision(planner_orchestrator, run_id="run-1", chapter_id=chapter_id)

    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        workflow.initialize_workflow(run_id="run-1", book_id="book-1", product_mode="batch")
        workflow.prepare_execution(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
            product_mode="batch",
        )
        workflow.continue_after_execution_review(run_id="run-1")
        result = workflow.execute_current_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            product_mode="batch",
        )
        conn.commit()

    assert result["canon_ready"] is True
    assert result["accepted_for_writeback"] is True
    assert result["review_decision_status"] == "accepted"
    assert result["writeback_committed"] is True
    assert "顾迟" in result["memory_writeback"]["activated_planned_characters"]
    run_dir = workflow.run_writer.layout.run_dir("run-1")
    assert (run_dir / "memory_writeback.json").exists()
    freeze_e = workflow.run_writer.get_freeze_record("run-1", "freeze_e")
    assert freeze_e is not None
    assert freeze_e.status == "frozen"
    draft_index_doc = json.loads((run_dir / "draft_retention_index.json").read_text(encoding="utf-8"))
    draft_record = draft_index_doc["data"]["drafts"]["draft-001"]
    assert draft_record["retention_status"] == "accepted"
    assert draft_record["eligible_for_writeback"] is True
    assert draft_record["eligible_for_canon"] is True
    assert draft_record["memory_writeback_source_path"].endswith("memory_writeback.json")


def _prepare_batch_execution_workflow(
    tmp_path: Path,
) -> tuple[NovelAgentDB, WriterLayeredGenerationOrchestrator, WriterInteractiveWorkflow, str]:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    chapter_package_path = planner_orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json"
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
    chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
    chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    planner_orchestrator.confirm_chapter_package(run_id="run-1")

    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        workflow.initialize_workflow(run_id="run-1", book_id="book-1", product_mode="batch")
        workflow.prepare_execution(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
            product_mode="batch",
        )
        workflow.continue_after_execution_review(run_id="run-1")

    return db, planner_orchestrator, workflow, chapter_id


def test_batch_workflow_execute_current_chapter_routes_revise_length_to_wait_length_review_without_writeback(
    tmp_path: Path,
) -> None:
    db, planner_orchestrator, workflow, chapter_id = _prepare_batch_execution_workflow(tmp_path)
    _write_revise_length_review_decision(planner_orchestrator, run_id="run-1", chapter_id=chapter_id)

    with db.connect() as conn:
        db.init_schema(conn)
        result = workflow.execute_current_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            product_mode="batch",
        )

    state = workflow.load_workflow_state(run_id="run-1")
    resumed_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-1")
    freeze_c = workflow.run_writer.get_freeze_record("run-1", "freeze_c")
    freeze_d = workflow.run_writer.get_freeze_record("run-1", "freeze_d")
    freeze_e = workflow.run_writer.get_freeze_record("run-1", "freeze_e")

    assert result["canon_ready"] is True
    assert result["review_decision_status"] == "revise_length"
    assert result["accepted_for_writeback"] is False
    assert result["writeback_committed"] is False
    assert result["memory_writeback"] == {}
    assert state is not None
    assert state["current_stage"] == "wait_length_review"
    assert state["last_rollback"] is None
    assert state["terminal_stage"] is None
    assert state["pending_checkpoint"]["stage"] == "wait_length_review"
    assert resumed_checkpoint is not None
    assert resumed_checkpoint["stage"] == "wait_length_review"
    assert freeze_c is not None
    assert freeze_c.status == "frozen"
    assert freeze_d is not None
    assert freeze_d.status == "frozen"
    assert freeze_e is None


def test_chapter_length_plan_review_sits_between_freeze_c_and_freeze_d(tmp_path: Path) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )
    workflow.initialize_workflow(run_id="run-1", book_id="book-1", product_mode="assist")

    workflow.continue_after_chapter_review(run_id="run-1")
    state = workflow.load_workflow_state(run_id="run-1")
    length_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-1")
    run_dir = workflow.run_writer.layout.run_dir("run-1")
    length_plan_doc = json.loads((run_dir / "chapter_length_plan.json").read_text(encoding="utf-8"))
    chapter_id = str(length_plan_doc["data"]["budgets"][0]["chapter_id"])
    target_chars = int(length_plan_doc["data"]["budgets"][0]["target_chars"])

    assert state is not None
    assert state["current_stage"] == "wait_length_review"
    assert length_checkpoint is not None
    assert length_checkpoint["stage"] == "wait_length_review"

    workflow.continue_after_length_review(run_id="run-1")
    with db.connect() as conn:
        db.init_schema(conn)
        workflow.prepare_execution(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
            product_mode="assist",
        )

    execution_input_doc = json.loads((run_dir / "chapter_execution_input.json").read_text(encoding="utf-8"))
    budget_doc = json.loads((run_dir / "chapter_length_budget.json").read_text(encoding="utf-8"))
    assert execution_input_doc["data"]["length_budget"]["target_chars"] == target_chars
    assert budget_doc["data"]["target_chars"] == target_chars


def test_continue_after_length_review_applies_interactive_length_overrides(tmp_path: Path) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )
    workflow.initialize_workflow(run_id="run-1", book_id="book-1", product_mode="assist")
    workflow.continue_after_chapter_review(run_id="run-1")
    run_dir = workflow.run_writer.layout.run_dir("run-1")
    original_plan = _load_run_artifact_data(run_dir / "chapter_length_plan.json")
    first_chapter_id = str(original_plan["budgets"][0]["chapter_id"])

    workflow.continue_after_length_review(
        run_id="run-1",
        default_target_chars=3000,
        chapter_overrides={
            first_chapter_id: {
                "target_chars": 3600,
                "min_chars": 3200,
                "max_chars": 3900,
                "reason": "interactive_expansion",
                "note": "加强本章过渡铺垫。",
            },
            "chapter-extra": {
                "target_chars": 1800,
                "min_chars": 1500,
                "max_chars": 2100,
                "reason": "quiet_buffer",
            },
        },
    )

    updated_plan = _load_run_artifact_data(run_dir / "chapter_length_plan.json")
    updated_budgets = {str(item["chapter_id"]): item for item in updated_plan["budgets"]}
    state = workflow.load_workflow_state(run_id="run-1")

    assert updated_plan["default_target_chars"] == 3000
    assert updated_plan["default_min_chars"] == 2550
    assert updated_plan["default_max_chars"] == 3450
    assert updated_budgets[first_chapter_id]["target_chars"] == 3600
    assert updated_budgets[first_chapter_id]["min_chars"] == 3200
    assert updated_budgets[first_chapter_id]["max_chars"] == 3900
    assert updated_budgets[first_chapter_id]["focus_reason"] == "interactive_expansion"
    assert "加强本章过渡铺垫。" in updated_budgets[first_chapter_id]["expansion_notes"]
    assert updated_budgets["chapter-extra"]["target_chars"] == 1800
    assert "chapter-extra" in updated_plan["focus_chapter_ids"]
    assert "已在 wait_length_review 通过交互输入更新章节长度计划。" in updated_plan["review_notes"]
    assert state is not None
    assert state["current_stage"] == "length_confirmed"


def test_revise_length_updates_chapter_length_plan_before_rewrite(tmp_path: Path) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    planner_orchestrator.confirm_chapter_package(run_id="run-1")
    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )
    workflow.initialize_workflow(run_id="run-1", book_id="book-1", product_mode="assist")
    workflow.prepare_chapter_length_plan(run_id="run-1", product_mode="assist")
    workflow.continue_after_length_review(run_id="run-1")

    run_dir = workflow.run_writer.layout.run_dir("run-1")
    length_plan_doc = json.loads((run_dir / "chapter_length_plan.json").read_text(encoding="utf-8"))
    chapter_id = str(length_plan_doc["data"]["budgets"][0]["chapter_id"])
    with db.connect() as conn:
        db.init_schema(conn)
        workflow.prepare_execution(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
            product_mode="assist",
        )
    _write_revise_length_review_decision(planner_orchestrator, run_id="run-1", chapter_id=chapter_id)

    outcome = workflow.continue_after_chapter_acceptance(run_id="run-1")
    updated_plan_doc = json.loads((run_dir / "chapter_length_plan.json").read_text(encoding="utf-8"))
    updated_budget = next(
        item for item in updated_plan_doc["data"]["budgets"] if item["chapter_id"] == chapter_id
    )

    assert outcome["stage"] == "wait_length_review"
    assert updated_budget["target_chars"] == 3200
    assert updated_budget["min_chars"] == 2800
    assert updated_budget["max_chars"] == 3600

    workflow.continue_after_length_review(run_id="run-1")
    with db.connect() as conn:
        db.init_schema(conn)
        workflow.prepare_execution(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
            product_mode="assist",
        )
    rewritten_input_doc = json.loads((run_dir / "chapter_execution_input.json").read_text(encoding="utf-8"))
    assert rewritten_input_doc["data"]["length_budget"]["target_chars"] == 3200


def test_batch_workflow_execute_current_chapter_routes_replan_chapter_to_wait_chapter_review_without_writeback(
    tmp_path: Path,
) -> None:
    db, planner_orchestrator, workflow, chapter_id = _prepare_batch_execution_workflow(tmp_path)
    _write_replan_review_decision(planner_orchestrator, run_id="run-1", chapter_id=chapter_id)

    with db.connect() as conn:
        db.init_schema(conn)
        result = workflow.execute_current_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            product_mode="batch",
        )

    state = workflow.load_workflow_state(run_id="run-1")
    resumed_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-1")
    freeze_c = workflow.run_writer.get_freeze_record("run-1", "freeze_c")
    freeze_d = workflow.run_writer.get_freeze_record("run-1", "freeze_d")
    freeze_e = workflow.run_writer.get_freeze_record("run-1", "freeze_e")

    assert result["canon_ready"] is True
    assert result["review_decision_status"] == "replan_chapter"
    assert result["accepted_for_writeback"] is False
    assert result["writeback_committed"] is False
    assert result["memory_writeback"] == {}
    assert state is not None
    assert state["current_stage"] == "wait_chapter_review"
    assert state["last_rollback"] is None
    assert state["terminal_stage"] is None
    assert state["pending_checkpoint"]["stage"] == "wait_chapter_review"
    assert resumed_checkpoint is not None
    assert resumed_checkpoint["stage"] == "wait_chapter_review"
    assert freeze_c is not None
    assert freeze_c.status == "frozen"
    assert freeze_d is not None
    assert freeze_d.status == "frozen"
    assert freeze_e is None


def test_batch_workflow_execute_current_chapter_routes_discarded_to_halted_without_writeback(
    tmp_path: Path,
) -> None:
    db, planner_orchestrator, workflow, chapter_id = _prepare_batch_execution_workflow(tmp_path)
    _write_discarded_review_decision(planner_orchestrator, run_id="run-1", chapter_id=chapter_id)

    with db.connect() as conn:
        db.init_schema(conn)
        result = workflow.execute_current_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            product_mode="batch",
        )

    state = workflow.load_workflow_state(run_id="run-1")
    resumed_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-1")
    freeze_c = workflow.run_writer.get_freeze_record("run-1", "freeze_c")
    freeze_d = workflow.run_writer.get_freeze_record("run-1", "freeze_d")
    freeze_e = workflow.run_writer.get_freeze_record("run-1", "freeze_e")

    assert result["canon_ready"] is True
    assert result["review_decision_status"] == "discarded"
    assert result["accepted_for_writeback"] is False
    assert result["writeback_committed"] is False
    assert result["memory_writeback"] == {}
    assert state is not None
    assert state["current_stage"] == "halted"
    assert state["last_rollback"] is None
    assert state["pending_checkpoint"] is None
    assert state["terminal_stage"]["stage"] == "halted"
    assert resumed_checkpoint is None
    assert freeze_c is not None
    assert freeze_c.status == "frozen"
    assert freeze_d is not None
    assert freeze_d.status == "frozen"
    assert freeze_e is None


def test_rollback_manager_supports_progressive_and_cascade_rollbacks(tmp_path: Path) -> None:
    db, orchestrator = _prepare_freeze_c_chain(tmp_path)
    chapter_package_path = orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json"
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
    chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
    chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    orchestrator.confirm_chapter_package(run_id="run-1")
    _write_accepted_review_decision(orchestrator, run_id="run-1", chapter_id=chapter_id)

    executor = RestrictedWriterExecutor(
        repo_root=orchestrator.repo_root,
        run_writer=orchestrator.run_writer,
        model_client=None,
    )
    with db.connect() as conn:
        executor.prepare_execution_input(conn, run_id="run-1", book_id="book-1", chapter_id=chapter_id)
        executor.confirm_freeze_d(run_id="run-1")
        executor.execute_frozen_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            commit_writeback=True,
            auto_freeze_e=True,
        )
        conn.commit()

    rollback_manager = WriterRollbackManager(run_writer=orchestrator.run_writer)
    event_d = rollback_manager.rollback_after_failure(run_id="run-1", failure_count=1, reason="第一次失败")
    assert event_d.target_freeze_stage == "freeze_d"
    freeze_e = orchestrator.run_writer.get_freeze_record("run-1", "freeze_e")
    assert freeze_e is not None
    assert freeze_e.status == "invalidated"

    event_c = rollback_manager.rollback_after_failure(run_id="run-1", failure_count=2, reason="第二次失败")
    assert event_c.target_freeze_stage == "freeze_c"
    freeze_d = orchestrator.run_writer.get_freeze_record("run-1", "freeze_d")
    assert freeze_d is not None
    assert freeze_d.status == "invalidated"

    event_b = rollback_manager.cascade_for_character_cast_change(run_id="run-1", reason="人物补充方案修改")
    assert event_b.target_freeze_stage == "freeze_a"
    freeze_b = orchestrator.run_writer.get_freeze_record("run-1", "freeze_b")
    freeze_c = orchestrator.run_writer.get_freeze_record("run-1", "freeze_c")
    assert freeze_b is not None
    assert freeze_c is not None
    assert freeze_b.status == "invalidated"
    assert freeze_c.status == "invalidated"


def test_workflow_modes_and_resume_checkpoint_are_recorded(tmp_path: Path) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    workflow_db, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )
    assert workflow_db.db_path == db.db_path

    with db.connect() as conn:
        db.init_schema(conn)
        assist_state = workflow.initialize_workflow(run_id="run-assist", book_id="book-1", product_mode="assist")
        batch_state = workflow.initialize_workflow(run_id="run-batch", book_id="book-1", product_mode="batch")
        auto_state = workflow.initialize_workflow(run_id="run-auto", book_id="book-1", product_mode="auto_novel")

        workflow.prepare_planning(
            conn,
            run_id="run-assist",
            book_id="book-1",
            product_mode="assist",
            intent_payload={
                "major_characters": ["沈青"],
                "desired_actions": ["继续追查旧案"],
                "avoidances": [],
                "preferred_outcome": "保留悬念",
                "notes": "",
            },
        )
        workflow.prepare_planning(
            conn,
            run_id="run-batch",
            book_id="book-1",
            product_mode="batch",
            intent_payload={
                "major_characters": ["沈青"],
                "desired_actions": ["继续追查旧案"],
                "avoidances": [],
                "preferred_outcome": "保留悬念",
                "notes": "",
            },
        )
        resume_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-assist")
        batch_resume_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-batch")
        batch_after_planning = workflow.load_workflow_state(run_id="run-batch")

    assert "freeze_a_review" in assist_state["confirmation_points"]
    assert "freeze_a_review" not in batch_state["confirmation_points"]
    assert "batch_review" in batch_state["confirmation_points"]
    assert auto_state["confirmation_points"] == []
    assert resume_checkpoint is not None
    assert resume_checkpoint["stage"] == "freeze_a_review"
    assert batch_resume_checkpoint is None
    assert batch_after_planning is not None
    assert batch_after_planning["current_stage"] == "freeze_a"
    assert workflow.run_writer.get_freeze_record("run-batch", "freeze_a") is not None


def test_workflow_waiting_review_states_are_persisted_and_resumable(tmp_path: Path) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    workflow_db, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )
    assert workflow_db.db_path == db.db_path

    workflow.initialize_workflow(run_id="run-wait-states", book_id="book-1", product_mode="assist")
    run_dir = workflow.run_writer.layout.run_dir("run-wait-states")
    continuity_path = run_dir / "continuity_report.json"
    continuity_path.write_text("{}", encoding="utf-8")

    acceptance_checkpoint = workflow.register_wait_chapter_acceptance(
        run_id="run-wait-states",
        artifact_path=str(continuity_path),
        source="test_acceptance_wait",
    )
    state_after_acceptance = workflow.load_workflow_state(run_id="run-wait-states")
    resumed_acceptance = workflow.resume_from_latest_checkpoint(run_id="run-wait-states")

    assert acceptance_checkpoint["stage"] == "wait_chapter_acceptance"
    assert state_after_acceptance is not None
    assert state_after_acceptance["current_stage"] == "wait_chapter_acceptance"
    assert resumed_acceptance is not None
    assert resumed_acceptance["stage"] == "wait_chapter_acceptance"
    assert resumed_acceptance["artifact_path"] == str(continuity_path)

    length_checkpoint = workflow.register_wait_length_review(
        run_id="run-wait-states",
        artifact_path=str(run_dir / "chapter_length_plan.json"),
        source="test_length_wait",
    )
    state_after_length = workflow.load_workflow_state(run_id="run-wait-states")
    resumed_length = workflow.resume_from_latest_checkpoint(run_id="run-wait-states")

    assert length_checkpoint["stage"] == "wait_length_review"
    assert state_after_length is not None
    assert state_after_length["current_stage"] == "wait_length_review"
    assert resumed_length is not None
    assert resumed_length["stage"] == "wait_length_review"

    chapter_review_checkpoint = workflow.register_wait_chapter_review(
        run_id="run-wait-states",
        artifact_path=str(run_dir / "generation_review_decision.json"),
        source="test_chapter_review_wait",
    )
    state_after_chapter_review = workflow.load_workflow_state(run_id="run-wait-states")
    resumed_chapter_review = workflow.resume_from_latest_checkpoint(run_id="run-wait-states")

    assert chapter_review_checkpoint["stage"] == "wait_chapter_review"
    assert state_after_chapter_review is not None
    assert state_after_chapter_review["current_stage"] == "wait_chapter_review"
    assert resumed_chapter_review is not None
    assert resumed_chapter_review["stage"] == "wait_chapter_review"

    halted_checkpoint = workflow.register_halted(
        run_id="run-wait-states",
        artifact_path=str(run_dir / "generation_review_decision.json"),
        source="test_halted_wait",
    )
    state_after_halted = workflow.load_workflow_state(run_id="run-wait-states")
    resumed_halted = workflow.resume_from_latest_checkpoint(run_id="run-wait-states")

    assert halted_checkpoint["stage"] == "halted"
    assert state_after_halted is not None
    assert state_after_halted["current_stage"] == "halted"
    assert state_after_halted["pending_checkpoint"] is None
    assert state_after_halted["terminal_stage"]["stage"] == "halted"
    assert resumed_halted is None

    checkpoints_path = run_dir / "workflow_checkpoints.json"
    checkpoints_doc = json.loads(checkpoints_path.read_text(encoding="utf-8"))
    checkpoint_stages = [item["stage"] for item in checkpoints_doc["data"]["checkpoints"]]
    assert "wait_chapter_acceptance" in checkpoint_stages
    assert "wait_length_review" in checkpoint_stages
    assert "wait_chapter_review" in checkpoint_stages
    assert "halted" not in checkpoint_stages


def test_freeze_a_can_consume_user_edited_character_supplement_files(tmp_path: Path) -> None:
    db, orchestrator = _build_orchestrator(tmp_path)
    book_id = "book-1"

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        _seed_profile(conn, book_id=book_id, canonical_name="沈青")
        _seed_fragment_card(conn)
        conn.commit()

        orchestrator.prepare_freeze_a(
            conn,
            run_id="run-edit-plan",
            book_id=book_id,
            intent_payload={
                "major_characters": ["沈青", "顾迟"],
                "desired_actions": ["安排援军接应并继续追查旧案"],
                "avoidances": ["不要突然告白"],
                "preferred_outcome": "阶段性脱险但留下更深疑点",
                "notes": "需要一个新的反派压力位。",
            },
            character_seed_payloads=[
                {
                    "seed_id": "seed-1",
                    "display_name_hint": "顾迟",
                    "faction": "友方",
                    "core_concept": "外冷内热的情报中间人",
                    "must_keep": ["冷静", "克制"],
                    "must_avoid": ["喧宾夺主"],
                    "relationship_entry": {
                        "target_character": "沈青",
                        "initial_state": "互相试探",
                        "allowed_target_state_in_this_batch": "有限合作",
                    },
                    "world_constraints": ["不得拥有超出现有体系的能力"],
                }
            ],
        )

    planned_profiles_path = orchestrator.run_writer.layout.run_dir("run-edit-plan") / "planned_character_profiles.json"
    planned_profiles_doc = json.loads(planned_profiles_path.read_text(encoding="utf-8"))
    planned_profiles_doc["data"][0]["canonical_name"] = "顾迟-修订版"
    planned_profiles_path.write_text(
        json.dumps(planned_profiles_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    freeze_a_paths = orchestrator.confirm_freeze_a(run_id="run-edit-plan")
    assert Path(freeze_a_paths["freeze.json"]).exists()

    frozen_profiles = orchestrator._load_frozen_artifact(  # noqa: SLF001
        "run-edit-plan",
        "freeze_a",
        "planned_character_profiles.json",
    )
    assert frozen_profiles[0]["canonical_name"] == "顾迟-修订版"


def test_assist_workflow_records_confirmations_and_approves_writeback(tmp_path: Path) -> None:
    db, planner_orchestrator = _build_orchestrator(tmp_path)
    book_id = "book-1"

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=planner_orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        _seed_profile(conn, book_id=book_id, canonical_name="沈青")
        _seed_fragment_card(conn)
        conn.commit()

    workflow_db, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )
    assert workflow_db.db_path == db.db_path

    with db.connect() as conn:
        db.init_schema(conn)
        workflow.initialize_workflow(run_id="run-assist-full", book_id=book_id, product_mode="assist")
        workflow.prepare_planning(
            conn,
            run_id="run-assist-full",
            book_id=book_id,
            product_mode="assist",
            intent_payload={
                "major_characters": ["沈青", "顾迟"],
                "desired_actions": ["安排援军接应并继续追查旧案"],
                "avoidances": ["不要突然告白"],
                "preferred_outcome": "阶段性脱险但留下更深疑点",
                "notes": "需要一个新的反派压力位。",
            },
            character_seed_payloads=[
                {
                    "seed_id": "seed-1",
                    "display_name_hint": "顾迟",
                    "faction": "友方",
                    "core_concept": "外冷内热的情报中间人",
                    "must_keep": ["冷静", "克制"],
                    "must_avoid": ["喧宾夺主"],
                    "relationship_entry": {
                        "target_character": "沈青",
                        "initial_state": "互相试探",
                        "allowed_target_state_in_this_batch": "有限合作",
                    },
                    "world_constraints": ["不得拥有超出现有体系的能力"],
                }
            ],
        )
        planning_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-assist-full")
        assert planning_checkpoint is not None
        assert planning_checkpoint["stage"] == "freeze_a_review"
        workflow.continue_after_planning_review(run_id="run-assist-full")

        workflow.prepare_batch_plan(
            conn,
            run_id="run-assist-full",
            book_id=book_id,
            product_mode="assist",
            target_chapter_count=2,
        )
        batch_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-assist-full")
        assert batch_checkpoint is not None
        assert batch_checkpoint["stage"] == "batch_review"
        workflow.continue_after_batch_review(run_id="run-assist-full")

        workflow.prepare_chapter_package(
            run_id="run-assist-full",
            book_id=book_id,
            product_mode="assist",
            chapter_count=2,
        )
        chapter_package_path = workflow.run_writer.layout.run_dir("run-assist-full") / "chapter_package.json"
        chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
        chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
        chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
        chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
        chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        chapter_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-assist-full")
        assert chapter_checkpoint is not None
        assert chapter_checkpoint["stage"] == "chapter_review"
        workflow.continue_after_chapter_review(run_id="run-assist-full")

        workflow.prepare_execution(
            conn,
            run_id="run-assist-full",
            book_id=book_id,
            chapter_id=chapter_id,
            product_mode="assist",
        )
        execution_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-assist-full")
        assert execution_checkpoint is not None
        assert execution_checkpoint["stage"] == "freeze_d_review"
        workflow.continue_after_execution_review(run_id="run-assist-full")

        execution_result = workflow.execute_current_chapter(
            conn,
            run_id="run-assist-full",
            book_id=book_id,
            product_mode="assist",
        )
        assert execution_result["canon_ready"] is True
        acceptance_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-assist-full")
        assert acceptance_checkpoint is not None
        assert acceptance_checkpoint["stage"] == "wait_chapter_acceptance"
        _write_accepted_review_decision(planner_orchestrator, run_id="run-assist-full", chapter_id=chapter_id)
        writeback_checkpoint = workflow.continue_after_chapter_acceptance(run_id="run-assist-full")
        assert writeback_checkpoint["stage"] == "writeback_review"

        writeback_result = workflow.approve_writeback(
            conn,
            run_id="run-assist-full",
            book_id=book_id,
        )
        conn.commit()

    assert "顾迟" in writeback_result["activated_planned_characters"]

    checkpoints_path = workflow.run_writer.layout.run_dir("run-assist-full") / "workflow_checkpoints.json"
    checkpoints_doc = json.loads(checkpoints_path.read_text(encoding="utf-8"))
    checkpoints = checkpoints_doc["data"]["checkpoints"]
    confirmed_by_stage = {item["stage"]: item for item in checkpoints if item["status"] == "confirmed"}
    assert confirmed_by_stage["freeze_a_review"]["source"] == "continue_after_planning_review"
    assert confirmed_by_stage["batch_review"]["source"] == "continue_after_batch_review"
    assert confirmed_by_stage["chapter_review"]["source"] == "continue_after_chapter_review"
    assert confirmed_by_stage["freeze_d_review"]["source"] == "continue_after_execution_review"
    assert confirmed_by_stage["wait_chapter_acceptance"]["source"] == "continue_after_chapter_acceptance"
    assert confirmed_by_stage["wait_chapter_acceptance"]["confirmed_at"]
    assert confirmed_by_stage["writeback_review"]["source"] == "approve_writeback"
    assert confirmed_by_stage["writeback_review"]["confirmed_at"]

    registry_path = workflow.run_writer.layout.run_dir("run-assist-full") / "planned_character_registry.json"
    registry_doc = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry_doc["data"]["顾迟"]["status"] == "canon_active"
    freeze_e = workflow.run_writer.get_freeze_record("run-assist-full", "freeze_e")
    assert freeze_e is not None
    assert freeze_e.status == "frozen"
    assert {artifact.name for artifact in freeze_e.artifacts} >= {
        "chapter_execution_input.json",
        "continuity_report.json",
        "state_delta.json",
        "memory_writeback.json",
    }

    draft_index_path = workflow.run_writer.layout.run_dir("run-assist-full") / "draft_retention_index.json"
    draft_index_doc = json.loads(draft_index_path.read_text(encoding="utf-8"))
    accepted_record = draft_index_doc["data"]["drafts"]["draft-001"]
    assert accepted_record["retention_status"] == "accepted"
    assert accepted_record["eligible_for_writeback"] is True
    assert accepted_record["eligible_for_canon"] is True
    assert accepted_record["memory_writeback_source_path"].endswith("memory_writeback.json")
    assert accepted_record["archived_artifacts"]["memory_writeback.json"].endswith(
        "drafts/draft-001/memory_writeback.json"
    )

    run_dir = workflow.run_writer.layout.run_dir("run-assist-full")
    review_decision_doc = json.loads((run_dir / "generation_review_decision.json").read_text(encoding="utf-8"))
    review_decision_data = review_decision_doc["data"]
    workflow_state_doc = json.loads((run_dir / "workflow_state.json").read_text(encoding="utf-8"))
    workflow_state = workflow_state_doc["data"]
    assert workflow_state["current_stage"] == "completed"
    assert workflow_state["current_decision_id"] == review_decision_data["decision_id"]
    assert workflow_state["pending_checkpoint"] is None
    assert workflow_state["terminal_stage"]["stage"] == "completed"
    assert workflow_state["terminal_stage"]["source"] == "approve_writeback"
    assert (run_dir / "book_continuation_plan.json").exists()
    assert (run_dir / "world_expansion_pack.json").exists()
    assert (run_dir / "character_requirement_report.json").exists()
    assert (run_dir / "character_cast_request.json").exists()
    assert (run_dir / "character_cast_plan.json").exists()
    assert (run_dir / "planned_character_profiles.json").exists()
    assert (run_dir / "character_introduction_plan.json").exists()
    assert (run_dir / "batch_plan.json").exists()
    assert (run_dir / "chapter_package.json").exists()
    assert (run_dir / "state_delta.json").exists()


def test_approve_writeback_rejects_non_accepted_review_decision(tmp_path: Path) -> None:
    db, planner_orchestrator = _build_orchestrator(tmp_path)
    book_id = "book-1"

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=planner_orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        _seed_profile(conn, book_id=book_id, canonical_name="沈青")
        _seed_fragment_card(conn)
        conn.commit()

    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        workflow.initialize_workflow(run_id="run-assist-guard", book_id=book_id, product_mode="assist")
        workflow.prepare_planning(
            conn,
            run_id="run-assist-guard",
            book_id=book_id,
            product_mode="assist",
            intent_payload={
                "major_characters": ["沈青", "顾迟"],
                "desired_actions": ["安排援军接应并继续追查旧案"],
                "avoidances": ["不要突然告白"],
                "preferred_outcome": "阶段性脱险但留下更深疑点",
                "notes": "需要一个新的反派压力位。",
            },
            character_seed_payloads=[
                {
                    "seed_id": "seed-1",
                    "display_name_hint": "顾迟",
                    "faction": "友方",
                    "core_concept": "外冷内热的情报中间人",
                    "must_keep": ["冷静", "克制"],
                    "must_avoid": ["喧宾夺主"],
                    "relationship_entry": {
                        "target_character": "沈青",
                        "initial_state": "互相试探",
                        "allowed_target_state_in_this_batch": "有限合作",
                    },
                    "world_constraints": ["不得拥有超出现有体系的能力"],
                }
            ],
        )
        workflow.continue_after_planning_review(run_id="run-assist-guard")
        workflow.prepare_batch_plan(
            conn,
            run_id="run-assist-guard",
            book_id=book_id,
            product_mode="assist",
            target_chapter_count=2,
        )
        workflow.continue_after_batch_review(run_id="run-assist-guard")
        workflow.prepare_chapter_package(
            run_id="run-assist-guard",
            book_id=book_id,
            product_mode="assist",
            chapter_count=2,
        )
        chapter_package_path = workflow.run_writer.layout.run_dir("run-assist-guard") / "chapter_package.json"
        chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
        chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
        chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
        chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
        chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        workflow.continue_after_chapter_review(run_id="run-assist-guard")
        workflow.prepare_execution(
            conn,
            run_id="run-assist-guard",
            book_id=book_id,
            chapter_id=chapter_id,
            product_mode="assist",
        )
        workflow.continue_after_execution_review(run_id="run-assist-guard")
        execution_result = workflow.execute_current_chapter(
            conn,
            run_id="run-assist-guard",
            book_id=book_id,
            product_mode="assist",
        )
        assert execution_result["canon_ready"] is True
        _write_discarded_review_decision(planner_orchestrator, run_id="run-assist-guard", chapter_id=chapter_id)

        with pytest.raises(ValueError, match="generation_review_decision.status=accepted"):
            workflow.approve_writeback(
                conn,
                run_id="run-assist-guard",
                book_id=book_id,
            )

    memory_writeback_path = workflow.run_writer.layout.run_dir("run-assist-guard") / "memory_writeback.json"
    assert not memory_writeback_path.exists()
    registry_path = workflow.run_writer.layout.run_dir("run-assist-guard") / "planned_character_registry.json"
    assert not registry_path.exists()
    with db.connect() as conn:
        profile = CharacterProfilesRepo().get(conn, book_id="book-1", canonical_name="顾迟")
        assert profile is None


def test_approve_writeback_rejects_missing_accepted_review_decision(tmp_path: Path) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    chapter_package_path = planner_orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json"
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
    chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
    chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    planner_orchestrator.confirm_chapter_package(run_id="run-1")

    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        workflow.initialize_workflow(run_id="run-1", book_id="book-1", product_mode="assist")
        workflow.prepare_execution(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
            product_mode="assist",
        )
        workflow.continue_after_execution_review(run_id="run-1")
        execution_result = workflow.execute_current_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            product_mode="assist",
        )
        assert execution_result["canon_ready"] is True

        checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-1")
        assert checkpoint is not None
        assert checkpoint["stage"] == "wait_chapter_acceptance"

        with pytest.raises(ValueError, match="generation_review_decision.status=accepted"):
            workflow.approve_writeback(
                conn,
                run_id="run-1",
                book_id="book-1",
            )

    run_dir = workflow.run_writer.layout.run_dir("run-1")
    assert not (run_dir / "memory_writeback.json").exists()
    assert not (run_dir / "planned_character_registry.json").exists()
    freeze_e = workflow.run_writer.get_freeze_record("run-1", "freeze_e")
    assert freeze_e is None
    draft_index_doc = json.loads((run_dir / "draft_retention_index.json").read_text(encoding="utf-8"))
    draft_record = draft_index_doc["data"]["drafts"]["draft-001"]
    assert draft_record["retention_status"] == "drafted"
    assert draft_record["eligible_for_writeback"] is False
    assert draft_record["eligible_for_canon"] is False


def test_continue_after_chapter_acceptance_routes_review_decision_statuses(tmp_path: Path) -> None:
    db, planner_orchestrator = _build_orchestrator(tmp_path)
    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )

    cases = [
        {
            "run_id": "run-accept-assist",
            "product_mode": "assist",
            "writer": _write_accepted_review_decision,
            "expected_stage": "writeback_review",
            "expected_pending_stage": "writeback_review",
            "expected_resume_stage": "writeback_review",
            "expects_length_plan_update": False,
            "expects_chapter_replan_request": False,
        },
        {
            "run_id": "run-accept-batch",
            "product_mode": "batch",
            "writer": _write_accepted_review_decision,
            "expected_stage": "freeze_e",
            "expected_pending_stage": None,
            "expected_resume_stage": None,
            "expects_length_plan_update": False,
            "expects_chapter_replan_request": False,
        },
        {
            "run_id": "run-revise-length",
            "product_mode": "assist",
            "writer": _write_revise_length_review_decision,
            "expected_stage": "wait_length_review",
            "expected_pending_stage": "wait_length_review",
            "expected_resume_stage": "wait_length_review",
            "expects_length_plan_update": True,
            "expects_chapter_replan_request": False,
        },
        {
            "run_id": "run-replan-chapter",
            "product_mode": "assist",
            "writer": _write_replan_review_decision,
            "expected_stage": "wait_chapter_review",
            "expected_pending_stage": "wait_chapter_review",
            "expected_resume_stage": "wait_chapter_review",
            "expects_length_plan_update": False,
            "expects_chapter_replan_request": True,
        },
        {
            "run_id": "run-discarded",
            "product_mode": "assist",
            "writer": _write_discarded_review_decision,
            "expected_stage": "halted",
            "expected_pending_stage": None,
            "expected_resume_stage": None,
            "expects_length_plan_update": False,
            "expects_chapter_replan_request": False,
        },
    ]

    for case in cases:
        run_id = str(case["run_id"])
        workflow.initialize_workflow(run_id=run_id, book_id="book-1", product_mode=str(case["product_mode"]))
        run_dir = workflow.run_writer.layout.run_dir(run_id)
        continuity_path = run_dir / "continuity_report.json"
        continuity_path.write_text("{}", encoding="utf-8")
        (run_dir / "length_plan_update.json").write_text('{"stale": true}', encoding="utf-8")
        (run_dir / "chapter_replan_request.json").write_text('{"stale": true}', encoding="utf-8")
        workflow.register_wait_chapter_acceptance(
            run_id=run_id,
            artifact_path=str(continuity_path),
            source="test_wait_acceptance",
        )
        case["writer"](planner_orchestrator, run_id=run_id, chapter_id="chapter-001")

        outcome = workflow.continue_after_chapter_acceptance(run_id=run_id)
        state = workflow.load_workflow_state(run_id=run_id)
        pending_checkpoint = None if state is None else state.get("pending_checkpoint")
        resumed_checkpoint = workflow.resume_from_latest_checkpoint(run_id=run_id)
        decision_doc = json.loads((run_dir / "generation_review_decision.json").read_text(encoding="utf-8"))
        decision_data = decision_doc["data"]
        draft_index_doc = json.loads((run_dir / "draft_retention_index.json").read_text(encoding="utf-8"))
        draft_record = draft_index_doc["data"]["drafts"][decision_data["draft_id"]]

        assert outcome["stage"] == case["expected_stage"]
        assert state is not None
        assert state["current_stage"] == case["expected_stage"]
        assert decision_data["run_id"] == run_id
        assert decision_data["chapter_id"] == "chapter-001"
        assert decision_data["draft_id"]
        assert state["current_decision_id"] == decision_data["decision_id"]
        assert draft_record["draft_id"] == decision_data["draft_id"]
        assert draft_record["decision_id"] == decision_data["decision_id"]
        assert draft_record["decision_status"] == decision_data["status"]
        assert draft_record["archived_artifacts"]["generation_review_decision.json"].endswith(
            f"drafts/{decision_data['draft_id']}/generation_review_decision.json"
        )
        length_plan_update_path = run_dir / "length_plan_update.json"
        chapter_replan_request_path = run_dir / "chapter_replan_request.json"
        if case["expects_length_plan_update"]:
            length_plan_update_doc = json.loads(length_plan_update_path.read_text(encoding="utf-8"))
            assert length_plan_update_doc["data"]["decision_id"] == decision_data["decision_id"]
            assert length_plan_update_doc["data"]["chapter_id"] == "chapter-001"
            assert length_plan_update_doc["data"]["reason_code"] == decision_data["reason_code"]
            assert not chapter_replan_request_path.exists()
        else:
            assert not length_plan_update_path.exists()
        if case["expects_chapter_replan_request"]:
            chapter_replan_request_doc = json.loads(chapter_replan_request_path.read_text(encoding="utf-8"))
            assert chapter_replan_request_doc["data"]["decision_id"] == decision_data["decision_id"]
            assert chapter_replan_request_doc["data"]["chapter_id"] == "chapter-001"
            assert chapter_replan_request_doc["data"]["reason_code"] == decision_data["reason_code"]
            assert not length_plan_update_path.exists()
        else:
            assert not chapter_replan_request_path.exists()
        if case["expected_pending_stage"] is None:
            assert pending_checkpoint is None
        else:
            assert pending_checkpoint is not None
            assert pending_checkpoint["stage"] == case["expected_pending_stage"]
        if case["expected_resume_stage"] is None:
            assert resumed_checkpoint is None
        else:
            assert resumed_checkpoint is not None
            assert resumed_checkpoint["stage"] == case["expected_resume_stage"]
        if case["expected_stage"] == "halted":
            assert state["terminal_stage"]["stage"] == "halted"
            assert draft_record["retention_status"] == "discarded"
            assert draft_record["active_for_consumption"] is False
            assert draft_record["eligible_for_writeback"] is False
            assert draft_record["eligible_for_canon"] is False
        elif decision_data["status"] == "accepted":
            assert draft_record["retention_status"] == "accepted"
            assert draft_record["active_for_consumption"] is True
            assert draft_record["eligible_for_writeback"] is True
            assert draft_record["eligible_for_canon"] is True
        else:
            assert draft_record["retention_status"] == "drafted"
            assert draft_record["active_for_consumption"] is True
            assert draft_record["eligible_for_writeback"] is False
            assert draft_record["eligible_for_canon"] is False

        checkpoints_path = run_dir / "workflow_checkpoints.json"
        checkpoints_doc = json.loads(checkpoints_path.read_text(encoding="utf-8"))
        confirmed_stages = {
            item["stage"]
            for item in checkpoints_doc["data"]["checkpoints"]
            if item["status"] == "confirmed"
        }
        assert "wait_chapter_acceptance" in confirmed_stages


@pytest.mark.parametrize(
    ("decision_writer", "expected_stage"),
    [
        (_write_revise_length_review_decision, "wait_length_review"),
        (_write_replan_review_decision, "wait_chapter_review"),
    ],
)
def test_rejection_wait_paths_do_not_invalidate_freezes_or_create_rollbacks(
    tmp_path: Path,
    decision_writer,
    expected_stage: str,
) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    chapter_package_path = planner_orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json"
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_id = str(chapter_package_doc["data"]["chapters"][0]["chapter_id"])
    chapter_package_doc["data"]["chapters"][0]["must_include"].append("顾迟")
    chapter_package_doc["data"]["chapters"][0]["relationship_targets"][0]["required_bridge"] = ["实际行动"]
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    planner_orchestrator.confirm_chapter_package(run_id="run-1")

    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )

    with db.connect() as conn:
        db.init_schema(conn)
        workflow.initialize_workflow(run_id="run-1", book_id="book-1", product_mode="assist")
        workflow.prepare_execution(
            conn,
            run_id="run-1",
            book_id="book-1",
            chapter_id=chapter_id,
            product_mode="assist",
        )
        workflow.continue_after_execution_review(run_id="run-1")
        execution_result = workflow.execute_current_chapter(
            conn,
            run_id="run-1",
            book_id="book-1",
            product_mode="assist",
        )

    assert execution_result["canon_ready"] is True
    decision_writer(planner_orchestrator, run_id="run-1", chapter_id=chapter_id)

    outcome = workflow.continue_after_chapter_acceptance(run_id="run-1")
    state = workflow.load_workflow_state(run_id="run-1")
    run_dir = workflow.run_writer.layout.run_dir("run-1")
    rollback_events_path = run_dir / "rollback_events.json"
    freeze_c = workflow.run_writer.get_freeze_record("run-1", "freeze_c")
    freeze_d = workflow.run_writer.get_freeze_record("run-1", "freeze_d")
    freeze_e = workflow.run_writer.get_freeze_record("run-1", "freeze_e")
    resumed_checkpoint = workflow.resume_from_latest_checkpoint(run_id="run-1")

    assert outcome["stage"] == expected_stage
    assert state is not None
    assert state["current_stage"] == expected_stage
    assert state["last_rollback"] is None
    assert resumed_checkpoint is not None
    assert resumed_checkpoint["stage"] == expected_stage
    assert not rollback_events_path.exists()
    assert freeze_c is not None
    assert freeze_c.status == "frozen"
    assert freeze_d is not None
    assert freeze_d.status == "frozen"
    assert freeze_e is None


def test_wait_chapter_review_can_continue_to_length_review(tmp_path: Path) -> None:
    db, planner_orchestrator = _prepare_freeze_c_chain(tmp_path)
    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )
    run_id = "run-1"
    run_dir = workflow.run_writer.layout.run_dir(run_id)
    chapter_package_path = run_dir / "chapter_package.json"
    workflow.initialize_workflow(run_id=run_id, book_id="book-1", product_mode="assist")
    workflow.register_wait_chapter_review(
        run_id=run_id,
        artifact_path=str(chapter_package_path),
        source="test_replan_continue",
    )

    outcome = workflow.continue_after_chapter_review(run_id=run_id)
    state = workflow.load_workflow_state(run_id=run_id)
    resumed_checkpoint = workflow.resume_from_latest_checkpoint(run_id=run_id)
    checkpoints_doc = json.loads((run_dir / "workflow_checkpoints.json").read_text(encoding="utf-8"))
    confirmed_wait_chapter_review = [
        item
        for item in checkpoints_doc["data"]["checkpoints"]
        if item["stage"] == "wait_chapter_review" and item["status"] == "confirmed"
    ]

    assert "chapter_length_plan" in outcome
    assert state is not None
    assert state["current_stage"] == "wait_length_review"
    assert resumed_checkpoint is not None
    assert resumed_checkpoint["stage"] == "wait_length_review"
    assert confirmed_wait_chapter_review


def test_provisioning_new_draft_marks_previous_draft_as_superseded(tmp_path: Path) -> None:
    db, planner_orchestrator = _build_orchestrator(tmp_path)
    _, workflow = build_writer_workflow(
        repo_root=planner_orchestrator.repo_root,
        db_path=db.db_path,
        runs_dir=planner_orchestrator.run_writer.layout.base_dir,
        dry_run=True,
    )

    run_id = "run-superseded"
    workflow.initialize_workflow(run_id=run_id, book_id="book-1", product_mode="assist")
    run_dir = workflow.run_writer.layout.run_dir(run_id)
    workflow.run_writer.write_text(run_id, "draft.md", "# First Draft")
    workflow.run_writer.write_json(run_id, "continuity_report.json", {"canon_ready": True})
    workflow.run_writer.write_json(run_id, "state_delta.json", {"events": ["first"]})
    workflow._save_workflow_state(  # noqa: SLF001
        run_id,
        {
            **(workflow.load_workflow_state(run_id=run_id) or {}),
            "current_chapter_id": "chapter-001",
            "current_draft_id": "draft-001",
            "current_decision_id": "review-chapter-001-draft-001",
            "draft_sequence": 1,
        },
    )
    _write_revise_length_review_decision(
        planner_orchestrator,
        run_id=run_id,
        chapter_id="chapter-001",
        draft_id="draft-001",
    )

    state = workflow.load_workflow_state(run_id=run_id)
    assert state is not None
    workflow._normalize_generation_review_decision_artifact(  # noqa: SLF001
        run_id=run_id,
        state=state,
    )
    state = workflow.load_workflow_state(run_id=run_id)
    assert state is not None
    pending_payload = workflow._provision_generation_review_decision_artifact(  # noqa: SLF001
        run_id=run_id,
        state=state,
    )

    draft_index_doc = json.loads((run_dir / "draft_retention_index.json").read_text(encoding="utf-8"))
    old_record = draft_index_doc["data"]["drafts"]["draft-001"]
    new_record = draft_index_doc["data"]["drafts"]["draft-002"]

    assert pending_payload["draft_id"] == "draft-002"
    assert pending_payload["supersedes_draft_id"] == "draft-001"
    assert old_record["retention_status"] == "superseded"
    assert old_record["superseded_by_draft_id"] == "draft-002"
    assert old_record["active_for_consumption"] is False
    assert old_record["eligible_for_writeback"] is False
    assert new_record["retention_status"] == "drafted"
    assert new_record["decision_status"] == ""
    assert new_record["active_for_consumption"] is True
    assert new_record["supersedes_draft_id"] == "draft-001"
    assert (run_dir / "drafts" / "draft-001" / "generation_review_decision.json").exists()
    assert (run_dir / "drafts" / "draft-002" / "generation_review_decision.json").exists()


@pytest.mark.parametrize(
    ("decision_writer", "artifact_name"),
    [
        (_write_revise_length_review_decision, "length_plan_update.json"),
        (_write_replan_review_decision, "chapter_replan_request.json"),
    ],
)
def test_review_rework_artifacts_are_persisted_with_same_chapter_execution_draft(
    tmp_path: Path,
    decision_writer,
    artifact_name: str,
) -> None:
    db, planner_orchestrator, workflow, chapter_id = _prepare_batch_execution_workflow(tmp_path)
    run_id = "run-1"

    with db.connect() as conn:
        db.init_schema(conn)
        execution_result = workflow.execute_current_chapter(
            conn,
            run_id=run_id,
            book_id="book-1",
            product_mode="batch",
        )

    assert execution_result["canon_ready"] is True

    run_dir = workflow.run_writer.layout.run_dir(run_id)
    pending_decision = _load_run_artifact_data(run_dir / "generation_review_decision.json")
    draft_id = str(pending_decision["draft_id"])
    decision_writer(planner_orchestrator, run_id=run_id, chapter_id=chapter_id, draft_id=draft_id)

    workflow.continue_after_chapter_acceptance(run_id=run_id)

    decision_data = _load_run_artifact_data(run_dir / "generation_review_decision.json")
    rework_artifact_data = _load_run_artifact_data(run_dir / artifact_name)
    draft_index_doc = _load_run_artifact_data(run_dir / "draft_retention_index.json")
    draft_record = draft_index_doc["drafts"][draft_id]

    archived_decision_path = Path(draft_record["archived_artifacts"]["generation_review_decision.json"])
    archived_rework_artifact_path = Path(draft_record["archived_artifacts"][artifact_name])

    assert decision_data["run_id"] == run_id
    assert decision_data["chapter_id"] == chapter_id
    assert decision_data["draft_id"] == draft_id
    assert decision_data["decision_id"] == draft_record["decision_id"]
    assert rework_artifact_data["decision_id"] == decision_data["decision_id"]
    assert rework_artifact_data["chapter_id"] == chapter_id
    assert draft_record["draft_id"] == draft_id
    assert draft_record["chapter_id"] == chapter_id
    assert Path(draft_record["artifact_dir"]) == run_dir / "drafts" / draft_id
    assert archived_decision_path == run_dir / "drafts" / draft_id / "generation_review_decision.json"
    assert archived_rework_artifact_path == run_dir / "drafts" / draft_id / artifact_name
    assert _load_run_artifact_data(archived_decision_path) == decision_data
    assert _load_run_artifact_data(archived_rework_artifact_path) == rework_artifact_data
