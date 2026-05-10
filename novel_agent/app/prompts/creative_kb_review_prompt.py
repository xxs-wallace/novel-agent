from __future__ import annotations

import json
from typing import Any


FRAGMENT_CARD_RUBRIC = {
    "faithfulness": "content_summary 与各结构化字段是否忠实于原始 document excerpt，不编造事件、人物或关系。",
    "retrievability": "字段是否短、清晰、可用于 SceneBrief 检索，而不是散文化赏析。",
    "narrative_function": "narrative_function_text 是否抽取桥段功能，而非只复述表层事件。",
    "emotion_mechanism": "emotion_mechanism_text 是否提炼情绪表达机制。",
    "relationship_facts": "character_relation_text 与 relationship_state 是否避免无证据编造关系事实。",
    "style_transferability": "style_profile_text 与 transferability_score 是否能支持迁移到新场景。",
    "context_dependency_risk": "context_dependency_level 是否合理标注上下文依赖风险。",
}

CLUSTER_RUBRIC = {
    "near_duplicate_fit": "同簇成员是否在叙事功能、情绪机制与风格用途上近重复。",
    "false_merge_risk": "是否把表层事件相似但写法用途不同的片段误合并。",
    "representative_quality": "representative card 是否比其他成员更适合作为续写参考。",
}

RETRIEVAL_RUBRIC = {
    "top1_beats_decoys": "top1 selected reference 是否明显比 decoy / rejected references 更适合当前 SceneBrief。",
    "selected_fragments_match_scene_brief": "top 1-4 selected references 是否匹配 SceneBrief 的目标与约束。",
    "scene_function_fit": "selected references 的叙事功能是否匹配 SceneBrief。",
    "emotion_mechanism_fit": "selected references 的情绪机制是否匹配 SceneBrief。",
    "relationship_state_fit": "selected references 的关系阶段是否匹配 SceneBrief，避免关系跳级。",
    "style_reference_value": "selected references 是否提供明确、可迁移的风格参考。",
    "transferability": "selected references 是否可迁移到当前场景，而非高度依赖原文专有上下文。",
    "cluster_diversity": "selected references 是否避免同一 cluster 重复占位。",
    "context_dependency_risk": "高上下文依赖片段是否被不当地排到靠前位置。",
    "negative_transfer_risk": "selected references 是否可能把 Writer 带向错误剧情、错误设定或错误关系阶段。",
}

WRITER_AB_RUBRIC = {
    "synopsis_coverage": "draft 是否覆盖 reference_story_synopsis 的关键事件和必须保留点。",
    "recent_window_coherence": "draft 是否承接最近剧情窗口，而非另起主线。",
    "emotion_mechanism_quality": "draft 是否稳定执行目标情绪机制，而非只贴标签或直接解释。",
    "relationship_state_fit": "draft 是否保持关系阶段准确，避免关系跳级或错误和解。",
    "style_stability": "draft 是否从 references 获得可迁移风格收益，并保持节奏与表达稳定。",
    "negative_transfer_from_references": "是否出现 KB references 误迁移导致的剧情、设定或人物关系偏移。",
}


