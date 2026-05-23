from __future__ import annotations

from pathlib import Path

import pytest

from novel_agent.app.gui.interactive_runner import (
    InteractivePipelineCommand,
    PipelineRunConfig,
    WriterRunConfig,
    WriterWorkflowCommand,
    _split_csv,
)
from novel_agent.app.gui.writer_cli import _available_chapter_ids, _map_chapter_id_alias, _print_public_result
from novel_agent.app.orchestrators.writer_layered_generation import WriterLayeredGenerationOrchestrator
from novel_agent.runs.layout import RunLayout
from novel_agent.runs.writer import RunWriter


def test_interactive_pipeline_command_builds_python_module_invocation(tmp_path: Path) -> None:
    source_path = tmp_path / "novel.txt"
    source_path.write_text("chapter", encoding="utf-8")
    python_executable = tmp_path / "python"
    python_executable.write_text("", encoding="utf-8")

    config = PipelineRunConfig(
        repo_root=tmp_path,
        task_name="Demo Task",
        source_path=source_path,
        run_mode="resume",
        max_read_kb=7,
        max_close_batches=3,
        segment_step_kb=2,
        close_step_batches=1,
        build_creative_kb=False,
        api_key="secret",
        python_executable=python_executable,
    )

    command = InteractivePipelineCommand(config)

    assert command.command() == [str(python_executable.absolute()), "-m", "novel_agent.app.run_interactive"]
    assert command.environment()["DEEPSEEK_API_KEY"] == "secret"
    assert command.environment()["NOVEL_AGENT_REPO_ROOT"] == str(tmp_path.resolve())
    assert command.stdin_payload().decode("utf-8").splitlines() == [
        "pipeline",
        "Demo Task",
        str(source_path.resolve()),
        "resume",
        "7",
        "3",
        "2",
        "1",
        "n",
    ]


def test_pipeline_run_config_rejects_missing_source_path(tmp_path: Path) -> None:
    config = PipelineRunConfig(repo_root=tmp_path, task_name="Demo", source_path=tmp_path / "missing.txt")

    with pytest.raises(ValueError, match="小说路径不存在"):
        config.validate()


def test_pipeline_run_config_preserves_venv_python_symlink(tmp_path: Path) -> None:
    source_path = tmp_path / "novel.txt"
    source_path.write_text("chapter", encoding="utf-8")
    real_python = tmp_path / "real-python"
    real_python.write_text("", encoding="utf-8")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_python = venv_bin / "python"
    venv_python.symlink_to(real_python)

    config = PipelineRunConfig(repo_root=tmp_path, task_name="Demo", source_path=source_path)

    assert config.resolved_python == venv_python.absolute()
    assert config.resolved_python != real_python.absolute()


def test_writer_workflow_command_builds_json_payload(tmp_path: Path) -> None:
    python_executable = tmp_path / "python"
    python_executable.write_text("", encoding="utf-8")
    config = WriterRunConfig(
        repo_root=tmp_path,
        task_name="Writer Task",
        product_mode="batch",
        action="prepare_planning",
        run_id="run-1",
        major_characters="A, B",
        desired_actions="escape, reveal",
        avoidances="ooc",
        preferred_outcome="win",
        notes="keep quiet",
        user_world_notes="new rule",
        target_chapter_count=5,
        chapter_count=4,
        reset_writer_memory=True,
        python_executable=python_executable,
    )

    command = WriterWorkflowCommand(config)
    payload = command.stdin_payload().decode("utf-8")

    assert command.command() == [str(python_executable.absolute()), "-m", "novel_agent.app.gui.writer_cli"]
    assert '"task_name": "Writer Task"' in payload
    assert '"product_mode": "batch"' in payload
    assert '"major_characters": ["A", "B"]' in payload
    assert '"desired_actions": ["escape", "reveal"]' in payload
    assert '"reset_writer_memory": true' in payload


