from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from ..constants import DEFAULT_SEGMENTATION_STAGE
from ..content_tags import ALLOWED_CONTENT_TAGS, CONTENT_TAG_GROUP_PRIORITY, CONTENT_TAG_TO_GROUP
from ..llm import InvalidJSONResponseError, JsonModelClient
from ..prompts.segmentation_prompt import build_segmentation_prompt
from ..repos.documents_repo import DocumentsRepo
from ..repos.reading_progress_repo import ReadingProgressRepo
from ..schemas.prompt_io_schema import (
    SegmentationBatchSummary,
    SegmentationInputSegment,
    SegmentationPromptOutput,
    SegmentedDocumentOutput,
)
from ..utils.text_utils import markdown_title
from .chapter_boundary_detector import ChapterBoundaryCandidate, ChapterBoundaryDetector
from .chinese_text_analyzer import ChineseTextAnalyzer
from .chunk_reader_service import TextBatch


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


CONTENT_TAG_ALIASES = {
    "景物描写": "景色描写",
    "场景描写": "环境描写",
    "对白": "人物对话",
    "对话描写": "人物对话",
    "心理描写": "心理活动",
    "内心活动": "心理活动",
    "情绪描写": "心理活动",
    "动作场面": "动作描写",
    "都市": "城市",
    "古城": "遗迹古城",
}

CONTENT_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "景色描写": ("天空", "阳光", "月光", "星光", "江面", "湖面", "树林", "山", "花", "风景"),
    "环境描写": ("房间", "走廊", "楼道", "门", "窗", "屋里", "大厅", "座位", "街道"),
    "天气描写": ("下雨", "暴雨", "雨水", "雨点", "雪", "风", "雷", "雾"),
    "外貌描写": ("眉", "眼睛", "头发", "脸", "嘴唇", "身材", "衣服", "校服"),
    "神态描写": ("皱眉", "微笑", "冷笑", "发呆", "愣住", "沉默", "表情", "眼神"),
    "动作描写": ("站起", "坐下", "走", "跑", "推开", "抓住", "抬头", "低头", "转身"),
    "人物对话": ("“", "”", "说道", "问", "回答", "开口", "嘀咕", "喊"),
    "心理活动": ("心里", "想着", "觉得", "忽然意识到", "不禁", "害怕", "犹豫", "后悔"),
    "内心独白": ("他想", "她想", "我想", "心想", "告诉自己"),
    "感官描写": ("闻到", "听见", "看见", "触到", "刺痛", "冰冷", "灼热"),
    "设定说明": ("传说", "规则", "体系", "能力", "组织", "禁忌", "设定"),
    "信息揭示": ("原来", "发现", "得知", "真相", "揭开", "终于明白"),
    "伏笔埋设": ("似乎", "隐约", "也许", "仿佛预示", "后来才知道"),
    "悬念制造": ("为什么", "难道", "究竟", "秘密", "神秘", "无法解释"),
    "冲突升级": ("争吵", "冲突", "逼近", "威胁", "失控", "压迫"),
    "回忆插叙": ("想起", "回忆", "那一年", "曾经", "从前"),
    "梦境幻觉": ("梦", "梦里", "惊醒", "幻觉", "幻象"),
    "任务发布": ("任务", "委托", "命令", "通知", "安排"),
    "情报交换": ("情报", "消息", "线索", "资料", "告诉他"),
    "调查": ("调查", "查找", "追查", "线索", "档案"),
    "谈判": ("条件", "交换", "让步", "协议", "谈判"),
    "训练": ("训练", "练习", "课程", "测试"),
    "战斗描写": ("战斗", "厮杀", "开枪", "爆炸", "血", "刀", "剑", "攻击"),
    "受伤疗伤": ("受伤", "流血", "包扎", "治疗", "疼痛"),
    "学习考试": ("考试", "作业", "成绩", "课堂", "学习", "高考"),
    "社交聚会": ("聚会", "派对", "舞会", "聚餐", "宴会"),
    "通信联络": ("手机", "电话", "短信", "QQ", "邮件", "来电"),
    "入学面试": ("录取", "面试", "通知书", "申请", "入学"),
    "校园": ("学校", "学院", "高中", "大学", "学生", "老师"),
    "教室": ("教室", "讲台", "黑板", "课桌"),
    "宿舍": ("宿舍", "寝室", "床位", "上铺"),
    "图书馆": ("图书馆", "书架", "阅览室"),
    "操场": ("操场", "跑道", "球场"),
    "食堂": ("食堂", "餐盘", "打饭"),
    "家庭住宅": ("家里", "叔叔", "婶婶", "卧室", "客厅", "厨房"),
    "城市": ("城市", "城区", "霓虹", "高楼"),
    "城市街道": ("街道", "路口", "小区", "商店", "报摊"),
    "医院": ("医院", "病房", "医生", "护士"),
    "乡村": ("村", "乡下", "田地", "镇上"),
    "森林": ("森林", "树林", "树影"),
    "山地": ("山", "山路", "山坡"),
    "河湖海": ("江", "河", "湖", "海", "水面"),
    "地下空间": ("地下", "隧道", "地窖", "井下"),
    "遗迹古城": ("古城", "遗迹", "废墟", "白帝城"),
    "酒店餐馆": ("餐馆", "饭店", "酒店", "包厢"),
    "办公室": ("办公室", "会议室", "工位"),
    "实验室": ("实验室", "试剂", "仪器"),
    "白天": ("白天", "中午", "上午"),
    "夜晚": ("夜里", "深夜", "夜色", "夜晚"),
    "清晨": ("清晨", "早晨", "黎明"),
    "黄昏": ("黄昏", "傍晚", "日落"),
    "雨天": ("下雨", "暴雨", "雨幕", "雨声", "雨里", "雨中"),
    "雪天": ("下雪", "雪花", "积雪"),
    "紧张压迫": ("紧张", "压迫", "窒息", "冷汗", "发抖"),
    "温馨日常": ("晚饭", "早餐", "回家", "安静", "温暖"),
    "神秘诡异": ("诡异", "神秘", "黑暗", "阴影", "古怪"),
    "浪漫暧昧": ("脸红", "靠近", "心跳", "暧昧"),
    "悲伤低落": ("难过", "悲伤", "沮丧", "失落", "哭"),
    "热血激昂": ("燃烧", "怒吼", "热血", "激昂"),
    "荒诞幽默": ("好笑", "荒诞", "滑稽", "吐槽"),
    "孤独感": ("孤独", "一个人", "空荡荡", "寂寞"),
    "宿命感": ("命运", "注定", "宿命", "无法逃避"),
}

