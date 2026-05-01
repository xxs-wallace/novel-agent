from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from smolagents import Tool

from ..schemas.continuity import ContinuityIssue, ContinuityReport
from ..schemas.scene_plan import ScenePlan


def _split_items(raw: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[，,、;；/\n\r\t]+", raw) if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _extract_list(text: str, *, keywords: list[str]) -> list[str]:
    if not text.strip():
        return []
    items: list[str] = []
    for kw in keywords:
        pattern = re.compile(rf"{re.escape(kw)}\s*[:：]\s*([^\n]+)")
        for m in pattern.finditer(text):
            items.extend(_split_items(m.group(1)))
    return items


def _extract_word_target(text: str) -> int | None:
    s = text.strip()
    if not s:
        return None
    m = re.search(r"(\d{2,5})\s*[-~～—]\s*(\d{2,5})\s*字", s)
    if m:
        lo = int(m.group(1))
        hi = int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        if hi <= 0:
            return None
        return max(1, int(round((lo + hi) / 2)))
    m = re.search(r"(\d{2,5})\s*字", s)
    if m:
        n = int(m.group(1))
        return n if n > 0 else None
    m = re.search(r"word(?:s)?\s*[:：]?\s*(\d{2,5})", s, flags=re.IGNORECASE)
    if m:
        n = int(m.group(1))
        return n if n > 0 else None
    return None


def _as_object(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return None


def _extract_sources(value: Any, *, limit: int = 30) -> list[dict[str, Any]]:
    obj = _as_object(value)
    if obj is None:
        return []

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def visit(x: Any) -> None:
        nonlocal out
        if len(out) >= limit:
            return
        if isinstance(x, dict):
            sources = x.get("sources")
            if isinstance(sources, list):
                for s in sources:
                    if not isinstance(s, dict):
                        continue
                    path = str(s.get("path") or "")
                    snippet = str(s.get("snippet") or "")
                    key = (path, snippet)
                    if path and key not in seen:
                        seen.add(key)
                        out.append(dict(s))
                        if len(out) >= limit:
                            return
            for v in x.values():
                visit(v)
        elif isinstance(x, list):
            for it in x:
                visit(it)

    visit(obj)
    return out


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (0x3400 <= code <= 0x4DBF) or (0x4E00 <= code <= 0x9FFF)


def _approx_word_count(text: str) -> int:
    total = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if _is_cjk(ch):
            total += 1
            i += 1
            continue
        m = re.match(r"[A-Za-z0-9]+", text[i:])
        if m:
            total += 1
            i += len(m.group(0))
            continue
        i += 1
    return total


def _normalize_for_repeat(text: str) -> str:
    s = re.sub(r"\s+", "", text)
    return "".join(ch.lower() for ch in s if _is_cjk(ch) or ch.isalnum())


@dataclass(frozen=True, slots=True)
class _RepeatStats:
    ratio: float
    sample: str | None


def _repeat_stats(text: str) -> _RepeatStats:
    norm = _normalize_for_repeat(text)
    if len(norm) < 200:
        return _RepeatStats(ratio=0.0, sample=None)
    n = 12
    counts: dict[str, int] = {}
    for i in range(0, len(norm) - n + 1):
        g = norm[i : i + n]
        counts[g] = counts.get(g, 0) + 1
    if not counts:
        return _RepeatStats(ratio=0.0, sample=None)
    repeated = 0
    best = ("", 0)
    for g, c in counts.items():
        if c > 1:
            repeated += (c - 1) * n
        if c > best[1]:
            best = (g, c)
    ratio = min(1.0, repeated / max(1, len(norm)))
    sample = best[0] if best[1] >= 3 else None
    return _RepeatStats(ratio=ratio, sample=sample)


class PlanSceneTool(Tool):
    name = "plan_scene"
    description = "输入 goal、anchor_context 与可选 retrieval_json，生成结构化 ScenePlan。"
    inputs = {
        "goal": {"type": "string", "description": "续写目标描述。"},
        "anchor_context": {"type": "string", "description": "锚点上下文内容（相邻分片/摘要等）。"},
        "retrieval_json": {"type": "object", "description": "可选检索结果（可包含 sources）。", "nullable": True},
    }
    output_type = "object"
    output_schema = {
        "type": "object",
        "required": ["goal", "anchor_context", "must_include", "forbidden", "outline", "target_word_count", "sources"],
        "properties": {
            "goal": {"type": "string"},
            "anchor_context": {"type": "string"},
            "must_include": {"type": "array", "items": {"type": "string"}},
            "forbidden": {"type": "array", "items": {"type": "string"}},
            "outline": {"type": "array", "items": {"type": "string"}},
            "target_word_count": {"type": "integer"},
            "sources": {"type": "array", "items": {"type": "object"}},
        },
    }

    def forward(self, goal: str, anchor_context: str, retrieval_json: Any | None = None) -> dict[str, Any]:
        goal_s = str(goal or "").strip()
        anchor_s = str(anchor_context or "").strip()
        must = _extract_list(goal_s, keywords=["必须包含", "必须写到", "必须提及", "必写", "必含", "must_include"])
        forbid = _extract_list(goal_s, keywords=["禁止", "不要", "避免", "不得", "forbidden"])
        target = _extract_word_target(goal_s) or 1200
        sources = _extract_sources(retrieval_json)

        outline: list[str] = []
        if anchor_s:
            excerpt = re.sub(r"\s+", " ", anchor_s).strip()
            if len(excerpt) > 80:
                excerpt = excerpt[:80].rstrip() + "…"
            outline.append(f"承接锚点：{excerpt}")
        if goal_s:
            outline.append(f"推进目标：{goal_s}")
        outline.extend(
            [
                "设置一个明确冲突或阻碍，并让角色做出选择",
                "补充新信息或转折，保证与既有设定一致",
                "收束场景并留下下一步行动或悬念",
            ]
        )

        plan = ScenePlan(
            goal=goal_s,
            anchor_context=anchor_s,
            must_include=must,
            forbidden=forbid,
            outline=outline,
            target_word_count=int(target),
            sources=sources,
        )
        return plan.to_dict()


class CheckContinuityTool(Tool):
    name = "check_continuity"
    description = "输入草稿与可选 ScenePlan，对一致性做最小可用规则检查并输出报告。"
    inputs = {
        "draft": {"type": "string", "description": "待检查的续写草稿文本。"},
        "scene_plan_json": {"type": "object", "description": "可选 ScenePlan JSON。", "nullable": True},
    }
    output_type = "object"
    output_schema = {
        "type": "object",
        "required": ["issues"],
        "properties": {
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["type", "severity", "message"],
                    "properties": {
                        "type": {"type": "string"},
                        "severity": {"type": "string"},
                        "message": {"type": "string"},
                        "span": {
                            "type": ["array", "null"],
                            "items": {"type": "integer"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "quote": {"type": ["string", "null"]},
                        "suggested_fix": {"type": ["string", "null"]},
                    },
                },
            }
        },
    }

    def forward(self, draft: str, scene_plan_json: Any | None = None) -> dict[str, Any]:
        draft_s = str(draft or "")
        plan_obj = _as_object(scene_plan_json)
        plan = ScenePlan.from_dict(plan_obj) if isinstance(plan_obj, dict) else None

        issues: list[ContinuityIssue] = []

        if plan is not None:
            for term in plan.must_include:
                if term and term not in draft_s:
                    issues.append(
                        ContinuityIssue(
                            type="missing_must_include",
                            severity="high",
                            message=f"必写点未出现：{term}",
                            suggested_fix=f"在本场景中补充对“{term}”的明确提及或具体描写。",
                        )
                    )

            for term in plan.forbidden:
                if not term:
                    continue
                m = re.search(re.escape(term), draft_s)
                if m:
                    start = max(0, m.start() - 20)
                    end = min(len(draft_s), m.end() + 20)
                    quote = draft_s[start:end].strip()
                    issues.append(
                        ContinuityIssue(
                            type="forbidden_present",
                            severity="high",
                            message=f"出现禁写点：{term}",
                            span=(m.start(), m.end()),
                            quote=quote,
                            suggested_fix=f"删除或改写与“{term}”相关内容，使其不违反禁写点。",
                        )
                    )

            if plan.target_word_count > 0:
                wc = _approx_word_count(draft_s)
                lo = max(1, int(round(plan.target_word_count * 0.8)))
                hi = max(lo, int(round(plan.target_word_count * 1.2)))
                if wc < lo or wc > hi:
                    direction = "扩写" if wc < lo else "压缩"
                    issues.append(
                        ContinuityIssue(
                            type="word_count_deviation",
                            severity="medium",
                            message=f"字数偏离：当前约 {wc}，目标 {plan.target_word_count}（建议区间 {lo}-{hi}）。",
                            suggested_fix=f"尝试{direction}到接近目标字数，并保持节奏与信息密度。",
                        )
                    )

        rep = _repeat_stats(draft_s)
        if rep.ratio >= 0.18:
            issues.append(
                ContinuityIssue(
                    type="high_repetition",
                    severity="medium",
                    message=f"重复率偏高：估算重复片段占比约 {rep.ratio:.0%}。",
                    quote=rep.sample,
                    suggested_fix="合并同义表达，删除重复句式，使用更具体的动作/感官细节替换空泛重复。",
                )
            )

        report = ContinuityReport(issues=issues)
        return report.to_dict()


NOVEL_AGENT_TOOL_MAPPING: dict[str, type[Tool]] = {
    PlanSceneTool.name: PlanSceneTool,
    CheckContinuityTool.name: CheckContinuityTool,
}
