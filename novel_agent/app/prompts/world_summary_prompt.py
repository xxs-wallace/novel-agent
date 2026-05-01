from __future__ import annotations


def build_world_summary_prompt(world_markdown: str) -> tuple[str, str]:
    system_prompt = (
        "你是世界观压缩助手。"
        "请把详细世界观文档压缩成不超过 1KB 的 Markdown 概要，只保留最影响后续阅读和续写的设定。"
        "输出必须保留固定分区：世界类型、时代背景、能力体系、超自然要素、阵营势力、核心禁忌与规则。"
    )
    user_prompt = f"请压缩以下世界观文档：\n\n{world_markdown}"
    return system_prompt, user_prompt