CONTENT_TAG_MAX_COUNT = 4
SEGMENT_MIN_BYTES = 100
SEGMENT_MAX_BYTES = 1000
SEGMENT_DELIMITERS = {",", "，", ".", "。", "!", "！", "\n"}
RESUME_CONTEXT_TAIL_CHARS = 600
RESUME_OVERLAP_MAX_CHARS = 600
RESUME_OVERLAP_MIN_CHARS = 20
CHINESE_NUMBER_CHARS = "零〇一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾"
HEADING_NUMBER_PATTERN = re.compile(rf"[0-9{CHINESE_NUMBER_CHARS}]")
HEADING_KEYWORD_PATTERN = re.compile(r"(第.{0,12}[章幕卷节回]|Chapter|Part|Episode|卷|章|幕|节|回)", re.IGNORECASE)
PARENTHESIZED_CHINESE_HEADING_PATTERN = re.compile(rf"^[（(][{CHINESE_NUMBER_CHARS}]+[）)]$")

SKIP_DOCUMENT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"本书版权",
        r"\bISBN\b",
        r"电子邮箱",
        r"www\.",
        r"目录",
        r"纸质版编目数据",
        r"数字传媒有限公司",
    ]
]


def _extract_document_title(text: str, path: Path) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            return stripped[3:].strip()
    return markdown_title(text, fallback=path.stem)


def _extract_title_index(path: Path) -> int:
    match = re.match(r"^(\d+)", path.stem)
    if match:
        return int(match.group(1))
    return abs(hash(path.stem)) % 1_000_000


@dataclass(slots=True)
class IngestResult:
    book_id: str
    inserted_documents: int
    batch_count: int


@dataclass(slots=True)
class BatchPromptSegment:
    segment_id: int
    source_span_index: int
    start_index: int
    end_index: int
    text: str
    boundary_candidate: ChapterBoundaryCandidate | None = None

    @property
    def byte_length(self) -> int:
        return len(self.text.encode("utf-8"))

    def to_prompt_input(self) -> SegmentationInputSegment:
        return SegmentationInputSegment(
            segment_id=self.segment_id,
            byte_length=self.byte_length,
            text=self.text,
            boundary_candidate=self.boundary_candidate.to_dict() if self.boundary_candidate is not None else None,
        )


