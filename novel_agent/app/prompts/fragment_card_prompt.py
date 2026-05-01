from __future__ import annotations

import json

from ..content_tags import build_content_tag_reference_text
from ..repos.documents_repo import DocumentRow

SOURCE_EXCERPT_PROMPT_CHARS = 1600


def build_fragment_card_prompt(document: DocumentRow) -> tuple[str, str]:
    tag_reference = build_content_tag_reference_text()
    source_excerpt = document.content[:SOURCE_EXCERPT_PROMPT_CHARS].strip()
    candidate_tags = "、".join(document.content_tags) if document.content_tags else "(无)"
    system_prompt = (
        "你是创作知识库的 fragment_card 建卡助手。\n"
        "你的任务是把单个小说 document 转成可检索、可复用的结构化 fragment_card。\n"
        "你必须只输出严格 JSON，不要输出解释、前后缀、分析散文或 Markdown 代码块。\n"
        "重要约束：\n"
        "1. preferred_tags 只能从提供的标签词典中选择，且最多 4 个。\n"
        "2. narrative_function_text、emotion_mechanism_text、character_relation_text、style_profile_text 必须写成 1-2 句可检索短句，不要写文学评论。\n"
        "3. 无证据则返回空数组或空字符串，不要编造人物、关系、场景或事件。\n"
        "4. transferability_score 必须是 0 到 1 之间的数值。\n"
        "5. context_dependency_level 只能是 low、medium、high 之一。\n"
        "6. 不要输出 doc_id、source_offsets、source_excerpt 以外的原文复制内容；这些字段由本地程序回填。\n"
        "7. 风格字段应服务于后续桥段检索和仿写，不做篇章赏析。\n"
    )
    user_prompt = (
        "任务：根据下面的 document 内容，生成 fragment_card 的结构化 JSON 字段。\n\n"
        "评分语义：\n"
        "- transferability_score:\n"
        "  - 0.0-0.2: 高度依赖专有设定或上下文，几乎不可复用。\n"
        "  - 0.3-0.5: 可借鉴局部写法，但桥段用途较窄。\n"
        "  - 0.6-0.8: 桥段结构和情绪机制较稳定，可直接作为参考。\n"
        "  - 0.9-1.0: 高可迁移的写法锚点，兼具清晰用途和低上下文依赖。\n"
        "- context_dependency_level:\n"
        "  - low: 不读前文也能理解桥段用途与情绪机制。\n"
        "  - medium: 需要少量上下文才能完整理解，但仍可复用写法。\n"
        "  - high: 强依赖特定人物关系、专有设定或前情，脱离上下文难以复用。\n\n"
        f"document 元数据：\n"
        f"- doc_id: {document.doc_id}\n"
        f"- document_title: {document.document_title}\n"
        f"- document_title_index: {document.document_title_index}\n"
        f"- source_path: {document.source_path or document.path}\n"
        f"- source_offsets: [{document.source_start_offset}, {document.source_end_offset}]\n"
        f"- 轻量标签候选: {candidate_tags}\n\n"
        "标签词典：\n"
        f"{tag_reference}\n\n"
        "document 正文：\n"
        f"{source_excerpt}\n\n"
        "请只输出如下 JSON 结构：\n"
        f"{json.dumps(_example_output(), ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def _example_output() -> dict[str, object]:
    return {
        "content_summary": "一句话概括这个桥段可复用的叙事用途与主要动作。",
        "narrative_function": ["收束过渡", "告别"],
        "narrative_function_text": "用克制停顿收束冲突后的关系张力，为后续离开或转场做准备。",
        "scene_space_tags": ["城市街道", "雨天"],
        "event_tags": ["告别"],
        "emotion_tags": ["悲伤低落", "克制"],
        "emotion_mechanism_text": "通过沉默、停顿、回避直视与延迟动作来表达压住的悲伤。",
        "expression_mode_tags": ["人物对话", "动作描写", "心理活动"],
        "preferred_tags": ["雨天", "告别"],
        "pov_mode": "近距离第三人称",
        "character_focus": ["角色A", "角色B"],
        "character_temperament": ["克制", "敏感"],
        "character_relation_text": "关系处在尚未和解的告别边缘，重点是情绪拉扯而非信息交换。",
        "relationship_state": ["未和解", "即将分离"],
        "continuity_phase": "冲突后收束",
        "style_features": {
            "sentence_rhythm": "短句偏多",
            "dialogue_density": "低",
            "interiority_density": "中高",
            "imagery_density": "中",
        },
        "style_profile_text": "短句、低对白、以动作停顿和少量心理描写承载情绪。",
        "transferability_score": 0.82,
        "context_dependency_level": "medium",
    }
