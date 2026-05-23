from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from ...reviewer.base import ModelPrompt, ReviewerLoopState
from ...schemas.reviewer_schema import ResolvedReviewTarget, ReviewReport, ReviewRequest


@dataclass(frozen=True, slots=True)
class ReviewerPromptSpec:
    reviewer_id: str
    reviewer_version: str
    display_name_zh: str
    supported_target_types: tuple[str, ...]
    dimensions: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    focus_zh: str
    boundary_zh: str
    context_guidance_zh: str


def build_planning_prompt(
    *,
    spec: ReviewerPromptSpec,
    request: ReviewRequest,
    resolved_target: ResolvedReviewTarget,
) -> ModelPrompt:
    payload = {
        "review_request": request.to_dict(),
        "resolved_target": resolved_target.to_dict(),
        "reviewer": _reviewer_payload(spec),
    }
    system_prompt = _system_prompt(spec, phase_zh="评审计划")
    user_prompt = (
        "任务：生成 ReviewPlan JSON，说明本次模型评审要检查的维度、初步风险和需要请求的只读证据。\n\n"
        f"{_shared_contract_text(spec)}\n\n"
        "Planning 输出只能包含 ReviewPlan contract 字段：\n"
        f"{json.dumps(_plan_example(spec, resolved_target.target_id), ensure_ascii=False, indent=2)}\n\n"
        "工具请求规则：\n"
        "- tool_requests 只是请求，runtime 会按 ReviewContextPolicy 和预算校验。\n"
        "- 如需 Memory 证据，只能请求 memory_query，由 ReviewerMemoryTool 执行。\n"
        "- 如需 KB 证据，只能请求 kb_retrieval，由 ReviewerKBTool 执行。\n"
        "- 如需授权 artifact，只能请求 artifact_read，由 ReviewerArtifactTool 执行。\n"
        "- 不要请求 allowed_tools 之外的工具；若证据不足，请在 notes_zh 中说明。\n\n"
        "Reviewer 输入：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return ModelPrompt(system_prompt=system_prompt, user_prompt=user_prompt)


def build_judging_prompt(*, spec: ReviewerPromptSpec, state: ReviewerLoopState) -> ModelPrompt:
    payload = {
        "request": state.request.to_dict(),
        "resolved_target": state.resolved_target.to_dict(),
        "reviewer": _reviewer_payload(spec),
        "review_plan": state.plan or {},
        "tool_calls": state.tool_calls or [],
        "tool_results": state.tool_results or [],
        "loop_trace": state.loop_trace or [],
    }
    system_prompt = _system_prompt(spec, phase_zh="正式评审")
    user_prompt = (
        "任务：基于目标文本和授权证据输出 ReviewReport JSON。\n\n"
        f"{_shared_contract_text(spec)}\n\n"
        "Judging 输出要求：\n"
        "- summary_zh 必须是中文参考意见。\n"
        "- score 必须是 0-100 的整数参考评分。\n"
        "- score_usage 必须精确为 reference_only。\n"
        "- findings 必须是结构化问题清单；每条强判断应引用 evidence_refs 中的 evidence_id。\n"
        "- findings[].severity 必须精确使用枚举 critical、major、minor、note 之一；证据不足、提示性或低风险事项使用 note，严禁使用 info、warning、high、medium、low 等非 contract 值。\n"
        "- evidence_refs 只能引用目标文本、授权 Memory、授权 KB、授权 Writer artifact 或用户输入证据。\n"
        "- evidence_refs[].source_type 只能使用 target_text、memory、kb、writer_artifact、reference_truth、user_input；严禁使用 document、tool_result、artifact、info、warning 等非 contract 枚举。\n"
        "- self_check 由下一轮模型自检生成，本轮可省略或留空对象。\n"
        "- 区分已经有证据支持的问题和证据不足无法判断的问题；证据不足不得改写成事实。\n\n"
        "ReviewReport JSON 示例结构：\n"
        f"{json.dumps(_report_example(spec, state.request.target.target_id), ensure_ascii=False, indent=2)}\n\n"
        "Reviewer 输入：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return ModelPrompt(system_prompt=system_prompt, user_prompt=user_prompt)


def build_self_check_prompt(
    *,
    spec: ReviewerPromptSpec,
    report: ReviewReport,
    state: ReviewerLoopState,
) -> ModelPrompt:
    payload = {
        "request": state.request.to_dict(),
        "resolved_target": state.resolved_target.to_dict(),
        "reviewer": _reviewer_payload(spec),
        "review_plan": state.plan or {},
        "tool_results": state.tool_results or [],
        "review_report": report.to_dict(),
    }
    system_prompt = _system_prompt(spec, phase_zh="报告自检")
    user_prompt = (
        "任务：对 ReviewReport 做模型自检，只输出自检 JSON。\n\n"
        f"{_shared_contract_text(spec)}\n\n"
        "Self-check 必须确认：\n"
        "- schema_ok: 报告字段形状符合 ReviewReport contract。\n"
        "- score_usage_is_reference_only: score_usage 精确为 reference_only，score 是 0-100 参考评分。\n"
        "- chinese_reference_opinion: summary_zh、findings.message_zh、suggestion_zh 是中文参考意见。\n"
        "- findings_have_evidence_refs: 强判断有 evidence_refs；证据不足事项有清晰说明。\n"
        "- finding_severity_enum: 每个 findings[].severity 都精确属于 critical、major、minor、note。\n"
        "- authorized_context_only: 未使用未授权 reference truth 或未授权工具证据。\n"
        "- no_quality_gate_decision: 没有输出 Writer 或 benchmark 的质量裁决语义。\n\n"
        "若报告可用，status 用 ok；若存在语义矛盾，status 用 needs_revision，并在 issues_zh 说明。\n"
        "自检 JSON 示例：\n"
        f"{json.dumps(_self_check_example(), ensure_ascii=False, indent=2)}\n\n"
        "待自检输入：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return ModelPrompt(system_prompt=system_prompt, user_prompt=user_prompt)


def _system_prompt(spec: ReviewerPromptSpec, *, phase_zh: str) -> str:
    return (
        f"你是 Reviewer Agent 的 model-only 插件：{spec.display_name_zh}（{spec.reviewer_id}）。\n"
        f"当前阶段：{phase_zh}。\n"
        "你只做只读评审，不创作正文，不修改 Writer artifact，不写入 Memory 或 KB。\n"
        "语义判断必须由模型基于目标文本和授权证据完成；不得使用本地规则、关键词覆盖、固定角色表或小说专名映射。\n"
        "不要输出 Writer 或 benchmark 的质量裁决语义；status 只表示评审运行状态。\n"
        "只输出严格 JSON，不要输出 Markdown、代码块或解释性前后缀。"
    )


def _shared_contract_text(spec: ReviewerPromptSpec) -> str:
    return (
        "Reviewer 固定边界：\n"
        f"- 评审重点：{spec.focus_zh}\n"
        f"- 不评审内容：{spec.boundary_zh}\n"
        f"- 上下文策略：{spec.context_guidance_zh}\n"
        f"- 支持 target_type：{', '.join(spec.supported_target_types)}\n"
        f"- 评审维度：{', '.join(spec.dimensions)}\n"
        f"- allowed_tools：{', '.join(spec.allowed_tools) if spec.allowed_tools else '无'}\n"
        "- 输出必须包含中文参考意见、0-100 参考评分、score_usage = reference_only、findings、evidence_refs 和模型自检结果。\n"
        "- ReviewFinding.severity 只能是 critical、major、minor、note；证据不足或提示性意见统一用 note，不得输出 info。\n"
        "- 分数和意见只是参考评审结果，不是 Writer 或 benchmark 的自动质量裁决。"
    )


def _reviewer_payload(spec: ReviewerPromptSpec) -> dict[str, Any]:
    return {
        "reviewer_id": spec.reviewer_id,
        "reviewer_version": spec.reviewer_version,
        "display_name_zh": spec.display_name_zh,
        "supported_target_types": list(spec.supported_target_types),
        "dimensions": list(spec.dimensions),
        "allowed_tools": list(spec.allowed_tools),
        "focus_zh": spec.focus_zh,
        "boundary_zh": spec.boundary_zh,
        "context_guidance_zh": spec.context_guidance_zh,
        "score_usage": "reference_only",
    }


def _plan_example(spec: ReviewerPromptSpec, target_id: str) -> dict[str, Any]:
    tool_request: dict[str, Any] = {
        "tool": spec.allowed_tools[0] if spec.allowed_tools else "",
        "intent": "用一句中文说明需要查询的证据类型；不需要工具时返回空列表。",
        "query": "面向工具的中文查询意图。",
        "priority": "high|medium|low",
        "expected_evidence": "期望证据类型",
        "reason_zh": "说明为什么该证据和当前 reviewer 维度相关。",
    }
    return {
        "schema_version": "1.0",
        "reviewer_id": spec.reviewer_id,
        "target_id": target_id,
        "dimensions": list(spec.dimensions),
        "initial_risks": ["中文列出初步风险；没有明显风险也要说明关注点。"],
        "tool_requests": [tool_request] if spec.allowed_tools else [],
        "can_judge_without_context": not bool(spec.allowed_tools),
        "notes_zh": "中文说明计划和证据充分性预期。",
    }


def _report_example(spec: ReviewerPromptSpec, target_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "target_id": target_id,
        "target_type": "由 request.target.target_type 决定",
        "reviewer_id": spec.reviewer_id,
        "reviewer_version": spec.reviewer_version,
        "status": "success",
        "score": 78,
        "score_usage": "reference_only",
        "summary_zh": "中文总评：说明主要风险、可保留部分和修订重点。",
        "dimension_scores": {dimension: 78 for dimension in spec.dimensions},
        "findings": [
            {
                "finding_id": "finding-001",
                "severity": "major",
                "category": spec.dimensions[0] if spec.dimensions else "综合评审",
                "message_zh": "中文说明问题；若证据不足，明确写成证据不足无法判断。",
                "evidence_refs": ["ev-target-001"],
                "suggestion_zh": "中文修改方向，只给建议，不代写正文。",
                "confidence": 0.72,
            }
        ],
        "evidence_refs": [
            {
                "evidence_id": "ev-target-001",
                "source_type": "target_text",
                "source_id": target_id,
                "quote": "短引用目标文本或授权证据。",
                "summary_zh": "中文概括证据和判断关系。",
                "location": {},
            }
        ],
        "suggested_revision_focus": ["中文列出可执行修订重点。"],
        "confidence": 0.72,
        "self_check": {},
    }


def _self_check_example() -> dict[str, Any]:
    return {
        "status": "ok",
        "schema_ok": True,
        "score_usage_is_reference_only": True,
        "chinese_reference_opinion": True,
        "findings_have_evidence_refs": True,
        "finding_severity_enum": True,
        "authorized_context_only": True,
        "no_quality_gate_decision": True,
        "notes_zh": "报告符合 contract，分数仅作为参考。",
        "issues_zh": [],
    }
