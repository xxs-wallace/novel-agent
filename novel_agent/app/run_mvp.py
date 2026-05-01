from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smolagents import CodeAgent, ToolCallingAgent
from smolagents.cli import load_model
from smolagents.models import OpenAIModel

from ..indexes import build_index
from ..runs import RunLayout, RunWriter
from ..tools.task4_retrieval_tools import (
    ReadAnchorContextTool,
    SearchByCharacterTool,
    SearchByTimelineTool,
    SearchLoreTool,
)
from ..tools.task5_scene_tools import CheckContinuityTool, PlanSceneTool


def _repo_root_default() -> Path:
    return Path(__file__).resolve().parents[2]


def _index_db_default(repo_root: Path) -> Path:
    return repo_root / "novel_agent" / "indexes" / "novel.db"


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for s in sources:
        if not isinstance(s, dict):
            continue
        path = str(s.get("path") or "")
        snippet = str(s.get("snippet") or "")
        key = (path, snippet)
        if not path or key in seen:
            continue
        seen.add(key)
        out.append(dict(s))
    return out


def _normalize_list(xs: list[str] | None) -> list[str]:
    if not xs:
        return []
    out: list[str] = []
    for x in xs:
        s = str(x).strip()
        if s:
            out.append(s)
    return out


def _draft_from_plan(plan: dict[str, Any]) -> str:
    goal = str(plan.get("goal") or "").strip()
    anchor_context = str(plan.get("anchor_context") or "").strip()
    outline = plan.get("outline") or []
    if not isinstance(outline, list):
        outline = []
    outline_lines = [str(x).strip() for x in outline if str(x).strip()]
    target = plan.get("target_word_count")
    try:
        target_wc = int(target) if target is not None else 1200
    except (TypeError, ValueError):
        target_wc = 1200
    if target_wc <= 0:
        target_wc = 1200

    header = f"# 草稿\n\n目标：{goal}\n"
    if anchor_context:
        excerpt = " ".join(anchor_context.split())
        excerpt = excerpt[:180].rstrip() + ("…" if len(excerpt) > 180 else "")
        header += f"\n锚点摘要：{excerpt}\n"

    body_parts: list[str] = []
    if outline_lines:
        body_parts.append("## 场景大纲\n" + "\n".join(f"- {x}" for x in outline_lines))
    body_parts.append("## 正文\n")

    paragraphs: list[str] = []
    if outline_lines:
        for i, item in enumerate(outline_lines, start=1):
            paragraphs.append(f"{i}. {item}。在这个节点上，角色的动作、对话与环境细节共同推动情节向前。")
    else:
        paragraphs.append("场景从锚点处自然承接，角色在压力与诱惑之间做出选择，新的信息逐步浮出水面。")

    core = "\n\n".join(paragraphs).strip()
    if not core:
        core = "场景从锚点处自然承接，角色在压力与诱惑之间做出选择，新的信息逐步浮出水面。"

    filler = (
        "灯影在墙上晃动，呼吸与脚步声交错。"
        "他把话咽回去，又在下一秒改口，把真正的意图藏在半句玩笑里。"
        "对方没有立刻回答，只用目光把每个破绽都点了一遍。"
    )

    text = header + "\n\n" + "\n\n".join(body_parts) + core
    while len(text) < int(target_wc * 0.8):
        text = text.rstrip() + "\n\n" + filler
    if len(text) > int(target_wc * 1.25):
        text = text[: int(target_wc * 1.25)].rstrip()
    return text.strip() + "\n"


