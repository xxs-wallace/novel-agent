from __future__ import annotations

import json

from ..content_tags import build_content_tag_reference_text
from ..schemas.prompt_io_schema import SegmentationInputSegment


def build_segmentation_prompt(
    *,
    batch_segments: list[SegmentationInputSegment],
    file_context: str,
    chunk_min: int,
    chunk_max: int,
    doc_min: int,
    doc_max: int,
    toc_context: str = "",
    resume_document_title: str = "",
    resume_context: str = "",
) -> tuple[str, str]:
    tag_reference = build_content_tag_reference_text()
    segments_json = json.dumps([segment.to_dict() for segment in batch_segments], ensure_ascii=False, indent=2)
    resume_context_section = ""
    if resume_context.strip():
        resume_context_section = (
            "\n续传衔接上下文（仅用于判断章节与段落连续性，禁止重复写入 documents.content）：\n"
            f"- 上一条 document 标题：{resume_document_title or '(未知)'}\n"
            f"- 上一条 document 尾部节选：\n{resume_context.strip()}\n"
        )
    chapter_split_chars = max(doc_max * 2, chunk_min)
    system_prompt = (
        "你是小说粗读与分段助手。\n"
        "任务是把输入 segments 按原顺序分组成可写入 SQLite documents 表的若干 document，并提取内容标签。\n"
        "你必须输出严格 JSON，不要输出解释、前后缀或 Markdown 代码块。\n"
        "重要约束：\n"
        "1. 不要改写原文，不要总结原文；系统会根据你返回的 segment_ids 在本地重建 documents.content。\n"
        "2. 粗读阶段不负责人物提取，character_keywords 必须始终返回空数组。\n"
        "3. content_tags 必须只从提供的标签词典中选择，不要自造标签。\n"
        "4. 每个 document 最多只保留 4 个 content_tags；应先在不同标签组里选高置信标签，再按全局相关性排序。\n"
        "5. document_title_index 表示章节/卷/幕级边界，不表示场景、地点、视角或情绪小节。\n"
        "6. 同一章节的多个 document 必须共享相同的 document_title_index；不要因为场景变化就频繁新建章节。\n"
        "7. document_title 应优先使用原文显式章节名；没有显式章节名时使用稳定的“未命名章节-N”，不要为每个 document 自由概括标题。\n"
        "8. 如果某个 segment 内容极短、独占一行，且包含阿拉伯数字或中文数字（如 1、01、一、二十、十五），它很可能是章节名或小节名；若同时出现 第/章/幕/卷/节/Chapter/Part 等标记，应优先作为章节边界。\n"
        f"9. 如果长时间未发现章节名，且同一章节累计已超过约 {chapter_split_chars} 字符，同时连续内容在时间、地点、主行动、叙事视角或核心冲突上发生显著变化，可以开启新的“未命名章节-N”；否则继续沿用当前章节。\n"
        "10. 若提供了续传衔接上下文，它只用于帮助判断章节边界和句段延续，不要把其中已出现的文本重复映射到本批次 segment_ids。\n"
        "11. 你必须覆盖全部输入 segment；每个 segment 只能出现在一个 document 中；segment_ids 必须按原顺序递增。\n"
    )
    user_prompt = f"""
输入批次说明：
- 批次正文目标长度：{chunk_min} 到 {chunk_max} 字符
- 单个 document 推荐长度：{doc_min} 到 {doc_max} 字符
- 若原文已经显式带有章节名，请复用章节名生成 document_title
- 同一章节的多个 document 必须共享同一个 document_title_index
- 没有显式章节名时，优先沿用上一章节；不要把普通场景转场、心理变化、对话主题变化当作新章节
- 极短且含数字的独立 segment 往往是章节标题；中文数字也算数字，例如“一、二、三、十、十五、二十”
- 若同一章节累计超过约 {chapter_split_chars} 字符且内容发生显著断裂，可开启新的“未命名章节-N”
- 每个 document 的 character_keywords 固定返回空数组，人物分析留给精读阶段
- 每个 document 必须提炼 content_tags
- 不要改写原文语义
- 你只需要返回分组后的 segment_ids，不要返回 content
- 若已检测到目录，请优先参考目录中的章节名和顺序做分段，避免把“目录页”误当成正文章节

标签词典：
{tag_reference}

已检测目录：
{toc_context or "(未检测到目录)"}
{resume_context_section}

文件上下文：
{file_context}

输入 segments（segment_id 按原文顺序排列，每段约 100 到 1000 字节）：
{segments_json}

请输出以下 JSON 结构：
{{
  "document_title_index_start": 100,
  "documents": [
    {{
      "document_local_id": 1,
      "document_title": "第一章 新的线索",
      "document_title_index": 100,
      "inferred_chapter_no": 1,
      "segment_ids": [1, 2, 3, 4],
      "character_keywords": [],
      "content_tags": ["校园", "学习考试", "人物对话", "心理活动"],
      "segmentation_reason": "按章节自然段切分",
      "continuity_hint": "承接上一段对话"
    }}
  ],
  "batch_summary": {{
    "chapter_count": 1,
    "document_count": 1,
    "new_characters": []
  }}
}}
"""
    return system_prompt, user_prompt.strip()
