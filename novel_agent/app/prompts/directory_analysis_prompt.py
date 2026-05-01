from __future__ import annotations


def build_directory_analysis_prompt(*, tree_summary: str, source_root: str, book_id_hint: str) -> tuple[str, str]:
    system_prompt = (
        "你是小说目录分析助手。"
        "请根据给定目录树判断这是单文件、单书多文件还是多书目录，"
        "并输出严格 JSON，不要输出解释性文字。"
    )
    user_prompt = f"""
目标目录：{source_root}
book_id 提示：{book_id_hint}

目录树：
{tree_summary}

请输出 JSON，字段必须包含：
- strategy_type
- books: 每个元素包含 book_id, book_name, root_path, selected_paths, ignored_paths, read_order, confidence
- global_notes
"""
    return system_prompt, user_prompt.strip()
