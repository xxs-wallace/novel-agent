from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from .orchestrators import MainLayerOrchestrator
from .repos.creative_kb_storage import init_creative_kb_schema
from .repos.db import NovelAgentDB
from .services.continuation_generation_service import ContinuationGenerationService
from ..runs import RunLayout, RunWriter
from ..schemas import RunConfig


def _normalize_lines(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value).strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _load_optional_json_file(path_text: str | None) -> dict[str, Any]:
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        raise SystemExit(f"scene plan json file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("scene plan json must contain a JSON object")
    return {str(key): value for key, value in payload.items()}


def _should_run_creative_kb(args: argparse.Namespace) -> bool:
    return bool(args.creative_kb_db and args.anchor_context and args.recent_window_summary and args.goal)


def _build_retrieval_bundle_text(payload: dict[str, Any]) -> str:
    writer_input_bundle = payload.get("writer_input_bundle") or {}
    scene_brief = writer_input_bundle.get("scene_brief") or payload.get("scene_brief") or {}
    rerank_result = payload.get("rerank_result") or {}
    reference_fragments = writer_input_bundle.get("reference_fragments") or payload.get("reference_fragments") or []
    context_payload = writer_input_bundle.get("context_payload") or {}
    lines = [
        "Creative KB Retrieval Context:",
        f"- scene_objective: {scene_brief.get('scene_objective', '')}",
        f"- emotional_goal: {scene_brief.get('emotional_goal', '')}",
        f"- conflict_goal: {scene_brief.get('conflict_goal', '')}",
        f"- narrative_function: {', '.join(scene_brief.get('narrative_function') or [])}",
        f"- emotion_mode: {', '.join(scene_brief.get('emotion_mode') or [])}",
        f"- style_need: {', '.join(scene_brief.get('style_need') or [])}",
        f"- selected_fragment_ids: {', '.join(rerank_result.get('selected_fragment_ids') or [])}",
    ]
    if reference_fragments:
        lines.append("- reference_fragments:")
        for item in reference_fragments:
            excerpt = str(item.get("source_excerpt") or "").strip()
            summary = str(item.get("content_summary") or "").strip()
            style = str(item.get("style_profile_text") or "").strip()
            lines.append(f"  - fragment_id: {item.get('fragment_id', '')}")
            if summary:
                lines.append(f"    summary: {summary}")
            if style:
                lines.append(f"    style: {style}")
            if excerpt:
                lines.append(f"    excerpt: {excerpt}")
    chapter_context = context_payload.get("chapter_context") or []
    if chapter_context:
        lines.append("- chapter_context:")
        for item in chapter_context:
            chapter_title = str(item.get("chapter_title") or "").strip()
            summary_md = str(item.get("summary_md") or "").strip()
            if chapter_title:
                lines.append(f"  - {chapter_title}")
            if summary_md:
                lines.append(f"    summary: {summary_md}")
    world_summary_md = str(context_payload.get("world_summary_md") or "").strip()
    if world_summary_md:
        lines.append(f"- world_summary_md: {world_summary_md}")
    character_profiles = context_payload.get("character_profiles") or []
    if character_profiles:
        lines.append("- character_profiles:")
        for item in character_profiles:
            name = str(item.get("canonical_name") or "").strip()
            profile_summary = str(item.get("profile_summary_md") or "").strip()
            if name:
                lines.append(f"  - {name}")
            if profile_summary:
                lines.append(f"    summary: {profile_summary}")
    story_outline_md = str(context_payload.get("story_outline_md") or "").strip()
    if story_outline_md:
        lines.append(f"- story_outline_md: {story_outline_md}")
    return "\n".join(lines).strip()


def _augment_prompt_with_creative_kb(original_prompt: str, payload: dict[str, Any]) -> str:
    retrieval_text = _build_retrieval_bundle_text(payload)
    if not retrieval_text:
        return original_prompt
    return f"{retrieval_text}\n\nUser Task:\n{original_prompt}".strip()


def _maybe_run_creative_kb_retrieval(
    *,
    args: argparse.Namespace,
    run_id: str,
    writer: RunWriter,
) -> dict[str, Any] | None:
    if not _should_run_creative_kb(args):
        return None

    db = NovelAgentDB(Path(args.creative_kb_db))
    orchestrator = MainLayerOrchestrator()
    scene_plan = _load_optional_json_file(args.scene_plan_json)
    retrieval_context = {
        "character_hits": _normalize_lines(args.character_hit),
        "timeline_hits": _normalize_lines(args.timeline_hit),
        "lore_hits": _normalize_lines(args.lore_hit),
    }

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        result = orchestrator.run_online_creative_kb_path(
            conn,
            anchor_context=args.anchor_context,
            recent_window_summary=args.recent_window_summary,
            goal=args.goal,
            previous_generated_segment=args.previous_generated_segment,
            retrieval_context=retrieval_context,
            scene_plan=scene_plan,
            include_coarse_result=bool(args.include_coarse_result),
            expand_reference_fragments=True,
        )
        context_payload = None
        if args.book_id:
            related_character_names = _normalize_lines(args.related_character_name) or _normalize_lines(args.character_hit)
            context_payload = orchestrator.assemble_context_payload(
                conn,
                book_id=args.book_id,
                document_title_index=args.document_title_index,
                related_character_names=related_character_names,
            )
        writer_input_bundle = orchestrator.build_writer_input_bundle(
            anchor_context=args.anchor_context,
            recent_window_summary=args.recent_window_summary,
            retrieval_result=result,
            context_payload=context_payload,
        )

    writer.write_json(run_id, "scene_brief.json", result.scene_brief)
    writer.write_json(run_id, "retrieval_bundle.json", result)
    writer.write_json(run_id, "writer_input_bundle.json", writer_input_bundle)
    payload = result.to_dict()
    payload["writer_input_bundle"] = writer_input_bundle.to_dict()
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Continue a novel scene using smolagents CodeAgent defaults")
    parser.add_argument("prompt", type=str, nargs="?", default=None, help="The prompt to run with the agent")
    parser.add_argument("--runs-dir", type=str, default="runs", help="Directory to write run artifacts into")
    parser.add_argument("--dry-run", action="store_true", help="Write run config only, without calling the model")
    parser.add_argument(
        "--model-type",
        type=str,
        default="InferenceClientModel",
        help="Model type (InferenceClientModel, OpenAIModel, LiteLLMModel, TransformersModel)",
    )
    parser.add_argument("--model-id", type=str, default="Qwen/Qwen3-Next-80B-A3B-Thinking", help="Model id")
    parser.add_argument("--provider", type=str, default=None, help="Inference provider (for InferenceClientModel)")
    parser.add_argument("--api-base", type=str, default=None, help="API base url")
    parser.add_argument("--api-key", type=str, default=None, help="API key")
    parser.add_argument(
        "--thinking",
        type=str,
        default=None,
        choices=["enabled", "disabled"],
        help="DeepSeek thinking mode (OpenAI-compatible via extra_body). Only effective when --model-type OpenAIModel.",
    )
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default=None,
        choices=["high", "max"],
        help="DeepSeek thinking effort. Only effective when --model-type OpenAIModel.",
    )
    parser.add_argument(
        "--save-reasoning",
        action="store_true",
        help="Write DeepSeek reasoning_content to runs/<run_id>/reasoning.md and reasoning.json when available.",
    )
    parser.add_argument("--action-type", type=str, default="code", choices=["code", "tool_calling"])
    parser.add_argument("--tools", nargs="*", default=["python_interpreter"])
    parser.add_argument("--imports", nargs="*", default=[])
    parser.add_argument("--verbosity-level", type=int, default=1)
    parser.add_argument("--stream-outputs", action="store_true")
    parser.add_argument("--creative-kb-db", type=str, default=None, help="Path to novel.db for Creative KB retrieval")
    parser.add_argument("--anchor-context", type=str, default=None, help="Anchor context for Creative KB retrieval")
    parser.add_argument(
        "--recent-window-summary",
        type=str,
        default=None,
        help="Recent window summary for Creative KB retrieval",
    )
    parser.add_argument("--goal", type=str, default=None, help="Goal for Creative KB retrieval")
    parser.add_argument("--book-id", type=str, default=None, help="Book id for Memory context assembly")
    parser.add_argument(
        "--document-title-index",
        type=str,
        default=None,
        help="Current chapter title index for Memory context assembly",
    )
    parser.add_argument(
        "--previous-generated-segment",
        type=str,
        default=None,
        help="Previous generated segment for Creative KB retrieval",
    )
    parser.add_argument(
        "--character-hit",
        action="append",
        default=[],
        help="Character retrieval hit to include in RetrievalContext; repeatable",
    )
    parser.add_argument(
        "--timeline-hit",
        action="append",
        default=[],
        help="Timeline retrieval hit to include in RetrievalContext; repeatable",
    )
    parser.add_argument(
        "--lore-hit",
        action="append",
        default=[],
        help="Lore retrieval hit to include in RetrievalContext; repeatable",
    )
    parser.add_argument(
        "--related-character-name",
        action="append",
        default=[],
        help="Character name to prioritize in Memory context assembly; repeatable",
    )
    parser.add_argument(
        "--scene-plan-json",
        type=str,
        default=None,
        help="Optional path to legacy ScenePlan JSON file for KB compatibility input",
    )
    parser.add_argument(
        "--include-coarse-result",
        action="store_true",
        help="Include coarse_result in retrieval_bundle.json for QA/debug",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = RunConfig(
        prompt=args.prompt,
        model_type=args.model_type,
        model_id=args.model_id,
        provider=args.provider,
        api_base=args.api_base,
        api_key=args.api_key,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
        save_reasoning=bool(args.save_reasoning),
        action_type=args.action_type,
        tools=list(args.tools),
        imports=list(args.imports),
        verbosity_level=args.verbosity_level,
        dry_run=bool(args.dry_run),
    )

    run_id = uuid.uuid4().hex
    layout = RunLayout(base_dir=Path(args.runs_dir))
    writer = RunWriter(layout=layout)
    writer.write_run_config(run_id, config)

    if args.dry_run:
        return 0

    if not args.prompt:
        raise SystemExit("prompt is required unless --dry-run is set")

    retrieval_payload = _maybe_run_creative_kb_retrieval(
        args=args,
        run_id=run_id,
        writer=writer,
    )
    agent_prompt = (
        _augment_prompt_with_creative_kb(args.prompt, retrieval_payload)
        if retrieval_payload is not None
        else args.prompt
    )

    try:
        generation_result = ContinuationGenerationService().generate(
            prompt=agent_prompt,
            config=config,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.save_reasoning:
        writer.write_json(
            run_id,
            "reasoning.json",
            {"steps": [item.to_dict() for item in generation_result.reasoning_steps]},
        )
        writer.write_text(run_id, "reasoning.md", generation_result.reasoning_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