def test_writer_run_config_accepts_all_chapter_acceptance_actions(tmp_path: Path) -> None:
    for action in ["accept_chapter", "revise_chapter_length", "replan_chapter", "discard_chapter"]:
        WriterRunConfig(repo_root=tmp_path, task_name="Writer Task", action=action, run_id="run-1").validate()


def test_writer_cli_public_result_does_not_leak_internal_stage_tokens(capsys) -> None:
    _print_public_result(
        result={
            "checkpoint": {
                "stage": "wait_chapter_acceptance",
                "status": "pending",
                "artifact_path": "/tmp/run/generation_review_decision.json",
            }
        },
        run_id="run-1",
        book_id="book-1",
    )
    output = capsys.readouterr().out

    assert "请决定当前章节草稿" in output
    for token in ["artifact saved", "Freeze B pending", "freeze_d_review", "wait_chapter_acceptance", "checkpoint confirmed"]:
        assert token not in output


def test_writer_chapter_id_alias_maps_chinese_ordinal_to_existing_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    freeze_dir = run_dir / "freezes" / "freeze_c"
    freeze_dir.mkdir(parents=True)
    (freeze_dir / "chapter_package.json").write_text(
        """
        {
          "data": {
            "chapters": [
              {"chapter_id": "batch15-ch01"},
              {"chapter_id": "batch15-ch02"}
            ]
          }
        }
        """,
        encoding="utf-8",
    )

    assert _available_chapter_ids(runs_dir=tmp_path, run_id="run-1") == ["batch15-ch01", "batch15-ch02"]
    assert _map_chapter_id_alias(runs_dir=tmp_path, run_id="run-1", chapter_id="一", chapter_count=3) == "batch15-ch01"
    assert _map_chapter_id_alias(runs_dir=tmp_path, run_id="run-1", chapter_id="第2章", chapter_count=3) == "batch15-ch02"


def test_split_csv_accepts_chinese_and_english_separators() -> None:
    assert _split_csv("张三，李四, 王五；赵六\n钱七") == ["张三", "李四", "王五", "赵六", "钱七"]


def test_run_writer_rebuilds_accepted_chapters_markdown(tmp_path: Path) -> None:
    writer = RunWriter(layout=RunLayout(base_dir=tmp_path))
    run_id = "run-1"
    writer.write_text(run_id, "draft.md", "# 正文\n\n第一章内容")
    writer.sync_draft_retention_record(
        run_id,
        draft_id="draft-001",
        chapter_id="batch01-ch01",
        decision_id="review-1",
        retention_status="accepted",
        decision_status="accepted",
    )

    path = writer.rebuild_accepted_chapters_markdown(run_id)

    assert path == tmp_path / run_id / "accepted_chapters.md"
    assert "batch01-ch01" in path.read_text(encoding="utf-8")
    assert "第一章内容" in path.read_text(encoding="utf-8")


def test_prepare_execution_allows_blank_chapter_id_for_auto_selection(tmp_path: Path) -> None:
    config = WriterRunConfig(
        repo_root=tmp_path,
        task_name="Writer Task",
        action="prepare_execution",
        run_id="run-1",
        chapter_id="",
        python_executable=tmp_path / "python",
    )

    payload = WriterWorkflowCommand(config).stdin_payload().decode("utf-8")

    assert '"action": "prepare_execution"' in payload
    assert '"chapter_id": ""' in payload


def test_writer_planner_unknown_evidence_level_falls_back_to_reasonable_inference(tmp_path: Path) -> None:
    writer = RunWriter(layout=RunLayout(base_dir=tmp_path))
    planner = WriterLayeredGenerationOrchestrator(repo_root=tmp_path, run_writer=writer)

    evidence = planner._evidence_item_from_dict({"claim": "模型判断", "evidence_level": "model_guess"})  # noqa: SLF001

    assert evidence.evidence_level == "reasonable_inference"