def build_fragment_card_review_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Creative KB benchmark 的外部建卡质量 Reviewer。\n"
        "你只评价 fragment_card 质量，不得提出修改后的 card，不得把结论反向注入 KB、检索或 rerank。\n"
        "请根据原始 document excerpt 和 fragment_card 做证据约束评估。\n"
        "只输出严格 JSON，不要输出 Markdown、代码块或解释性前后缀。"
    )
    user_prompt = (
        "任务：评价一个 fragment_card 是否忠实、可检索、可迁移。\n\n"
        "固定检查项：\n"
        f"{json.dumps(FRAGMENT_CARD_RUBRIC, ensure_ascii=False, indent=2)}\n\n"
        "输出 JSON schema：\n"
        f"{json.dumps(_fragment_card_report_example(), ensure_ascii=False, indent=2)}\n\n"
        "Reviewer 输入：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_cluster_review_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Creative KB benchmark 的外部聚类质量 Reviewer。\n"
        "你只评价 fragment_cluster 质量，不得提出修改后的 cluster，不得把结论反向注入 KB、检索或 rerank。\n"
        "请根据 cluster members、representative card 与 dedup_reason 做相对判断。\n"
        "只输出严格 JSON，不要输出 Markdown、代码块或解释性前后缀。"
    )
    user_prompt = (
        "任务：评价一个 fragment_cluster 是否合并了真正近重复的桥段机制，并选出了合理代表片段。\n\n"
        "固定检查项：\n"
        f"{json.dumps(CLUSTER_RUBRIC, ensure_ascii=False, indent=2)}\n\n"
        "输出 JSON schema：\n"
        f"{json.dumps(_cluster_report_example(), ensure_ascii=False, indent=2)}\n\n"
        "Reviewer 输入：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_retrieval_review_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Creative KB benchmark 的外部检索 / rerank 质量 Reviewer。\n"
        "你评价的是相对排序质量，不是片段的绝对文学性。\n"
        "必须基于 SceneBrief、selected references、decoy references 与 rejected high-score references 判断："
        "系统 top references 是否比 decoy 更适合作为当前 SceneBrief 的桥段参考。\n"
        "你只评价，不得提出修改后的 KB、检索规则或 rerank 输入。\n"
        "只输出严格 JSON，不要输出 Markdown、代码块或解释性前后缀。"
    )
    user_prompt = (
        "任务：评价一个 retrieval case 的 rerank 质量。\n\n"
        "固定检查项：\n"
        f"{json.dumps(RETRIEVAL_RUBRIC, ensure_ascii=False, indent=2)}\n\n"
        "输出 JSON schema：\n"
        f"{json.dumps(_retrieval_report_example(), ensure_ascii=False, indent=2)}\n\n"
        "Reviewer 输入：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_writer_ab_review_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Creative KB benchmark 的 Writer A/B 增益诊断 Reviewer。\n"
        "你比较的是 KB references 对 Writer 输出的可观测增益，不是孤立评价文学性。\n"
        "必须基于 reference story synopsis、reference truth、各 variant draft、各 variant references 摘要判断："
        "kb_enabled 是否相对 kb_disabled/kb_random 更稳定、更少负迁移。\n"
        "Writer A/B 只提供诊断信号，不覆盖 retrieval / rerank 主评测结论。\n"
        "只输出严格 JSON，不要输出 Markdown、代码块或解释性前后缀。"
    )
    user_prompt = (
        "任务：比较 Creative KB Writer A/B variants，并判断 KB references 是否带来可观测增益。\n\n"
        "固定检查项：\n"
        f"{json.dumps(WRITER_AB_RUBRIC, ensure_ascii=False, indent=2)}\n\n"
        "输出 JSON schema：\n"
        f"{json.dumps(_writer_ab_report_example(), ensure_ascii=False, indent=2)}\n\n"
        "Reviewer 输入：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def _fragment_card_report_example() -> dict[str, object]:
    return {
        "decision": "pass|borderline|fail",
        "score": 0.72,
        "summary": "简短中文结论，说明主要优点和风险。",
        "checks": {
            "faithfulness": "pass|borderline|fail",
            "retrievability": "pass|borderline|fail",
            "narrative_function": "pass|borderline|fail",
            "emotion_mechanism": "pass|borderline|fail",
            "relationship_facts": "pass|borderline|fail",
            "style_transferability": "pass|borderline|fail",
            "context_dependency_risk": "pass|borderline|fail",
        },
        "issues": ["可选问题列表"],
    }


def _cluster_report_example() -> dict[str, object]:
    return {
        "decision": "pass|borderline|fail",
        "score": 0.68,
        "summary": "简短中文结论，说明近重复合理性、误合并风险和代表片段质量。",
        "checks": {
            "near_duplicate_fit": "pass|borderline|fail",
            "false_merge_risk": "pass|borderline|fail",
            "representative_quality": "pass|borderline|fail",
        },
        "issues": ["可选问题列表"],
    }


def _retrieval_report_example() -> dict[str, object]:
    return {
        "decision": "pass|borderline|fail",
        "score": 0.67,
        "summary": "简短中文结论，说明 selected references 相对 decoy 的优劣与主要风险。",
        "checks": {
            "top1_beats_decoys": "pass|borderline|fail",
            "selected_fragments_match_scene_brief": "pass|borderline|fail",
            "scene_function_fit": "pass|borderline|fail",
            "emotion_mechanism_fit": "pass|borderline|fail",
            "relationship_state_fit": "pass|borderline|fail",
            "style_reference_value": "pass|borderline|fail",
            "transferability": "pass|borderline|fail",
            "cluster_diversity": "pass|borderline|fail",
            "context_dependency_risk": "pass|borderline|fail",
            "negative_transfer_risk": "pass|borderline|fail",
        },
        "selected_fragment_ids": ["fragment-1"],
        "decoy_fragment_ids": ["fragment-9"],
        "issues": ["可选问题列表"],
    }


def _writer_ab_report_example() -> dict[str, object]:
    return {
        "decision": "pass|borderline|fail",
        "score": 0.63,
        "winner": "kb_enabled|kb_disabled|kb_random|kb_oracle|tie",
        "variant_scores": {
            "kb_enabled": 0.68,
            "kb_disabled": 0.53,
            "kb_random": 0.41,
        },
        "negative_transfer_issues": ["可选负迁移问题列表"],
        "summary": "简短中文结论，说明 KB references 是否带来可观测增益。",
        "checks": {
            "synopsis_coverage": "pass|borderline|fail",
            "recent_window_coherence": "pass|borderline|fail",
            "emotion_mechanism_quality": "pass|borderline|fail",
            "relationship_state_fit": "pass|borderline|fail",
            "style_stability": "pass|borderline|fail",
            "negative_transfer_from_references": "pass|borderline|fail",
        },
        "issues": ["可选问题列表"],
    }
