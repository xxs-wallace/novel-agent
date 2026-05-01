from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.schemas.orchestration_schema import (
    BatchPlan,
    ChapterBrief,
    ChapterPackage,
    ChapterStructureHint,
    FreezeRecord,
    ModelingCheckItem,
    ModelingStatus,
    RelationshipTarget,
    StateChange,
    StateDelta,
    TraceableSource,
)
from novel_agent.runs.layout import RunLayout
from novel_agent.runs.writer import RunWriter


def test_writer_layered_schema_to_dict_keeps_nested_shapes() -> None:
    modeling_status = ModelingStatus(
        book_id="book-1",
        ready_for_continuation=True,
        checks=[
            ModelingCheckItem(
                name="memory",
                ready=True,
                detail="character profiles indexed",
                source_paths=["memory/characters.json"],
            )
        ],
        missing_modeling_steps=["creative_kb"],
        sources=[
            TraceableSource(
                type="analysis",
                path="specs/modeling.md",
                evidence_level="confirmed_analysis",
            )
        ],
    )
    chapter = ChapterBrief(
        chapter_id="batch-01-ch01",
        title="雨夜之前",
        goal="迫使两人合作",
        plot_function="承上启下",
        emotional_goal="由防备转向有限信任",
        conflict_goal="在追捕中求生",
        relationship_targets=[
            RelationshipTarget(
                relation_type="友情",
                current_state="试探",
                target_state="有限合作",
                required_bridge=["共同危机"],
            )
        ],
        must_include=["雨夜逃亡"],
        forbidden=["突然告白"],
        structure_hint=ChapterStructureHint(theory="故事圆环", beats=["Need", "Go"]),
    )
    package = ChapterPackage(
        package_id="pkg-1",
        batch_id="batch-01",
        package_goal="完成第一批章节冻结",
        chapters=[chapter],
    )
    batch = BatchPlan(
        batch_id="batch-01",
        book_id="book-1",
        scope_start="chapter-11",
        scope_end="chapter-13",
        batch_goal="推进逃亡线",
        must_resolve=["建立合作"],
        must_not_consume=["终局真相"],
    )
    delta = StateDelta(
        chapter_id="batch-01-ch01",
        character_state_changes=[StateChange(subject="沈青", from_state="防备", to_state="松动")],
        relationship_state_changes=[
            StateChange(subject="沈青-周渡", from_state="试探", to_state="有限合作")
        ],
        timeline_events=["两人共同脱离追捕"],
        world_state_changes=["旧仓库位置暴露"],
        outline_progress=["逃亡线正式启动"],
        canon_ready=True,
    )

    status_dict = modeling_status.to_dict()
    package_dict = package.to_dict()
    batch_dict = batch.to_dict()
    delta_dict = delta.to_dict()

    assert status_dict["checks"][0]["name"] == "memory"
    assert status_dict["sources"][0]["evidence_level"] == "confirmed_analysis"
    assert package_dict["chapters"][0]["relationship_targets"][0]["target_state"] == "有限合作"
    assert package_dict["chapters"][0]["structure_hint"]["beats"] == ["Need", "Go"]
    assert batch_dict["must_not_consume"] == ["终局真相"]
    assert delta_dict["character_state_changes"][0]["to_state"] == "松动"
    assert delta_dict["canon_ready"] is True


def test_run_writer_persists_freeze_record_and_manifest(tmp_path: Path) -> None:
    writer = RunWriter(layout=RunLayout(base_dir=tmp_path / "runs"))

    paths = writer.write_freeze_record(
        "run-1",
        FreezeRecord(
            freeze_stage="freeze_c",
            summary="章节包已确认",
            depends_on=["freeze_b"],
        ),
        artifact_payloads={
            "chapter_package.json": {"package_id": "pkg-1"},
            "review.md": "# confirmed\n",
        },
    )

    freeze_record_path = Path(paths["freeze.json"])
    manifest_path = Path(paths["freezes/index.json"])
    chapter_package_path = Path(paths["chapter_package.json"])
    review_path = Path(paths["review.md"])

    assert freeze_record_path.exists()
    assert manifest_path.exists()
    assert chapter_package_path.exists()
    assert review_path.exists()

    freeze_record_doc = json.loads(freeze_record_path.read_text(encoding="utf-8"))
    manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))

    assert freeze_record_doc["data"]["freeze_stage"] == "freeze_c"
    assert freeze_record_doc["data"]["invalidates_downstream"] == ["freeze_d", "freeze_e"]
    assert chapter_package_doc["data"]["package_id"] == "pkg-1"
    assert manifest_doc["records"][0]["freeze_stage"] == "freeze_c"
    assert manifest_doc["records"][0]["artifacts"][0]["name"] == "chapter_package.json"
