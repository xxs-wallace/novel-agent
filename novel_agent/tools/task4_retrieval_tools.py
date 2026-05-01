from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smolagents import Tool


def _repo_root() -> Path:
    override = os.getenv("NOVEL_AGENT_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def _db_path() -> Path:
    override = os.getenv("NOVEL_AGENT_INDEX_DB")
    if override:
        return Path(override).resolve()
    return _repo_root() / "novel_agent" / "indexes" / "novel.db"


def _safe_snippet(text: str, *, limit: int = 240) -> str:
    s = re.sub(r"\s+", " ", text).strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (0x3400 <= code <= 0x4DBF) or (0x4E00 <= code <= 0x9FFF)


def _prepare_fts_query(query: str) -> str:
    q = query.strip()
    if not q:
        return q
    if all(_is_cjk(ch) for ch in q):
        return " ".join(list(q))
    return q


def _rel_path(path: Path, *, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _scope_from_rel_path(rel_path: str) -> str:
    if "/" not in rel_path:
        return ""
    return rel_path.split("/", 1)[0]


def _tool_response(
    *,
    tool: str,
    ok: bool,
    tool_input: dict[str, Any],
    output: dict[str, Any] | None,
    sources: list[dict[str, Any]],
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "ok": ok,
        "input": tool_input,
        "output": output,
        "sources": sources,
        "error": error,
    }


@dataclass(frozen=True, slots=True)
class _FtsHit:
    path: str
    scope: str
    title: str | None
    rank: float
    snippet: str


class _SQLiteFtsClient:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def search(
        self,
        query: str,
        *,
        scope: str | None = None,
        path_prefix: str | None = None,
        limit: int = 20,
    ) -> list[_FtsHit]:
        prepared = _prepare_fts_query(query)
        if not prepared:
            return []

        where = ["documents_fts MATCH ?"]
        params: list[object] = [prepared]

        if scope:
            where.append("documents.scope = ?")
            params.append(scope)
        if path_prefix:
            where.append("documents.path LIKE ?")
            prefix = path_prefix if path_prefix.endswith("/") else f"{path_prefix}/"
            params.append(f"{prefix}%")

        sql = f"""
        SELECT
            documents.path AS path,
            documents.scope AS scope,
            documents.title AS title,
            bm25(documents_fts) AS rank,
            snippet(documents_fts, 0, '', '', '…', 18) AS snippet
        FROM documents_fts
        JOIN documents ON documents_fts.rowid = documents.doc_id
        WHERE {" AND ".join(where)}
        ORDER BY rank
        LIMIT ?
        """
        params.append(int(limit))

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        hits: list[_FtsHit] = []
        for row in rows:
            hits.append(
                _FtsHit(
                    path=str(row["path"]),
                    scope=str(row["scope"]),
                    title=str(row["title"]) if row["title"] is not None else None,
                    rank=float(row["rank"]),
                    snippet=str(row["snippet"]) if row["snippet"] is not None else "",
                )
            )
        return hits


class _CharacterAliasResolver:
    def __init__(self) -> None:
        self._cached_root: Path | None = None
        self._alias_to_canonical: dict[str, str] = {}
        self._canonical_to_aliases: dict[str, set[str]] = {}

    def _load_from_analysis(self, repo_root: Path) -> None:
        analysis_root = repo_root / "analysis"
        if not analysis_root.exists():
            return
        for md_path in sorted(analysis_root.rglob("*.md")):
            if not md_path.is_file():
                continue
            canonical = md_path.stem.strip()
            if not canonical:
                continue
            text = md_path.read_text(encoding="utf-8", errors="replace")
            found = []
            for m in re.finditer(r"(?:别名|aliases)\s*[:：]\s*(.+)", text, flags=re.IGNORECASE):
                found.append(m.group(1))
            if not found:
                continue
            raw = " ".join(found)
            candidates = [s.strip() for s in re.split(r"[，,、;/\n\r\t]+", raw) if s.strip()]
            if not candidates:
                continue
            aliases = self._canonical_to_aliases.setdefault(canonical, set())
            for a in candidates:
                if a and a != canonical:
                    aliases.add(a)
                    self._alias_to_canonical.setdefault(a, canonical)

    def ensure_loaded(self, repo_root: Path) -> None:
        if self._cached_root == repo_root:
            return
        self._cached_root = repo_root
        self._alias_to_canonical = {}
        self._canonical_to_aliases = {}
        self._load_from_analysis(repo_root)

    def variants(self, name: str, *, repo_root: Path) -> tuple[str, list[str]]:
        self.ensure_loaded(repo_root)
        n = name.strip()
        if not n:
            return "", []
        canonical = self._alias_to_canonical.get(n, n)
        aliases = sorted(self._canonical_to_aliases.get(canonical, set()))
        variants = [canonical, *aliases]
        seen: set[str] = set()
        out: list[str] = []
        for v in variants:
            v = v.strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return canonical, out


def _fts_or_query(terms: list[str]) -> str:
    prepared = [_prepare_fts_query(t) for t in terms if t.strip()]
    prepared = [p for p in prepared if p.strip()]
    if not prepared:
        return ""
    parts = [f"({p})" for p in prepared]
    return " OR ".join(parts)


class ReadAnchorContextTool(Tool):
    name = "read_anchor_context"
    description = "按 segment_path 读取锚点相邻分片窗口内容，并返回统一 sources。"
    inputs = {
        "segment_path": {
            "type": "string",
            "description": "锚点分片路径（相对仓库根目录）。例如 longzu_split/seg_001.md",
        },
        "window_before": {"type": "integer", "description": "向前读取的相邻分片数量。", "nullable": True},
        "window_after": {"type": "integer", "description": "向后读取的相邻分片数量。", "nullable": True},
    }
    output_type = "object"
    output_schema = {
        "type": "object",
        "required": ["tool", "ok", "input", "output", "sources", "error"],
        "properties": {
            "tool": {"type": "string"},
            "ok": {"type": "boolean"},
            "input": {"type": "object"},
            "output": {"type": ["object", "null"]},
            "sources": {"type": "array"},
            "error": {"type": ["string", "null"]},
        },
    }

    def forward(self, segment_path: str, window_before: int = 1, window_after: int = 1) -> dict[str, Any]:
        tool_input = {"segment_path": segment_path, "window_before": window_before, "window_after": window_after}
        repo_root = _repo_root()
        anchor_abs = (repo_root / segment_path).resolve()
        if not anchor_abs.exists() or not anchor_abs.is_file():
            return _tool_response(
                tool=self.name,
                ok=False,
                tool_input=tool_input,
                output=None,
                sources=[],
                error=f"segment_path not found: {segment_path}",
            )

        siblings = sorted([p for p in anchor_abs.parent.glob("*.md") if p.is_file()], key=lambda p: p.name)
        resolved = [p.resolve() for p in siblings]
        try:
            idx = resolved.index(anchor_abs)
        except ValueError:
            idx = 0

        before = max(int(window_before), 0)
        after = max(int(window_after), 0)
        start = max(0, idx - before)
        end = min(len(siblings) - 1, idx + after)
        window_paths = siblings[start : end + 1]

        contents: list[str] = []
        sources: list[dict[str, Any]] = []
        for p in window_paths:
            rel = _rel_path(p, repo_root=repo_root)
            scope = _scope_from_rel_path(rel)
            text = p.read_text(encoding="utf-8", errors="replace")
            contents.append(text)
            sources.append({"path": rel, "scope": scope, "snippet": _safe_snippet(text)})

        output = {
            "anchor_path": _rel_path(anchor_abs, repo_root=repo_root),
            "window_before": before,
            "window_after": after,
            "paths": [_rel_path(p, repo_root=repo_root) for p in window_paths],
            "content": "\n\n".join(contents).strip(),
        }
        return _tool_response(
            tool=self.name, ok=True, tool_input=tool_input, output=output, sources=sources, error=None
        )


class SearchByCharacterTool(Tool):
    name = "search_by_character"
    description = "输入人物名或别名，扩展为候选集合后进行 FTS 检索并返回统一 sources。"
    inputs = {
        "name": {"type": "string", "description": "人物名或别名。"},
        "scope": {
            "type": "string",
            "description": "可选 scope 过滤（例如 longzu_split、analysis）。",
            "nullable": True,
        },
        "limit": {"type": "integer", "description": "返回条数上限。", "nullable": True},
    }
    output_type = "object"
    output_schema = ReadAnchorContextTool.output_schema

    def __init__(self) -> None:
        super().__init__()
        self._alias_resolver = _CharacterAliasResolver()

    def forward(self, name: str, scope: str | None = None, limit: int = 20) -> dict[str, Any]:
        tool_input = {"name": name, "scope": scope, "limit": limit}
        repo_root = _repo_root()
        canonical, variants = self._alias_resolver.variants(name, repo_root=repo_root)
        query = _fts_or_query(variants)
        if not query:
            return _tool_response(
                tool=self.name, ok=False, tool_input=tool_input, output=None, sources=[], error="name is empty"
            )

        hits = _SQLiteFtsClient(_db_path()).search(query, scope=scope, limit=int(limit))
        sources = [{"path": h.path, "scope": h.scope, "snippet": h.snippet or "", "rank": h.rank} for h in hits]
        output = {
            "canonical": canonical,
            "variants": variants,
            "hits": [{"path": h.path, "scope": h.scope, "title": h.title, "rank": h.rank} for h in hits],
        }
        return _tool_response(
            tool=self.name, ok=True, tool_input=tool_input, output=output, sources=sources, error=None
        )


class SearchLoreTool(Tool):
    name = "search_lore"
    description = "根据 keyword 进行 FTS 检索，可选 layer/path_prefix 过滤，返回统一 sources。"
    inputs = {
        "keyword": {"type": "string", "description": "检索关键词。"},
        "layer": {
            "type": "string",
            "description": "可选 layer（映射为 analysis/<layer> 的 path_prefix 过滤）。",
            "nullable": True,
        },
        "scope": {"type": "string", "description": "可选 scope 过滤。默认 analysis。", "nullable": True},
        "limit": {"type": "integer", "description": "返回条数上限。", "nullable": True},
    }
    output_type = "object"
    output_schema = ReadAnchorContextTool.output_schema

    def forward(
        self, keyword: str, layer: str | None = None, scope: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        tool_input = {"keyword": keyword, "layer": layer, "scope": scope, "limit": limit}
        query = keyword.strip()
        if not query:
            return _tool_response(
                tool=self.name, ok=False, tool_input=tool_input, output=None, sources=[], error="keyword is empty"
            )

        effective_scope = scope if scope is not None else "analysis"
        path_prefix = None
        if layer:
            layer_clean = layer.strip().lstrip("/")
            path_prefix = layer_clean if layer_clean.startswith("analysis/") else f"analysis/{layer_clean}"

        hits = _SQLiteFtsClient(_db_path()).search(
            query, scope=effective_scope, path_prefix=path_prefix, limit=int(limit)
        )
        sources = [{"path": h.path, "scope": h.scope, "snippet": h.snippet or "", "rank": h.rank} for h in hits]
        output = {
            "keyword": keyword,
            "scope": effective_scope,
            "layer": layer,
            "path_prefix": path_prefix,
            "hits": [{"path": h.path, "scope": h.scope, "title": h.title, "rank": h.rank} for h in hits],
        }
        return _tool_response(
            tool=self.name, ok=True, tool_input=tool_input, output=output, sources=sources, error=None
        )


class SearchByTimelineTool(Tool):
    name = "search_by_timeline"
    description = "在章节分片中做关键词检索，并按分片序号范围与顺序返回统一 sources。"
    inputs = {
        "keyword": {"type": "string", "description": "检索关键词。"},
        "start": {"type": "integer", "description": "可选起始分片序号（含）。", "nullable": True},
        "end": {"type": "integer", "description": "可选结束分片序号（含）。", "nullable": True},
        "scope": {"type": "string", "description": "可选 scope 过滤。默认 longzu_split。", "nullable": True},
        "limit": {"type": "integer", "description": "返回条数上限。", "nullable": True},
    }
    output_type = "object"
    output_schema = ReadAnchorContextTool.output_schema

    def _segment_no(self, path: str) -> int | None:
        name = Path(path).stem
        m = re.search(r"(\d+)", name)
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    def forward(
        self,
        keyword: str,
        start: int | None = None,
        end: int | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        tool_input = {"keyword": keyword, "start": start, "end": end, "scope": scope, "limit": limit}
        query = keyword.strip()
        if not query:
            return _tool_response(
                tool=self.name, ok=False, tool_input=tool_input, output=None, sources=[], error="keyword is empty"
            )

        effective_scope = scope if scope is not None else "longzu_split"
        hits = _SQLiteFtsClient(_db_path()).search(query, scope=effective_scope, limit=int(limit))

        lo: int | None = int(start) if start is not None else None
        hi: int | None = int(end) if end is not None else None
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo

        filtered: list[tuple[_FtsHit, int | None]] = [(h, self._segment_no(h.path)) for h in hits]
        if lo is not None or hi is not None:
            out_filtered = []
            for h, no in filtered:
                if no is None:
                    continue
                if lo is not None and no < lo:
                    continue
                if hi is not None and no > hi:
                    continue
                out_filtered.append((h, no))
            filtered = out_filtered
            filtered.sort(key=lambda t: (t[1] is None, t[1] if t[1] is not None else 0, t[0].path))

        final_hits = [h for h, _ in filtered]
        sources = [{"path": h.path, "scope": h.scope, "snippet": h.snippet or "", "rank": h.rank} for h in final_hits]
        output = {
            "keyword": keyword,
            "scope": effective_scope,
            "start": lo,
            "end": hi,
            "hits": [{"path": h.path, "scope": h.scope, "title": h.title, "rank": h.rank} for h in final_hits],
        }
        return _tool_response(
            tool=self.name, ok=True, tool_input=tool_input, output=output, sources=sources, error=None
        )


NOVEL_AGENT_TOOL_MAPPING: dict[str, type[Tool]] = {
    ReadAnchorContextTool.name: ReadAnchorContextTool,
    SearchByCharacterTool.name: SearchByCharacterTool,
    SearchLoreTool.name: SearchLoreTool,
    SearchByTimelineTool.name: SearchByTimelineTool,
}
