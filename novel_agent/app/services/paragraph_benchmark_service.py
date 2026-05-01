from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from pathlib import Path

from ...schemas import RunConfig
from ..schemas.paragraph_benchmark_schema import (
    ParagraphBenchmarkIssue,
    ParagraphBenchmarkReviewerReport,
    ParagraphBenchmarkRunResult,
    ParagraphBenchmarkSample,
)
from .continuation_generation_service import ContinuationGenerationService


SEGMENT_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？!?；;])\s*")
TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")
CHINESE_NAME_CANDIDATE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,4}")

STOPWORD_TOKENS = {
    "一个",
    "一下",
    "一声",
    "不是",
    "不能",
    "他们",
    "你们",
    "我们",
    "这个",
    "那个",
    "自己",
    "没有",
    "已经",
    "还是",
    "只是",
    "然后",
    "因为",
    "所以",
    "但是",
    "如果",
    "时候",
    "现在",
    "之前",
    "之后",
}


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _normalize_string_list(items: object) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        raw_items = re.split(r"[,，、\s]+", items)
    elif isinstance(items, list):
        raw_items = [str(item) for item in items]
    else:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _safe_excerpt(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


class ParagraphSegmenter:
    """Splits a source novel into benchmark-sized paragraph units."""

    def split(self, text: str) -> list[str]:
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        segments = self._split_by_blank_lines(normalized)
        if len(segments) >= 2:
            return segments
        segments = self._split_by_nonempty_lines(normalized)
        if len(segments) >= 2:
            return segments
        return self._split_by_sentences(normalized)

    def _split_by_blank_lines(self, text: str) -> list[str]:
        return self._clean_segments(SEGMENT_SPLIT_PATTERN.split(text))

    def _split_by_nonempty_lines(self, text: str) -> list[str]:
        return self._clean_segments(text.splitlines())

    def _split_by_sentences(self, text: str) -> list[str]:
        return self._clean_segments(SENTENCE_SPLIT_PATTERN.split(text))

    def _clean_segments(self, values: list[str]) -> list[str]:
        return [segment for segment in (_normalize_text(value) for value in values) if segment]


class ParagraphBenchmarkReviewer:
    """A lightweight reviewer for 60-point regression checks, not a literary judge."""

    def review(
        self,
        *,
        sample: ParagraphBenchmarkSample,
        generated_text: str,
    ) -> ParagraphBenchmarkReviewerReport:
        generated = _normalize_text(generated_text)
        issues = self._build_issues(sample=sample, generated_text=generated)
        metrics: dict[str, float | None] = {
            "non_empty": 1.0 if generated else 0.0,
            "length_reasonable": self._score_length_reasonable(sample=sample, generated_text=generated),
            "recent_window_coherence": self._keyword_overlap_score(sample.recent_window_text, generated),
            "reference_direction_alignment": self._keyword_overlap_score(sample.reference_truth, generated),
            "outline_alignment": (
                self._keyword_overlap_score(sample.outline_text, generated) if sample.outline_text else None
            ),
            "character_coverage": self._score_character_coverage(
                character_names=sample.character_names,
                generated_text=generated,
            ),
        }
        score = self._weighted_score(metrics)
        if any(issue.severity == "fatal" for issue in issues):
            score = 0.0
            decision = "fail"
        elif score >= 0.6:
            decision = "pass"
        elif score >= 0.45:
            decision = "borderline"
        else:
            decision = "fail"
        return ParagraphBenchmarkReviewerReport(
            decision=decision,
            score=score,
            summary=self._build_summary(decision=decision, score=score, issues=issues),
            issues=issues,
            metrics=metrics,
            generated_chars=len(generated),
            reference_truth_chars=len(sample.reference_truth),
        )

    def _build_issues(
        self,
        *,
        sample: ParagraphBenchmarkSample,
        generated_text: str,
    ) -> list[ParagraphBenchmarkIssue]:
        issues: list[ParagraphBenchmarkIssue] = []
        if not generated_text:
            return [
                ParagraphBenchmarkIssue(
                    type="empty_output",
                    severity="fatal",
                    message="生成结果为空，无法判断续写能力。",
                )
            ]
        if len(generated_text) < 40:
            issues.append(
                ParagraphBenchmarkIssue(
                    type="too_short",
                    severity="warning",
                    message="生成文本过短，只能作为非常粗略的回归信号。",
                    evidence=f"{len(generated_text)} chars",
                )
            )
        if self._keyword_overlap_score(sample.recent_window_text, generated_text) < 0.08:
            issues.append(
                ParagraphBenchmarkIssue(
                    type="weak_recent_continuity",
                    severity="warning",
                    message="生成文本与最近剧情窗口的关键词承接较弱，需要人工快速扫一眼。",
                )
            )
        if self._keyword_overlap_score(sample.reference_truth, generated_text) < 0.06:
            issues.append(
                ParagraphBenchmarkIssue(
                    type="large_reference_deviation",
                    severity="warning",
                    message="生成文本和原文下一段的剧情方向重合较低；这不一定是错误，但说明偏离较明显。",
                )
            )
        unknown_names = self._unknown_generated_names(
            known_text="\n".join([sample.prefix_text, sample.reference_truth, sample.outline_text]),
            generated_text=generated_text,
            explicit_names=sample.character_names,
        )
        if unknown_names:
            issues.append(
                ParagraphBenchmarkIssue(
                    type="possible_new_character_introduction",
                    severity="warning",
                    message="生成文本疑似引入了前文未出现的人名，可能需要检查是否弄混角色。",
                    evidence="、".join(unknown_names[:5]),
                )
            )
        return issues

    def _score_length_reasonable(
        self,
        *,
        sample: ParagraphBenchmarkSample,
        generated_text: str,
    ) -> float:
        if not generated_text:
            return 0.0
        target = max(80, sample.target_length_chars)
        lower = max(40, int(target * 0.35))
        upper = max(lower + 1, int(target * 1.8))
        length = len(generated_text)
        if lower <= length <= upper:
            return 1.0
        if length < lower:
            return _clamp_score(length / lower)
        return _clamp_score(upper / length)

    def _score_character_coverage(self, *, character_names: list[str], generated_text: str) -> float | None:
        if not character_names:
            return None
        matched = sum(1 for name in character_names if name and name in generated_text)
        return _clamp_score(matched / max(1, len(character_names)))

    def _keyword_overlap_score(self, left_text: str, right_text: str) -> float:
        left_tokens = self._token_counter(left_text)
        right_tokens = self._token_counter(right_text)
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = sum(min(left_tokens[token], right_tokens[token]) for token in left_tokens if token in right_tokens)
        denominator = min(sum(left_tokens.values()), 24)
        return _clamp_score(overlap / max(1, denominator))

    def _token_counter(self, text: str) -> Counter[str]:
        tokens: list[str] = []
        for token in TOKEN_PATTERN.findall(text):
            normalized = token.strip().lower()
            if len(normalized) <= 1 or normalized in STOPWORD_TOKENS:
                continue
            tokens.append(normalized)
            if re.fullmatch(r"[\u4e00-\u9fff]+", normalized):
                for index in range(len(normalized) - 1):
                    bigram = normalized[index : index + 2]
                    if bigram not in STOPWORD_TOKENS:
                        tokens.append(bigram)
        return Counter(tokens)

    def _unknown_generated_names(
        self,
        *,
        known_text: str,
        generated_text: str,
        explicit_names: list[str],
    ) -> list[str]:
        if explicit_names:
            known_names = set(explicit_names)
        else:
            known_names = self._infer_name_candidates(known_text)
        generated_names = self._infer_name_candidates(generated_text)
        unknown = [
            name
            for name in generated_names
            if name not in known_names and name not in STOPWORD_TOKENS
        ]
        return sorted(unknown)

    def _infer_name_candidates(self, text: str) -> set[str]:
        candidates = set()
        for match in CHINESE_NAME_CANDIDATE_PATTERN.findall(text):
            if match in STOPWORD_TOKENS:
                continue
            if any(suffix in match for suffix in ("先生", "小姐", "阿姨", "老师", "姐姐", "哥哥")):
                candidates.add(match)
        return candidates

    def _weighted_score(self, metrics: dict[str, float | None]) -> float:
        weights = {
            "non_empty": 0.20,
            "length_reasonable": 0.15,
            "recent_window_coherence": 0.25,
            "reference_direction_alignment": 0.25,
            "outline_alignment": 0.10,
            "character_coverage": 0.05,
        }
        weighted = 0.0
        total_weight = 0.0
        for metric, weight in weights.items():
            value = metrics.get(metric)
            if value is None:
                continue
            weighted += float(value) * weight
            total_weight += weight
        if total_weight <= 0:
            return 0.0
        return _clamp_score(weighted / total_weight)

    def _build_summary(
        self,
        *,
        decision: str,
        score: float,
        issues: list[ParagraphBenchmarkIssue],
    ) -> str:
        if decision == "pass":
            return f"达到最小回归目标：约 {round(score * 100)} 分，逻辑与剧情承接没有明显硬伤。"
        if decision == "borderline":
            return f"接近最小回归目标：约 {round(score * 100)} 分，建议人工快速复核最近窗口承接。"
        if issues:
            return f"未达到最小回归目标：约 {round(score * 100)} 分，主要问题：{issues[0].message}"
        return f"未达到最小回归目标：约 {round(score * 100)} 分。"


class ParagraphBenchmarkService:
    """Runs the text-only N -> N+1 paragraph regression benchmark."""

    def __init__(
        self,
        *,
        segmenter: ParagraphSegmenter | None = None,
        reviewer: ParagraphBenchmarkReviewer | None = None,
        generation_service: ContinuationGenerationService | None = None,
    ) -> None:
        self.segmenter = segmenter or ParagraphSegmenter()
        self.reviewer = reviewer or ParagraphBenchmarkReviewer()
        self.generation_service = generation_service or ContinuationGenerationService()

    def run(
        self,
        *,
        source_path: Path,
        prefix_count: int,
        recent_window_size: int = 3,
        target_length_chars: int = 600,
        outline_path: Path | None = None,
        outline_text: str = "",
        character_names: list[str] | str | None = None,
        runs_dir: Path = Path("runs") / "paragraph_benchmark",
        generation_config: RunConfig | None = None,
    ) -> ParagraphBenchmarkRunResult:
        sample = self.build_sample(
            source_path=source_path,
            prefix_count=prefix_count,
            recent_window_size=recent_window_size,
            target_length_chars=target_length_chars,
            outline_path=outline_path,
            outline_text=outline_text,
            character_names=character_names,
        )
        prompt_text = self.build_prompt(sample)
        generated_text = self.generate(prompt=prompt_text, sample=sample, generation_config=generation_config)
        reviewer_report = self.reviewer.review(sample=sample, generated_text=generated_text)

        run_id = uuid.uuid4().hex
        run_dir = runs_dir.expanduser().resolve() / run_id
        self._write_run_artifacts(
            run_id=run_id,
            run_dir=run_dir,
            sample=sample,
            prompt_text=prompt_text,
            generated_text=generated_text,
            reviewer_report=reviewer_report,
        )
        return ParagraphBenchmarkRunResult(
            run_id=run_id,
            run_dir=str(run_dir),
            sample=sample,
            prompt_text=prompt_text,
            generated_text=generated_text,
            reviewer_report=reviewer_report,
        )

    def build_sample(
        self,
        *,
        source_path: Path,
        prefix_count: int,
        recent_window_size: int = 3,
        target_length_chars: int = 600,
        outline_path: Path | None = None,
        outline_text: str = "",
        character_names: list[str] | str | None = None,
    ) -> ParagraphBenchmarkSample:
        resolved_source_path = source_path.expanduser().resolve()
        if not resolved_source_path.exists():
            raise FileNotFoundError(f"source file not found: {resolved_source_path}")
        source_text = resolved_source_path.read_text(encoding="utf-8", errors="replace")
        segments = self.segmenter.split(source_text)
        normalized_prefix_count = int(prefix_count)
        if normalized_prefix_count < 1:
            raise ValueError("prefix_count must be >= 1")
        if normalized_prefix_count >= len(segments):
            raise ValueError(
                f"source only has {len(segments)} segments; prefix_count must leave at least one target segment"
            )
        prefix_segments = segments[:normalized_prefix_count]
        target_segment = segments[normalized_prefix_count]
        resolved_outline_text = self._resolve_outline_text(
            prefix_segments=prefix_segments,
            outline_path=outline_path,
            outline_text=outline_text,
        )
        return ParagraphBenchmarkSample(
            source_path=str(resolved_source_path),
            prefix_count=normalized_prefix_count,
            target_segment_index=normalized_prefix_count + 1,
            recent_window_size=recent_window_size,
            prefix_segments=prefix_segments,
            recent_segments=prefix_segments[-max(1, int(recent_window_size)):],
            reference_truth=target_segment,
            outline_text=resolved_outline_text,
            character_names=_normalize_string_list(character_names),
            target_length_chars=target_length_chars,
            total_segments=len(segments),
        )

    def build_prompt(self, sample: ParagraphBenchmarkSample) -> str:
        outline_block = f"之前剧情大纲：\n{sample.outline_text}\n\n" if sample.outline_text else ""
        character_block = (
            "需要保持一致的人物：" + "、".join(sample.character_names) + "\n\n"
            if sample.character_names
            else ""
        )
        return (
            "你正在执行一个最小小说续写回归测试。\n"
            "任务：只根据已给出的前文，续写下一小段正文。不要解释，不要输出评分。\n"
            f"目标：逻辑通顺、剧情连贯、不要弄混人物；长度约 {sample.target_length_chars} 字以内。\n\n"
            f"{outline_block}"
            f"{character_block}"
            f"最近 {len(sample.recent_segments)} 段连续剧情：\n{sample.recent_window_text}\n\n"
            "请续写下一段："
        ).strip()

    def generate(
        self,
        *,
        prompt: str,
        sample: ParagraphBenchmarkSample,
        generation_config: RunConfig | None = None,
    ) -> str:
        if generation_config is None:
            return self._fallback_generate(sample)
        return self.generation_service.generate(prompt=prompt, config=generation_config).generated_text.strip()

    def _fallback_generate(self, sample: ParagraphBenchmarkSample) -> str:
        last_segment = sample.recent_segments[-1] if sample.recent_segments else sample.prefix_segments[-1]
        excerpt = _safe_excerpt(last_segment, limit=min(260, sample.target_length_chars))
        if sample.character_names:
            names = "、".join(sample.character_names[:3])
            return f"{excerpt}\n\n{names}仍沿着前一段的情绪往下走，话没有说满，局面也没有立刻解决。"
        return f"{excerpt}\n\n局面顺着前一段继续推进，情绪没有突然断开，未解决的问题仍压在人物之间。"

    def _resolve_outline_text(
        self,
        *,
        prefix_segments: list[str],
        outline_path: Path | None,
        outline_text: str,
    ) -> str:
        if outline_text.strip():
            return outline_text.strip()
        if outline_path is not None:
            resolved_outline_path = outline_path.expanduser().resolve()
            if not resolved_outline_path.exists():
                raise FileNotFoundError(f"outline file not found: {resolved_outline_path}")
            return resolved_outline_path.read_text(encoding="utf-8", errors="replace").strip()
        return self._derive_tiny_outline(prefix_segments)

    def _derive_tiny_outline(self, prefix_segments: list[str]) -> str:
        recent = prefix_segments[-min(5, len(prefix_segments)):]
        lines = [f"- 段落 {index}: {_safe_excerpt(segment, 120)}" for index, segment in enumerate(recent, start=1)]
        return "\n".join(lines)

    def _write_run_artifacts(
        self,
        *,
        run_id: str,
        run_dir: Path,
        sample: ParagraphBenchmarkSample,
        prompt_text: str,
        generated_text: str,
        reviewer_report: ParagraphBenchmarkReviewerReport,
    ) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(run_dir / "benchmark_sample.json", sample.to_dict())
        (run_dir / "prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
        (run_dir / "generated.txt").write_text(generated_text + "\n", encoding="utf-8")
        (run_dir / "reference_truth.txt").write_text(sample.reference_truth + "\n", encoding="utf-8")
        self._write_json(run_dir / "reviewer_report.json", reviewer_report.to_dict())
        self._write_json(
            run_dir / "summary.json",
            {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "source_path": sample.source_path,
                "prefix_count": sample.prefix_count,
                "target_segment_index": sample.target_segment_index,
                "generated_chars": len(generated_text),
                "reference_truth_chars": len(sample.reference_truth),
                "decision": reviewer_report.decision,
                "score": reviewer_report.score,
            },
        )

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
