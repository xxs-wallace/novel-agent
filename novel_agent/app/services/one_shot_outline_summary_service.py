from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..bootstrap import resolve_db_path
from ..llm import JsonModelClient
from ..repos.db import NovelAgentDB


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TextModelClient(Protocol):
    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_text: str | None = None,
        timeout_seconds: int | None = None,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        include_reasoning_content: bool | None = None,
    ) -> str:
        ...


@dataclass(frozen=True, slots=True)
class OneShotOutlineConfig:
    task_id: str
    base_task_id: str
    source_path: Path
    start_after_line: int
    output_dir: Path
    target_min_chars: int = 5000
    target_max_chars: int = 10000
    chunk_chars: int = 36000
    reference_chars: int = 22000
    character_limit: int = 28
    chunk_timeout_seconds: int = 300
    final_timeout_seconds: int = 600


@dataclass(frozen=True, slots=True)
class OneShotOutlineResult:
    task_id: str
    base_task_id: str
    source_excerpt_path: Path
    outline_path: Path
    chunk_summary_path: Path
    metadata_path: Path
    chunk_count: int
    outline_chars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "base_task_id": self.base_task_id,
            "source_excerpt_path": str(self.source_excerpt_path),
            "outline_path": str(self.outline_path),
            "chunk_summary_path": str(self.chunk_summary_path),
            "metadata_path": str(self.metadata_path),
            "chunk_count": self.chunk_count,
            "outline_chars": self.outline_chars,
        }


@dataclass(frozen=True, slots=True)
class CharacterReference:
    canonical_name: str
    aliases: list[str]
    mention_count: int
    importance_score: int
    profile_text: str