class DocumentIngestService:
    def __init__(
        self,
        *,
        model_client: JsonModelClient,
        documents_repo: DocumentsRepo,
        progress_repo: ReadingProgressRepo,
        preferred_document_chars_min: int,
        preferred_document_chars_max: int,
        toc_markdown: str = "",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.model_client = model_client
        self.documents_repo = documents_repo
        self.progress_repo = progress_repo
        self.preferred_document_chars_min = preferred_document_chars_min
        self.preferred_document_chars_max = preferred_document_chars_max
        self.toc_markdown = toc_markdown.strip()
        self.progress_callback = progress_callback

        # Segmentation still uses lightweight tokenization for content-tag scoring.
        self.text_analyzer = ChineseTextAnalyzer()
        self.boundary_detector = ChapterBoundaryDetector()

    def _emit_progress(self, event: dict[str, Any]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(event)

    def _build_resume_context(self, content: str | None) -> str:
        if not content:
            return ""
        return content[-RESUME_CONTEXT_TAIL_CHARS:].strip()

    def _split_range_by_max_bytes(self, text: str, *, start: int, end: int) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        chunk_start = start
        chunk_bytes = 0
        for index in range(start, end):
            char_bytes = len(text[index].encode("utf-8"))
            if chunk_bytes + char_bytes > SEGMENT_MAX_BYTES and chunk_start < index:
                ranges.append((chunk_start, index))
                chunk_start = index
                chunk_bytes = 0
            chunk_bytes += char_bytes
        if chunk_start < end:
            ranges.append((chunk_start, end))
        return ranges

    def _merge_small_ranges(self, text: str, ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not ranges:
            return []
        merged: list[list[int]] = [[start, end] for start, end in ranges]
        index = 0
        while index < len(merged):
            start, end = merged[index]
            byte_length = len(text[start:end].encode("utf-8"))
            if byte_length >= SEGMENT_MIN_BYTES or len(merged) == 1:
                index += 1
                continue
            if index > 0:
                prev_start, _ = merged[index - 1]
                if len(text[prev_start:end].encode("utf-8")) <= SEGMENT_MAX_BYTES:
                    merged[index - 1][1] = end
                    merged.pop(index)
                    continue
            if index + 1 < len(merged):
                next_end = merged[index + 1][1]
                if len(text[start:next_end].encode("utf-8")) <= SEGMENT_MAX_BYTES:
                    merged[index + 1][0] = start
                    merged.pop(index)
                    continue
            index += 1
        return [(start, end) for start, end in merged]

    def _segment_span_text(
        self,
        text: str,
        *,
        boundary_candidates: Sequence[ChapterBoundaryCandidate] | None = None,
        span_start_offset: int = 0,
    ) -> list[tuple[int, int]]:
        if not text:
            return []
        heading_starts = [
            match.start()
            for match in re.finditer(r"(?m)^#{1,2}\s+\S.*$", text)
            if match.start() > 0
        ]
        inline_heading_starts = [
            start for start in self._iter_parenthesized_chinese_heading_starts(text) if start > 0
        ]
        detected_boundary_starts = {
            max(0, candidate.start_offset - span_start_offset)
            for candidate in (boundary_candidates or [])
            if candidate.start_offset > span_start_offset
        }
        section_starts = sorted({0, *heading_starts, *inline_heading_starts, *detected_boundary_starts, len(text)})
        segmented_ranges: list[tuple[int, int]] = []
        for section_start, section_end in zip(section_starts, section_starts[1:]):
            raw_ranges: list[tuple[int, int]] = []
            start = section_start
            for index in range(section_start, section_end):
                if text[index] in SEGMENT_DELIMITERS:
                    raw_ranges.append((start, index + 1))
                    start = index + 1
            if start < section_end:
                raw_ranges.append((start, section_end))
            bounded_ranges: list[tuple[int, int]] = []
            for range_start, range_end in raw_ranges:
                bounded_ranges.extend(self._split_range_by_max_bytes(text, start=range_start, end=range_end))
            segmented_ranges.extend(self._merge_small_ranges(text, bounded_ranges))
        return segmented_ranges

    def _build_batch_segments(self, batch: TextBatch) -> list[BatchPromptSegment]:
        segments: list[BatchPromptSegment] = []
        batch_cursor = 0
        next_segment_id = 1
        for span_index, span in enumerate(batch.spans):
            boundary_candidates = self.boundary_detector.detect(
                text=span.text,
                source_path=span.source_path,
                base_offset=span.start_offset,
                toc_markdown=self.toc_markdown,
            )
            boundary_by_local_start = {
                candidate.start_offset - span.start_offset: candidate for candidate in boundary_candidates
            }
            for start, end in self._segment_span_text(
                span.text,
                boundary_candidates=boundary_candidates,
                span_start_offset=span.start_offset,
            ):
                segment_text = span.text[start:end]
                if not segment_text:
                    continue
                segments.append(
                    BatchPromptSegment(
                        segment_id=next_segment_id,
                        source_span_index=span_index,
                        start_index=batch_cursor + start,
                        end_index=batch_cursor + end,
                        text=segment_text,
                        boundary_candidate=boundary_by_local_start.get(start),
                    )
                )
                next_segment_id += 1
            batch_cursor += len(span.text)
        return segments

    def _iter_parenthesized_chinese_heading_starts(self, text: str) -> list[int]:
        starts: list[int] = []
        for match in re.finditer(rf"[（(][{CHINESE_NUMBER_CHARS}]+[）)]", text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            if line_end == -1:
                line_end = len(text)
            line_prefix = text[line_start : match.start()].strip()
            line_suffix = text[match.end() : line_end].strip()
            if line_prefix or line_suffix:
                continue
            starts.append(match.start())
        return starts

    def _materialize_segment_documents(
        self,
        *,
        batch_segments: list[BatchPromptSegment],
        doc_items: Sequence[object],
    ) -> list[dict[str, Any]]:
        if not batch_segments:
            return []
        segments_by_id = {segment.segment_id: segment for segment in batch_segments}
        all_segment_ids = set(segments_by_id)
        consumed_segment_ids: set[int] = set()
        materialized: list[dict[str, Any]] = []
        for raw in doc_items:
            if not isinstance(raw, dict):
                return []
            raw_segment_ids = raw.get("segment_ids")
            if not isinstance(raw_segment_ids, list):
                return []
            segment_ids: list[int] = []
            previous_segment_id: int | None = None
            for item in raw_segment_ids:
                try:
                    segment_id = int(item)
                except (TypeError, ValueError):
                    return []
                segment = segments_by_id.get(segment_id)
                if segment is None or segment_id in consumed_segment_ids:
                    return []
                if previous_segment_id is not None and segment_id != previous_segment_id + 1:
                    return []
                segment_ids.append(segment_id)
                previous_segment_id = segment_id
            if not segment_ids:
                return []
            ordered_segments = [segments_by_id[segment_id] for segment_id in segment_ids]
            consumed_segment_ids.update(segment_ids)
            copied = dict(raw)
            copied["segment_ids"] = segment_ids
            copied["content"] = "".join(segment.text for segment in ordered_segments)
            copied["content_chars"] = len(str(copied["content"]))
            copied["_batch_start_index"] = ordered_segments[0].start_index
            copied["_batch_end_index"] = ordered_segments[-1].end_index
            self._apply_boundary_metadata(copied, ordered_segments[0])
            materialized.append(copied)
        if consumed_segment_ids != all_segment_ids:
            return []
        return materialized

    def _apply_boundary_metadata(self, raw: dict[str, Any], first_segment: BatchPromptSegment) -> None:
        candidate = first_segment.boundary_candidate
        if candidate is None:
            raw.setdefault("boundary_candidate_id", "")
            raw.setdefault("raw_heading", "")
            raw.setdefault("normalized_heading", "")
            raw.setdefault("boundary_confidence", 0.0)
            raw.setdefault("boundary_status", "uncertain")
            return
        raw["boundary_candidate_id"] = candidate.candidate_id
        raw["raw_heading"] = candidate.raw_heading
        raw["normalized_heading"] = candidate.normalized_heading
        raw["boundary_confidence"] = candidate.confidence
        raw["boundary_status"] = "confirmed" if candidate.is_high_confidence else "uncertain"

    def _split_materialized_documents_by_segment_titles(
        self,
        *,
        batch_segments: list[BatchPromptSegment],
        doc_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        segments_by_id = {segment.segment_id: segment for segment in batch_segments}
        split_items: list[dict[str, Any]] = []
        for raw in doc_items:
            raw_segment_ids = raw.get("segment_ids")
            if not isinstance(raw_segment_ids, list):
                split_items.append(raw)
                continue
            segment_ids: list[int] = []
            for item in raw_segment_ids:
                try:
                    segment_id = int(item)
                except (TypeError, ValueError):
                    continue
                if segment_id in segments_by_id:
                    segment_ids.append(segment_id)
            if not segment_ids:
                split_items.append(raw)
                continue
            groups: list[list[int]] = []
            current_group: list[int] = []
            for segment_id in segment_ids:
                segment = segments_by_id[segment_id]
                has_high_boundary = bool(segment.boundary_candidate and segment.boundary_candidate.is_high_confidence)
                if current_group and (has_high_boundary or self._extract_explicit_title(segment.text)):
                    groups.append(current_group)
                    current_group = []
                current_group.append(segment_id)
            if current_group:
                groups.append(current_group)
            if len(groups) <= 1:
                split_items.append(raw)
                continue
            try:
                base_title_index = int(raw.get("document_title_index", 0))
            except (TypeError, ValueError):
                base_title_index = 0
            for group_offset, group in enumerate(groups):
                group_segments = [segments_by_id[segment_id] for segment_id in group]
                copied = dict(raw)
                copied["segment_ids"] = group
                copied["content"] = "".join(segment.text for segment in group_segments)
                copied["content_chars"] = len(str(copied["content"]))
                copied["_batch_start_index"] = group_segments[0].start_index
                copied["_batch_end_index"] = group_segments[-1].end_index
                copied["document_title_index"] = base_title_index + group_offset
                copied["inferred_chapter_no"] = None
                self._apply_boundary_metadata(copied, group_segments[0])
                explicit_title = self._extract_explicit_title(str(copied["content"]))
                boundary_candidate = group_segments[0].boundary_candidate
                if boundary_candidate is not None and boundary_candidate.is_high_confidence:
                    copied["document_title"] = boundary_candidate.normalized_heading
                elif explicit_title:
                    copied["document_title"] = explicit_title
                reason = str(copied.get("segmentation_reason") or "").strip()
                copied["segmentation_reason"] = (
                    f"{reason}; deterministic_explicit_heading_split"
                    if reason
                    else "deterministic_explicit_heading_split"
                )
                split_items.append(copied)
        return split_items

    def _find_batch_split_index(self, text: str) -> int | None:
        if len(text) < 2:
            return None
        target = len(text) // 2
        window_start = max(0, target - 400)
        window_end = min(len(text), target + 400)
        for marker in ("。\r\n", "。\n", "。", "\n"):
            right = text.find(marker, target, window_end)
            if right != -1:
                split_index = right + len(marker)
                if 0 < split_index < len(text):
                    return split_index
            left = text.rfind(marker, window_start, target)
            if left != -1:
                split_index = left + len(marker)
                if 0 < split_index < len(text):
                    return split_index
        return target if 0 < target < len(text) else None

    def _split_batch_for_retry(self, batch: TextBatch) -> tuple[TextBatch, TextBatch] | None:
        split_index = self._find_batch_split_index(batch.content)
        if split_index is None:
            return None
        left_spans = []
        right_spans = []
        consumed = 0
        for span in batch.spans:
            span_len = len(span.text)
            span_start = consumed
            span_end = consumed + span_len
            consumed = span_end
            if span_end <= split_index:
                left_spans.append(span)
                continue
            if span_start >= split_index:
                right_spans.append(span)
                continue
            cut = split_index - span_start
            left_text = span.text[:cut]
            right_text = span.text[cut:]
            if left_text:
                left_spans.append(
                    type(span)(
                        source_path=span.source_path,
                        source_file_name=span.source_file_name,
                        start_offset=span.start_offset,
                        end_offset=span.start_offset + len(left_text),
                        text=left_text,
                    )
                )
            if right_text:
                right_spans.append(
                    type(span)(
                        source_path=span.source_path,
                        source_file_name=span.source_file_name,
                        start_offset=span.start_offset + len(left_text),
                        end_offset=span.end_offset,
                        text=right_text,
                    )
                )
        if not left_spans or not right_spans:
            return None
        left_batch = TextBatch(
            batch_no=batch.batch_no,
            chars=sum(len(span.text) for span in left_spans),
            spans=left_spans,
        )
        right_batch = TextBatch(
            batch_no=batch.batch_no + 1,
            chars=sum(len(span.text) for span in right_spans),
            spans=right_spans,
        )
        return left_batch, right_batch

    def _trim_resumed_overlap(self, *, previous_content: str, current_content: str) -> str:
        if not previous_content or not current_content:
            return current_content
        previous_tail = previous_content[-RESUME_OVERLAP_MAX_CHARS:]
        max_overlap = min(len(previous_tail), len(current_content), RESUME_OVERLAP_MAX_CHARS)
        for overlap_size in range(max_overlap, RESUME_OVERLAP_MIN_CHARS - 1, -1):
            if previous_tail.endswith(current_content[:overlap_size]):
                trimmed = current_content[overlap_size:].lstrip()
                return trimmed or current_content
        return current_content

    def _find_document_in_batch(self, *, batch: TextBatch, content: str, start_at: int) -> tuple[int, int] | None:
        hay = batch.content
        if not content:
            return None
        idx = hay.find(content, start_at)
        if idx == -1:
            return None
        return idx, idx + len(content)

    def _find_document_span_in_batch(self, *, batch: TextBatch, content: str, cursor: int) -> tuple[int, int]:
        # Best-effort mapping from model-returned content back to the raw batch text.
        # The model may normalize whitespace, so fall back to an anchor search and then a
        # length-based estimate to keep offsets monotonic.
        hay = batch.content
        cursor = max(0, min(cursor, len(hay)))
        exact = self._find_document_in_batch(batch=batch, content=content, start_at=cursor)
        if exact is not None:
            return exact
        compact = "".join(ch for ch in content.strip() if ch not in "\r\n\t")
        anchor = compact[:32]
        if len(anchor) >= 8:
            start_i = hay.find(anchor, cursor)
            if start_i != -1:
                end_i = min(len(hay), start_i + len(content))
                return start_i, max(start_i, end_i)
        start_i = cursor
        end_i = min(len(hay), start_i + len(content))
        return start_i, max(start_i, end_i)

    def _batch_index_to_source_offset(self, *, batch: TextBatch, batch_index: int) -> tuple[int, int, str]:
        remaining = max(0, batch_index)
        for span_index, span in enumerate(batch.spans):
            span_len = len(span.text)
            if remaining <= span_len:
                return span_index, span.start_offset + remaining, span.source_file_name
            remaining -= span_len
        last = batch.spans[-1]
        return len(batch.spans) - 1, last.end_offset, last.source_file_name

    def _extract_explicit_title(self, content: str) -> str | None:
        # Try to avoid chapter "flapping": only treat explicit headings as chapter boundaries.
        for line in content.splitlines()[:5]:
            stripped = line.strip()
            if stripped.startswith(("## ", "# ")):
                return stripped.lstrip("#").strip()
            if self._looks_like_short_numbered_heading(stripped):
                return stripped
        first_line = content.splitlines()[0].strip() if content.splitlines() else ""
        if first_line.startswith("第") and any(x in first_line for x in ("章", "幕", "卷")) and len(first_line) <= 32:
            return first_line
        return None

    def _looks_like_short_numbered_heading(self, line: str) -> bool:
        if not line or len(line) > 24:
            return False
        if any(mark in line for mark in ("。", "，", "！", "？", "；", "：", "“", "”")):
            return False
        if not HEADING_NUMBER_PATTERN.search(line):
            return False
        if HEADING_KEYWORD_PATTERN.search(line):
            return True
        compact = re.sub(r"\s+", "", line)
        if PARENTHESIZED_CHINESE_HEADING_PATTERN.fullmatch(compact):
            return True
        if re.fullmatch(rf"[0-9{CHINESE_NUMBER_CHARS}]+", compact):
            return True
        return bool(re.match(rf"^[0-9{CHINESE_NUMBER_CHARS}]+[\s._\-、]+.+$", line))

    def _clean_content_tags(self, items: Sequence[object]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = CONTENT_TAG_ALIASES.get(str(item).strip(), str(item).strip())
            if normalized not in ALLOWED_CONTENT_TAGS:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(normalized)
        return cleaned[:CONTENT_TAG_MAX_COUNT]

    def _score_content_tags(self, *, title: str, content: str) -> dict[str, float]:
        title_text = title.strip()
        body_text = content[:8000]
        combined_text = f"{title_text}\n{body_text}"
        token_counter = self.text_analyzer.token_counter(combined_text)
        scores: dict[str, float] = {}

        def add_score(tag: str, value: float) -> None:
            if tag in ALLOWED_CONTENT_TAGS and value > 0:
                scores[tag] = scores.get(tag, 0.0) + value

        if title_text.startswith(("序章", "开篇", "楔子")):
            add_score("开场铺垫", 4.0)
        for tag, keywords in CONTENT_TAG_KEYWORDS.items():
            tag_score = 0.0
            for keyword in keywords:
                normalized_keyword = keyword.strip()
                if len(normalized_keyword) < 2:
                    continue
                title_hits = title_text.count(normalized_keyword)
                body_hits = body_text.count(normalized_keyword)
                token_hits = token_counter.get(normalized_keyword, 0)
                if title_hits:
                    tag_score += title_hits * 4.0
                if body_hits:
                    tag_score += body_hits * (2.5 if len(normalized_keyword) >= 4 else 1.8)
                if token_hits:
                    tag_score += min(token_hits, 3) * (1.8 if len(normalized_keyword) >= 4 else 1.2)
            if tag_score:
                add_score(tag, tag_score)
        if body_text.count("“") >= 2 and body_text.count("”") >= 2:
            add_score("人物对话", 3.5)
        if any(word in combined_text for word in ("学院", "学校", "高中", "大学")):
            add_score("校园", 4.5)
        if any(word in combined_text for word in ("高考", "课堂", "作业", "成绩")):
            add_score("学习考试", 4.0)
        if any(word in combined_text for word in ("QQ", "短信", "电话", "邮件")):
            add_score("通信联络", 3.5)
        if any(word in combined_text for word in ("录取", "通知书", "面试")):
            add_score("入学面试", 4.0)
        if any(word in combined_text for word in ("古城", "遗迹", "废墟")):
            add_score("遗迹古城", 5.0)
        if any(word in combined_text for word in ("叔叔", "婶婶", "客厅", "卧室", "厨房", "家里")):
            add_score("家庭住宅", 3.5)
        if any(word in combined_text for word in ("孤独", "一个人", "寂寞", "被抛弃")):
            add_score("孤独感", 3.2)
        if any(word in combined_text for word in ("命运", "弃族", "战旗", "吞噬世界")):
            add_score("宿命感", 4.2)
        if any(word in combined_text for word in ("黑暗", "火光", "地狱", "献祭", "无法解释")):
            add_score("神秘诡异", 3.8)
        if any(word in combined_text for word in ("他想", "她想", "心里", "觉得", "想起")):
            add_score("心理活动", 2.8)
        if any(word in combined_text for word in ("阳光", "走廊", "楼道", "窗户", "树叶")):
            add_score("环境描写", 2.2)
        if any(word in combined_text for word in ("火焰", "奔跑", "箭", "哭号", "灼烧")):
            add_score("危机爆发", 3.2)
        return scores

    def _select_content_tags(self, *, title: str, content: str, preferred_tags: Sequence[str] | None = None) -> list[str]:
        scores = self._score_content_tags(title=title, content=content)
        for tag in self._clean_content_tags(preferred_tags or []):
            scores[tag] = max(scores.get(tag, 0.0), 1.0)
        if not scores:
            return []
        ordered = sorted(
            scores.items(),
            key=lambda item: (-item[1], -CONTENT_TAG_GROUP_PRIORITY.get(CONTENT_TAG_TO_GROUP.get(item[0], ""), 0), item[0]),
        )
        selected: list[str] = []
        per_group_count: dict[str, int] = {}

        for tag, _ in ordered:
            group_name = CONTENT_TAG_TO_GROUP.get(tag)
            if not group_name:
                continue
            if group_name in per_group_count:
                continue
            selected.append(tag)
            per_group_count[group_name] = 1
            if len(selected) >= min(3, CONTENT_TAG_MAX_COUNT):
                break

        for tag, _ in ordered:
            if tag in selected:
                continue
            group_name = CONTENT_TAG_TO_GROUP.get(tag)
            if not group_name:
                continue
            if per_group_count.get(group_name, 0) >= 2:
                continue
            selected.append(tag)
            per_group_count[group_name] = per_group_count.get(group_name, 0) + 1
            if len(selected) >= CONTENT_TAG_MAX_COUNT:
                break
        return selected[:CONTENT_TAG_MAX_COUNT]

    def _infer_content_tags(self, *, title: str, content: str) -> list[str]:
        return self._select_content_tags(title=title, content=content)

    def _should_skip_document(self, *, title: str, content: str) -> bool:
        normalized_title = title.strip()
        if normalized_title in {"版权信息", "纸质版编目数据", "目录"}:
            return True
        compact = re.sub(r"\s+", " ", content).strip()
        if content.lstrip().startswith("# ") and "- Source:" in content and "- Pages:" in content:
            return True
        if not compact:
            return True
        if len(compact) < 64 and not any(mark in compact for mark in ("。", "！", "？", "“", "”")):
            return True
        for pattern in SKIP_DOCUMENT_PATTERNS:
            if pattern.search(compact):
                return True
        return False

    def _postprocess_documents(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for raw in docs:
            content = str(raw.get("content", "")).strip()
            if not content:
                continue
            title = str(raw.get("document_title", "")).strip() or "Untitled"
            if self._should_skip_document(title=title, content=content):
                continue
            raw_tags = raw.get("content_tags", [])
            candidate_tags = raw_tags if isinstance(raw_tags, list) else []
            content_tags = self._select_content_tags(
                title=title,
                content=content,
                preferred_tags=self._clean_content_tags(candidate_tags),
            )
            doc = dict(raw)
            doc["document_title"] = title
            doc["content"] = content
            doc["content_chars"] = len(content)
            doc["character_keywords"] = []
            doc["content_tags"] = content_tags
            doc["_batch_start_index"] = int(raw.get("_batch_start_index", 0))
            doc["_batch_end_index"] = int(raw.get("_batch_end_index", raw.get("_batch_start_index", 0)))
            normalized.append(doc)
        if not normalized:
            return normalized
        merged: list[dict[str, Any]] = [normalized[0]]
        for doc in normalized[1:]:
            prev = merged[-1]
            if (
                len(doc["content"]) < 128
                and int(doc.get("document_title_index", -1)) == int(prev.get("document_title_index", -2))
            ):
                joiner = "" if prev["content"].endswith("\n") else "\n"
                prev["content"] = f"{prev['content']}{joiner}{doc['content']}"
                prev["content_chars"] = len(prev["content"])
                prev["character_keywords"] = []
                prev["_batch_end_index"] = int(doc.get("_batch_end_index", prev["_batch_end_index"]))
                prev["content_tags"] = self._select_content_tags(
                    title=str(prev.get("document_title", "")),
                    content=prev["content"],
                    preferred_tags=[str(x) for x in prev.get("content_tags", [])] + [str(x) for x in doc.get("content_tags", [])],
                )
                continue
            merged.append(doc)
        for index, doc in enumerate(merged, start=1):
            doc["document_local_id"] = index
        return merged

    def _build_fallback_documents_from_segments(
        self,
        batch: TextBatch,
        batch_segments: list[BatchPromptSegment],
    ) -> list[SegmentedDocumentOutput]:
        documents: list[SegmentedDocumentOutput] = []
        current_segments: list[BatchPromptSegment] = []
        current_title: str | None = None

        def flush() -> None:
            nonlocal current_segments, current_title
            if not current_segments:
                return
            content = "".join(segment.text for segment in current_segments)
            first_segment = current_segments[0]
            path = Path(batch.spans[first_segment.source_span_index].source_path)
            title = current_title or _extract_document_title(content, path)
            content_tags = self._infer_content_tags(title=title, content=content)
            documents.append(
                SegmentedDocumentOutput(
                    document_local_id=len(documents) + 1,
                    document_title=title,
                    document_title_index=len(documents) + 1,
                    inferred_chapter_no=len(documents) + 1,
                    segment_ids=[segment.segment_id for segment in current_segments],
                    character_keywords=[],
                    content_tags=content_tags,
                    segmentation_reason="deterministic_safe_fallback",
                    continuity_hint="模型未返回有效 document，按显式标题与本地片段保底切分",
                )
            )
            current_segments = []
            current_title = None

        for segment in batch_segments:
            explicit_title = self._extract_explicit_title(segment.text)
            if explicit_title and current_segments:
                flush()
            if explicit_title:
                current_title = explicit_title
            current_segments.append(segment)
        flush()
        return documents

    def _fallback_segmentation(self, batch: TextBatch, batch_segments: list[BatchPromptSegment]) -> dict[str, object]:
        documents = self._build_fallback_documents_from_segments(batch, batch_segments)
        output = SegmentationPromptOutput(
            document_title_index_start=documents[0].document_title_index if documents else None,
            documents=documents,
            batch_summary=SegmentationBatchSummary(
                chapter_count=len({doc.document_title_index for doc in documents}),
                document_count=len(documents),
                new_characters=[],
            ),
        )
        return output.to_dict()

    def _safe_fallback_segmentation(self, batch: TextBatch, batch_segments: list[BatchPromptSegment]) -> dict[str, object]:
        documents = self._build_fallback_documents_from_segments(batch, batch_segments)
        output = SegmentationPromptOutput(
            document_title_index_start=documents[0].document_title_index if documents else None,
            documents=documents,
            batch_summary=SegmentationBatchSummary(
                chapter_count=len({doc.document_title_index for doc in documents}),
                document_count=len(documents),
                new_characters=[],
            ),
        )
        return output.to_dict()

    def ingest_batches(
        self,
        *,
        conn,
        repo_root: Path,
        book_id: str,
        batches: list[TextBatch],
        run_id: str,
        reset_book: bool = True,
        initial_title_index: int = 1,
        continued_title: str | None = None,
        continued_title_index: int | None = None,
        continued_document_content: str | None = None,
    ) -> IngestResult:
        if reset_book:
            self.documents_repo.clear_book(conn, book_id=book_id)
        inserted = 0
        processed_batches = 0
        next_title_index = initial_title_index
        current_title = continued_title.strip() if continued_title else None
        current_title_index = continued_title_index
        pending_resume_context = self._build_resume_context(continued_document_content)
        pending_overlap_source = continued_document_content or ""
        pending_batches = deque(batches)
        while pending_batches:
            batch = pending_batches.popleft()
            batch_segments = self._build_batch_segments(batch)
            file_context = "\n".join(
                f"- {span.source_path}:{span.start_offset}-{span.end_offset}" for span in batch.spans
            )
            system_prompt, user_prompt = build_segmentation_prompt(
                batch_segments=[segment.to_prompt_input() for segment in batch_segments],
                file_context=file_context,
                chunk_min=min(len(batch.content), self.preferred_document_chars_min),
                chunk_max=max(len(batch.content), self.preferred_document_chars_max),
                doc_min=self.preferred_document_chars_min,
                doc_max=self.preferred_document_chars_max,
                toc_context=self.toc_markdown[:6000],
                resume_document_title=current_title or "",
                resume_context=pending_resume_context,
            )
            prompt_started_at = time.perf_counter()
            self._emit_progress(
                {
                    "stage": "segmentation",
                    "agent": "segmentation",
                    "event": "prompt_start",
                    "batch_no": batch.batch_no,
                    "batch_chars": batch.chars,
                    "segment_count": len(batch_segments),
                    "span_count": len(batch.spans),
                }
            )
            try:
                payload, raw_text = self.model_client.generate_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    fallback_factory=lambda batch=batch, batch_segments=batch_segments: self._fallback_segmentation(
                        batch, batch_segments
                    ),
                    use_fallback_on_error=self.model_client.settings.dry_run,
                )
                self._emit_progress(
                    {
                        "stage": "segmentation",
                        "agent": "segmentation",
                        "event": "prompt_end",
                        "batch_no": batch.batch_no,
                        "batch_chars": batch.chars,
                        "segment_count": len(batch_segments),
                        "duration_seconds": round(time.perf_counter() - prompt_started_at, 3),
                    }
                )
            except InvalidJSONResponseError:
                self._emit_progress(
                    {
                        "stage": "segmentation",
                        "agent": "segmentation",
                        "event": "prompt_invalid_json",
                        "batch_no": batch.batch_no,
                        "batch_chars": batch.chars,
                        "segment_count": len(batch_segments),
                        "duration_seconds": round(time.perf_counter() - prompt_started_at, 3),
                    }
                )
                split_batches = self._split_batch_for_retry(batch)
                if split_batches is None:
                    raise
                left_batch, right_batch = split_batches
                pending_batches.appendleft(right_batch)
                pending_batches.appendleft(left_batch)
                continue
            if isinstance(payload, list) and payload and isinstance(payload[0], dict) and "documents" in payload[0]:
                payload = payload[0]
            if not isinstance(payload, dict):
                if self.model_client.settings.dry_run:
                    payload = self._fallback_segmentation(batch, batch_segments)
                else:
                    preview = raw_text[:1200]
                    raise RuntimeError(
                        f"Segmentation model returned a non-dict JSON payload: {type(payload).__name__}\n"
                        f"Raw output preview:\n{preview}"
                    )
            doc_items = payload.get("documents") or []
            if not isinstance(doc_items, list):
                if self.model_client.settings.dry_run:
                    doc_items = []
                else:
                    raise RuntimeError("Segmentation model returned invalid documents field")
            if not doc_items and not self.model_client.settings.dry_run:
                raise RuntimeError("Segmentation model returned no documents")
            raw_doc_items = self._materialize_segment_documents(
                batch_segments=batch_segments,
                doc_items=doc_items,
            )
            raw_doc_items = self._split_materialized_documents_by_segment_titles(
                batch_segments=batch_segments,
                doc_items=raw_doc_items,
            )
            if not raw_doc_items and not self.model_client.settings.dry_run:
                raise RuntimeError("Segmentation model returned no materializable documents")
            if pending_overlap_source and raw_doc_items:
                first_content = str(raw_doc_items[0].get("content", ""))
                trimmed_content = self._trim_resumed_overlap(
                    previous_content=pending_overlap_source,
                    current_content=first_content,
                )
                raw_doc_items[0]["content"] = trimmed_content
                raw_doc_items[0]["content_chars"] = len(trimmed_content)
            processed_doc_items = self._postprocess_documents(raw_doc_items)
            if not processed_doc_items:
                continue
            pending_resume_context = ""
            pending_overlap_source = ""

            # Resolve title continuity in source order so continuation chunks after
            # a confirmed heading inherit the newly opened chapter immediately.
            for raw in processed_doc_items:
                content = str(raw.get("content", "")).lstrip()
                explicit_title = self._extract_explicit_title(content)
                if raw.get("boundary_status") == "confirmed" and str(raw.get("normalized_heading") or "").strip():
                    raw["document_title"] = str(raw.get("normalized_heading")).strip()
                elif explicit_title:
                    raw["document_title"] = explicit_title
                elif current_title:
                    raw["document_title"] = current_title

                title = str(raw.get("document_title", "")).strip() or "Untitled"
                if current_title is not None and title == current_title and current_title_index is not None:
                    raw["document_title_index"] = current_title_index
                else:
                    raw["document_title_index"] = next_title_index
                    current_title = title
                    current_title_index = next_title_index
                    next_title_index += 1

            # Map each document to precise source offsets when possible.
            for raw in processed_doc_items:
                content = str(raw.get("content", ""))
                start_i = int(raw.get("_batch_start_index", 0))
                end_i = int(raw.get("_batch_end_index", start_i))
                start_span_index, start_offset, _ = self._batch_index_to_source_offset(batch=batch, batch_index=start_i)
                _, end_offset, _ = self._batch_index_to_source_offset(batch=batch, batch_index=end_i)
                span_start = batch.spans[start_span_index]
                doc_source_start_offset = start_offset
                doc_source_end_offset = end_offset
                now = _utc_now()
                inserted += 1
                source_path_rel = Path(span_start.source_path)
                try:
                    source_path_rel = source_path_rel.relative_to(repo_root)
                except ValueError:
                    pass
                self.documents_repo.insert_document(
                    conn,
                    {
                        "path": source_path_rel.as_posix(),
                        "scope": source_path_rel.parts[0] if source_path_rel.parts else "",
                        "title": raw.get("document_title"),
                        "content": content,
                        "mtime": 0,
                        "size": len(content.encode("utf-8")),
                        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        "book_id": book_id,
                        "source_path": source_path_rel.as_posix(),
                        "source_file_name": span_start.source_file_name,
                        "source_start_offset": int(doc_source_start_offset),
                        "source_end_offset": int(doc_source_end_offset),
                        "source_batch_no": batch.batch_no,
                        "document_title": str(raw.get("document_title", source_path_rel.stem)),
                        "document_title_index": int(raw.get("document_title_index", _extract_title_index(Path(span_start.source_file_name)))),
                        "inferred_chapter_no": raw.get("inferred_chapter_no"),
                        "content_chars": len(content),
                        "character_keywords": [str(x) for x in raw.get("character_keywords", [])],
                        "content_tags": [str(x) for x in raw.get("content_tags", [])],
                        "segmentation_notes": raw.get("segmentation_reason"),
                        "boundary_candidate_id": str(raw.get("boundary_candidate_id") or ""),
                        "raw_heading": str(raw.get("raw_heading") or ""),
                        "normalized_heading": str(raw.get("normalized_heading") or ""),
                        "boundary_confidence": float(raw.get("boundary_confidence") or 0.0),
                        "boundary_status": str(raw.get("boundary_status") or "uncertain"),
                        "ingestion_run_id": run_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            last_span = batch.spans[-1]
            self.progress_repo.upsert(
                conn,
                {
                    "book_id": book_id,
                    "agent_stage": DEFAULT_SEGMENTATION_STAGE,
                    "current_doc_id": None,
                    "current_document_title_index": None,
                    "current_source_path": last_span.source_path,
                    "current_source_offset": last_span.end_offset,
                    "last_completed_doc_id": None,
                    "last_completed_title_index": None,
                    "last_completed_chapter_id": None,
                    "status": {"state": "completed_batch", "last_run_id": run_id, "last_batch_no": batch.batch_no},
                    "checkpoint_token": f"{last_span.source_path}:{last_span.end_offset}",
                    "updated_at": _utc_now(),
                },
            )
            processed_batches += 1
        return IngestResult(book_id=book_id, inserted_documents=inserted, batch_count=processed_batches)