def _build_generation_prompt(
    *, goal: str, anchor_context: str, retrieval_bundle: dict[str, Any], scene_plan: dict[str, Any]
) -> str:
    must = scene_plan.get("must_include") or []
    forbid = scene_plan.get("forbidden") or []
    outline = scene_plan.get("outline") or []
    try:
        target_wc = int(scene_plan.get("target_word_count") or 1200)
    except (TypeError, ValueError):
        target_wc = 1200
    must_s = "\n".join(f"- {str(x).strip()}" for x in must if str(x).strip())
    forbid_s = "\n".join(f"- {str(x).strip()}" for x in forbid if str(x).strip())
    outline_s = "\n".join(f"- {str(x).strip()}" for x in outline if str(x).strip())
    sources = _dedupe_sources(list(retrieval_bundle.get("sources") or []))
    src_s = "\n".join(
        f"- {s.get('path')}：{str(s.get('snippet') or '').strip()}" for s in sources[:12] if s.get("path")
    )

    parts = [
        "你是中文小说续写作者，请基于给定材料写一个单场景续写草稿。",
        "要求：",
        f"1) 字数目标：约 {target_wc} 字，允许 800-2000 字区间内浮动。",
        "2) 必须严格承接锚点上下文，不要引入与设定冲突的新事实。",
        "3) 避免复述材料，优先用动作、对话、感官细节推进剧情。",
        "4) 输出为 Markdown，仅输出正文，不要额外解释。",
        "",
        f"续写目标：{goal}",
        "",
        "锚点上下文：",
        anchor_context.strip(),
        "",
        "场景大纲：",
        outline_s.strip(),
        "",
        "必写点：",
        must_s.strip() if must_s.strip() else "- 无",
        "",
        "禁写点：",
        forbid_s.strip() if forbid_s.strip() else "- 无",
        "",
        "检索证据（只用于确保一致性，不要原文照抄）：",
        src_s.strip() if src_s.strip() else "- 无",
        "",
    ]
    return "\n".join(parts).strip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Novel continuation MVP runner (read->retrieve->plan->draft->check->save)"
    )
    parser.add_argument("--anchor-path", type=str, required=True, help="Anchor segment path, relative to repo root")
    parser.add_argument("--goal", type=str, required=True, help="Continuation goal description")
    parser.add_argument("--runs-dir", type=str, default="runs", help="Directory to write run artifacts into")
    parser.add_argument("--dry-run", action="store_true", help="Skip model call, generate a deterministic draft")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild index database before retrieval")
    parser.add_argument("--repo-root", type=str, default=None, help="Override NOVEL_AGENT_REPO_ROOT")
    parser.add_argument("--index-db", type=str, default=None, help="Override NOVEL_AGENT_INDEX_DB")
    parser.add_argument("--window-before", type=int, default=1)
    parser.add_argument("--window-after", type=int, default=1)
    parser.add_argument("--characters", nargs="*", default=None, help="Override character names for character search")
    parser.add_argument("--lore-keywords", nargs="*", default=None, help="Override lore keywords for lore search")
    parser.add_argument("--timeline-keywords", nargs="*", default=None, help="Override keywords for timeline search")
    parser.add_argument("--retrieval-limit", type=int, default=12)
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
    parser.add_argument("--action-type", type=str, default="tool_calling", choices=["code", "tool_calling"])
    parser.add_argument("--verbosity-level", type=int, default=1)
    parser.add_argument("--stream-outputs", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else _repo_root_default()
    index_db = Path(args.index_db).resolve() if args.index_db else _index_db_default(repo_root)
    os.environ.setdefault("NOVEL_AGENT_REPO_ROOT", str(repo_root))
    os.environ.setdefault("NOVEL_AGENT_INDEX_DB", str(index_db))

    run_id = uuid.uuid4().hex
    layout = RunLayout(base_dir=Path(args.runs_dir))
    writer = RunWriter(layout=layout)

    task = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "anchor_path": str(args.anchor_path),
        "goal": str(args.goal),
        "dry_run": bool(args.dry_run),
        "model": {
            "model_type": args.model_type,
            "model_id": args.model_id,
            "provider": args.provider,
            "api_base": args.api_base,
            "action_type": args.action_type,
        },
    }

    if args.rebuild_index or not index_db.exists():
        build_index(db_path=index_db, repo_root=repo_root, rebuild=bool(args.rebuild_index))

    read_tool = ReadAnchorContextTool()
    anchor_result = read_tool(
        segment_path=str(args.anchor_path),
        window_before=int(args.window_before),
        window_after=int(args.window_after),
    )
    if not anchor_result.get("ok"):
        raise SystemExit(str(anchor_result.get("error") or "read_anchor_context failed"))
    anchor_context = str((anchor_result.get("output") or {}).get("content") or "").strip()

    retrieval_limit = max(1, int(args.retrieval_limit))
    characters = _normalize_list(args.characters) or [str(args.goal).strip()]
    lore_keywords = _normalize_list(args.lore_keywords) or [str(args.goal).strip()]
    timeline_keywords = _normalize_list(args.timeline_keywords) or [str(args.goal).strip()]

    retrieval_steps: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    char_tool = SearchByCharacterTool()
    for name in characters:
        r = char_tool(name=name, scope="longzu_split", limit=retrieval_limit)
        retrieval_steps.append(r)
        sources.extend(list(r.get("sources") or []))

    lore_tool = SearchLoreTool()
    for kw in lore_keywords:
        r = lore_tool(keyword=kw, limit=retrieval_limit)
        retrieval_steps.append(r)
        sources.extend(list(r.get("sources") or []))

    timeline_tool = SearchByTimelineTool()
    for kw in timeline_keywords:
        r = timeline_tool(keyword=kw, scope="longzu_split", limit=retrieval_limit)
        retrieval_steps.append(r)
        sources.extend(list(r.get("sources") or []))

    dedup_sources = _dedupe_sources(list(anchor_result.get("sources") or []) + sources)
    retrieval_bundle = {
        "anchor_path": str(args.anchor_path),
        "queries": {"characters": characters, "lore_keywords": lore_keywords, "timeline_keywords": timeline_keywords},
        "steps": retrieval_steps,
        "sources": dedup_sources,
    }

    plan_tool = PlanSceneTool()
    scene_plan = plan_tool(goal=str(args.goal), anchor_context=anchor_context, retrieval_json=retrieval_bundle)

    if args.dry_run:
        draft_md = _draft_from_plan(scene_plan)
        reasoning_steps: list[dict[str, Any]] = []
        reasoning_md = ""
    else:
        if (args.thinking or args.reasoning_effort) and args.model_type != "OpenAIModel":
            raise SystemExit("--thinking/--reasoning-effort requires --model-type OpenAIModel")
        if args.model_type == "OpenAIModel" and (args.thinking or args.reasoning_effort):
            extra_body = {"thinking": {"type": args.thinking}} if args.thinking else None
            model = OpenAIModel(
                model_id=args.model_id,
                api_base=args.api_base,
                api_key=args.api_key,
                reasoning_effort=args.reasoning_effort,
                extra_body=extra_body,
                include_reasoning_content=True,
            )
        else:
            model = load_model(
                model_type=args.model_type,
                model_id=args.model_id,
                api_base=args.api_base,
                api_key=args.api_key,
                provider=args.provider,
            )
        prompt = _build_generation_prompt(
            goal=str(args.goal),
            anchor_context=anchor_context,
            retrieval_bundle=retrieval_bundle,
            scene_plan=scene_plan,
        )
        if args.action_type == "code":
            agent = CodeAgent(
                tools=[],
                model=model,
                verbosity_level=args.verbosity_level,
                stream_outputs=bool(args.stream_outputs),
            )
        else:
            agent = ToolCallingAgent(
                tools=[],
                model=model,
                verbosity_level=args.verbosity_level,
                stream_outputs=bool(args.stream_outputs),
            )
        draft_md = str(agent.run(prompt)).strip() + "\n"
        reasoning_steps = []
        for step in agent.memory.steps:
            msg = getattr(step, "model_output_message", None)
            if not msg:
                continue
            reasoning = getattr(msg, "reasoning_content", None)
            content = getattr(msg, "content", None)
            if reasoning is None and content is None:
                continue
            reasoning_steps.append(
                {
                    "step_type": type(step).__name__,
                    "reasoning_content": reasoning,
                    "content": content,
                }
            )
        reasoning_md = "\n\n".join(str(s.get("reasoning_content") or "").strip() for s in reasoning_steps).strip() + "\n"

    check_tool = CheckContinuityTool()
    continuity_report = check_tool(draft=draft_md, scene_plan_json=scene_plan)
    final_md = draft_md

    reading_pack = {
        "anchor": anchor_result,
        "anchor_context": anchor_context,
        "sources": dedup_sources,
    }

    writer.write_run_artifacts(
        run_id,
        task=task,
        reading_pack=reading_pack,
        retrieval_bundle=retrieval_bundle,
        scene_plan=scene_plan,
        draft_md=draft_md,
        continuity_report=continuity_report,
        final_md=final_md,
    )
    if args.save_reasoning:
        writer.write_json(run_id, "reasoning.json", {"steps": reasoning_steps})
        writer.write_text(run_id, "reasoning.md", reasoning_md if reasoning_md != "\n" else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