class OneShotOutlineSummaryService:
    """Build a read-only one-shot plot outline for a new source excerpt."""

    def __init__(self, *, repo_root: Path, model_client: TextModelClient | JsonModelClient) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.model_client = model_client

    def run(self, config: OneShotOutlineConfig) -> OneShotOutlineResult:
        output_dir = config.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        source_excerpt_path = output_dir / "source_after_line_56706.txt"
        outline_path = output_dir / "outline.md"
        chunk_summary_path = output_dir / "chunk_summaries.md"
        metadata_path = output_dir / "metadata.json"

        source_text = self.extract_after_line(
            source_path=config.source_path,
            start_after_line=config.start_after_line,
            output_path=source_excerpt_path,
        )
        self.ensure_task_registry_entry(task_id=config.task_id, source_path=source_excerpt_path)
        reference_packet = self.build_reference_packet(
            base_task_id=config.base_task_id,
            new_source_text=source_text,
            max_chars=config.reference_chars,
            character_limit=config.character_limit,
        )
        chunks = self.split_text(source_text, max_chars=config.chunk_chars)
        chunk_summaries = [
            self.summarize_chunk(
                chunk_text=chunk,
                chunk_index=index,
                chunk_count=len(chunks),
                reference_packet=reference_packet,
                timeout_seconds=config.chunk_timeout_seconds,
            )
            for index, chunk in enumerate(chunks, start=1)
        ]
        outline = self.synthesize_outline(
            chunk_summaries=chunk_summaries,
            reference_packet=reference_packet,
            target_min_chars=config.target_min_chars,
            target_max_chars=config.target_max_chars,
            timeout_seconds=config.final_timeout_seconds,
        )
        outline_path.write_text(outline.strip() + "\n", encoding="utf-8")
        chunk_summary_path.write_text(
            self._render_chunk_summaries(chunk_summaries),
            encoding="utf-8",
        )
        metadata = {
            "task_id": config.task_id,
            "base_task_id": config.base_task_id,
            "source_path": str(config.source_path.expanduser().resolve()),
            "source_excerpt_path": str(source_excerpt_path),
            "start_after_line": config.start_after_line,
            "generated_at": _utc_now(),
            "chunk_count": len(chunks),
            "chunk_chars": config.chunk_chars,
            "target_min_chars": config.target_min_chars,
            "target_max_chars": config.target_max_chars,
            "reference": reference_packet["metadata"],
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return OneShotOutlineResult(
            task_id=config.task_id,
            base_task_id=config.base_task_id,
            source_excerpt_path=source_excerpt_path,
            outline_path=outline_path,
            chunk_summary_path=chunk_summary_path,
            metadata_path=metadata_path,
            chunk_count=len(chunks),
            outline_chars=len(outline),
        )

    def extract_after_line(self, *, source_path: Path, start_after_line: int, output_path: Path) -> str:
        if start_after_line < 0:
            raise ValueError("start_after_line must be >= 0")
        source_path = source_path.expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"source file not found: {source_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        with source_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, start=1):
                if line_no > start_after_line:
                    lines.append(line)
        text = "".join(lines)
        if not text.strip():
            raise ValueError(f"no text found after line {start_after_line}: {source_path}")
        output_path.write_text(text, encoding="utf-8")
        return text

    def ensure_task_registry_entry(self, *, task_id: str, source_path: Path) -> None:
        normalized = str(task_id or "").strip()
        if not normalized:
            raise ValueError("task id 不能为空")
        registry_path = self.repo_root / ".indexes" / "tasks.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        if registry_path.exists():
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            tasks = payload if isinstance(payload, dict) else {}
        else:
            tasks = {}
        existing = dict(tasks.get(normalized, {})) if isinstance(tasks.get(normalized), dict) else {}
        existing["source_path"] = str(source_path.expanduser().resolve())
        tasks[normalized] = existing
        registry_path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def build_reference_packet(
        self,
        *,
        base_task_id: str,
        new_source_text: str,
        max_chars: int,
        character_limit: int,
    ) -> dict[str, Any]:
        outline_text = self._read_text(self.repo_root / ".memory" / "outlines" / f"{base_task_id}.outline.md")
        world_summary = self._read_text(self.repo_root / ".memory" / "worlds" / f"{base_task_id}.world_summary.md")
        base_db_path = resolve_db_path(self.repo_root, str(self.repo_root / ".indexes" / f"{base_task_id}.db"))
        character_refs = self._load_character_references(
            db_path=base_db_path,
            base_task_id=base_task_id,
            new_source_text=new_source_text,
            limit=character_limit,
        )
        compact_outline = self._compact_outline(outline_text, max_chars=max(4000, max_chars // 2))
        compact_world = self._trim_text(world_summary, 3000)
        compact_characters = self._render_character_references(
            character_refs,
            max_chars=max(4000, max_chars - len(compact_outline) - len(compact_world)),
        )
        reference_text = "\n\n".join(
            part
            for part in [
                "# 前置大纲（只读）\n" + compact_outline if compact_outline else "",
                "# 世界观概要（只读）\n" + compact_world if compact_world else "",
                "# 命中新文档的人物档案（只读）\n" + compact_characters if compact_characters else "",
            ]
            if part.strip()
        )
        return {
            "text": self._trim_text(reference_text, max_chars),
            "metadata": {
                "outline_chars": len(outline_text),
                "world_summary_chars": len(world_summary),
                "selected_character_count": len(character_refs),
                "selected_characters": [
                    {
                        "canonical_name": item.canonical_name,
                        "mention_count": item.mention_count,
                        "importance_score": item.importance_score,
                    }
                    for item in character_refs
                ],
            },
        }

    def split_text(self, text: str, *, max_chars: int) -> list[str]:
        if max_chars <= 0:
            raise ValueError("max_chars must be > 0")
        paragraphs = re.split(r"(\n{2,})", text)
        chunks: list[str] = []
        current = ""
        for part in paragraphs:
            if not part:
                continue
            if len(current) + len(part) <= max_chars:
                current += part
                continue
            if current.strip():
                chunks.append(current.strip())
                current = ""
            if len(part) <= max_chars:
                current = part
                continue
            for start in range(0, len(part), max_chars):
                chunks.append(part[start : start + max_chars].strip())
        if current.strip():
            chunks.append(current.strip())
        return [chunk for chunk in chunks if chunk]

    def summarize_chunk(
        self,
        *,
        chunk_text: str,
        chunk_index: int,
        chunk_count: int,
        reference_packet: dict[str, Any],
        timeout_seconds: int,
    ) -> str:
        system_prompt = (
            "你是小说续写系统中的只读剧情概括 Agent。你只能概括输入文本已经发生的剧情，"
            "可以使用前置大纲和人物档案来消歧，但不得更新人物档案、不得做人设特征抽取，"
            "不得把猜测写成事实。输出中文自然语言剧情梗概。"
        )
        user_prompt = (
            f"这是一次性新文档概括任务的第 {chunk_index}/{chunk_count} 个文本窗口。\n\n"
            "【前三部只读参考】\n"
            f"{reference_packet.get('text', '')}\n\n"
            "【当前新文档窗口原文】\n"
            f"{chunk_text}\n\n"
            "请按原文顺序概括本窗口剧情，保留主要因果、人物行动、关系变化、设定揭示和悬念。"
            "不要输出人物档案、标签、表格或数据库字段。篇幅控制在 900-1600 个中文字符。"
        )
        return self.model_client.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=timeout_seconds,
            thinking="disabled",
            include_reasoning_content=False,
        ).strip()

    def synthesize_outline(
        self,
        *,
        chunk_summaries: list[str],
        reference_packet: dict[str, Any],
        target_min_chars: int,
        target_max_chars: int,
        timeout_seconds: int,
    ) -> str:
        system_prompt = (
            "你是小说续写系统中的只读大纲整理 Agent。你的任务是把分块剧情梗概整合为自然语言大纲。"
            "不得更新或生成任何人物档案；不得做人设特征提取；不得把前三部参考资料改写为新文档剧情。"
        )
        joined_summaries = "\n\n".join(
            f"【窗口 {index}】\n{summary}" for index, summary in enumerate(chunk_summaries, start=1)
        )
        user_prompt = (
            "请根据下面的分块梗概，产出一份完整自然语言大纲。\n"
            f"目标篇幅：{target_min_chars}-{target_max_chars} 个中文字符左右。\n"
            "要求：\n"
            "1. 按新文档自身剧情顺序组织，不写数据库状态或内部任务术语。\n"
            "2. 可以用少量小标题分段，但主体必须是连贯自然语言。\n"
            "3. 保留主线推进、关键转折、人物选择、情绪线、设定揭示、未解悬念。\n"
            "4. 只把前三部资料当作只读背景，不要污染或改写旧任务记忆。\n\n"
            "【前三部只读参考摘要】\n"
            f"{reference_packet.get('text', '')}\n\n"
            "【新文档分块梗概】\n"
            f"{joined_summaries}"
        )
        return self.model_client.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=timeout_seconds,
            thinking="disabled",
            include_reasoning_content=False,
        ).strip()

    def _load_character_references(
        self,
        *,
        db_path: Path,
        base_task_id: str,
        new_source_text: str,
        limit: int,
    ) -> list[CharacterReference]:
        if not db_path.exists():
            return []
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT canonical_name, aliases_json, profile_summary_md, profile_brief_json, recent_activity_json,
                       relationships_json, story_events_json, importance_score
                FROM character_profiles
                WHERE book_id = ?
                ORDER BY importance_score DESC, canonical_name
                """,
                (base_task_id,),
            ).fetchall()
        refs = [self._row_to_character_reference(row, new_source_text=new_source_text) for row in rows]
        refs = [item for item in refs if item.mention_count > 0 or item.importance_score > 0]
        return sorted(refs, key=lambda item: (item.mention_count, item.importance_score, item.canonical_name), reverse=True)[
            :limit
        ]

    def _row_to_character_reference(self, row: sqlite3.Row, *, new_source_text: str) -> CharacterReference:
        aliases = [str(item) for item in self._json_list(row["aliases_json"]) if str(item).strip()]
        names = [str(row["canonical_name"]), *aliases]
        mention_count = sum(new_source_text.count(name) for name in names if name)
        profile_parts = [
            str(row["profile_summary_md"] or ""),
            self._json_preview(row["profile_brief_json"]),
            self._json_preview(row["recent_activity_json"]),
            self._json_preview(row["relationships_json"]),
            self._json_preview(row["story_events_json"]),
        ]
        return CharacterReference(
            canonical_name=str(row["canonical_name"]),
            aliases=aliases,
            mention_count=mention_count,
            importance_score=int(row["importance_score"] or 0),
            profile_text=self._trim_text("\n".join(part for part in profile_parts if part.strip()), 900),
        )

    def _compact_outline(self, outline_text: str, *, max_chars: int) -> str:
        if not outline_text.strip():
            return ""
        root_blocks = re.findall(r"(?ms)^###\s+(.+?)(?=^###\s+|\Z)", outline_text)
        if root_blocks:
            compact = "\n\n".join(self._trim_text(block.strip(), 900) for block in root_blocks)
            return self._trim_text(compact, max_chars)
        return self._trim_text(outline_text, max_chars)

    def _render_character_references(self, refs: list[CharacterReference], *, max_chars: int) -> str:
        parts = []
        for item in refs:
            alias_text = "、".join(item.aliases[:6])
            header = f"## {item.canonical_name}（新文档命中 {item.mention_count} 次"
            if item.importance_score:
                header += f"，旧档重要度 {item.importance_score}"
            header += "）"
            if alias_text:
                header += f"\n别名：{alias_text}"
            parts.append(f"{header}\n{item.profile_text}".strip())
        return self._trim_text("\n\n".join(parts), max_chars)

    def _render_chunk_summaries(self, summaries: list[str]) -> str:
        lines = ["# 分块剧情梗概", ""]
        for index, summary in enumerate(summaries, start=1):
            lines.extend([f"## 窗口 {index}", "", summary.strip(), ""])
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _read_text(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _trim_text(text: str, max_chars: int) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 20)].rstrip() + "\n[...已截断...]"

    @staticmethod
    def _json_list(raw_value: object) -> list[Any]:
        if not raw_value:
            return []
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    @staticmethod
    def _json_preview(raw_value: object) -> str:
        if not raw_value:
            return ""
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return str(raw_value)
        if value in ({}, []):
            return ""
        return json.dumps(value, ensure_ascii=False)
