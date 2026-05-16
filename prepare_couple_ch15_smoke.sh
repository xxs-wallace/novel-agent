#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_ROOT/.venv"

# Input / output configuration. Override with env vars when needed.
SOURCE_TXT="${SOURCE_TXT:-$REPO_ROOT/couple.txt}"
BOOK_ID="${BOOK_ID:-couple_smoke}"
WORK_ROOT="${WORK_ROOT:-$REPO_ROOT/.smoke/couple_ch15}"
DB_PATH="${DB_PATH:-$WORK_ROOT/couple_ch15.db}"
RUNS_DIR="${RUNS_DIR:-$WORK_ROOT/runs}"
SAMPLE_DIR="${SAMPLE_DIR:-$WORK_ROOT/sample_ch15}"
DEEPSEEK_API_FILE="${DEEPSEEK_API_FILE:-$HOME/deepseek.api}"

# Chapter 15 starts after about 197 KB UTF-8 / 69k chars and chapter 16 starts
# around 213 KB UTF-8 / 74k chars. 100 KB is not enough for a chapter-15 smoke.
# We therefore cap processing to ~80k chars, which is still far below full-book cost.
MAX_READ_CHARS="${MAX_READ_CHARS:-80000}"
MAX_CHAPTERS="${MAX_CHAPTERS:-15}"
TARGET_CHAPTER_NO="${TARGET_CHAPTER_NO:-15}"
ANCHOR_TAIL_CHARS="${ANCHOR_TAIL_CHARS:-1200}"
TRUTH_HEAD_CHARS="${TRUTH_HEAD_CHARS:-2200}"
STEP_TARGET_CHARS="${STEP_TARGET_CHARS:-2000}"

choose_python() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    echo "$VENV_DIR/bin/python"
    return 0
  fi

  local candidates=(
    "python3.12"
    "python3.11"
    "python3.10"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$(command -v "$candidate")"
      return 0
    fi
  done

  echo "未找到 Python 3.10+ 解释器。请先安装 python3.10 / python3.11 / python3.12。" >&2
  return 1
}

ensure_python_version() {
  local python_bin="$1"
  "$python_bin" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("当前解释器版本低于 3.10，无法运行本项目。")
PY
}

ensure_venv() {
  local base_python="$1"
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "创建虚拟环境: $VENV_DIR"
    "$base_python" -m venv "$VENV_DIR"
  fi
}

ensure_dependencies() {
  local python_bin="$1"
  if "$python_bin" - <<'PY' >/dev/null 2>&1
import importlib
mods = [
    "smolagents",
    "openai",
    "jieba",
    "dotenv",
    "requests",
    "rich",
    "jinja2",
    "PIL",
]
for mod in mods:
    importlib.import_module(mod)
PY
  then
    return 0
  fi

  echo "检测到缺失依赖，开始安装..."
  "$python_bin" -m pip install --upgrade pip setuptools wheel
  "$python_bin" -m pip install -e "$REPO_ROOT[openai]" PyYAML
}

ensure_deepseek_api_key() {
  if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
    export DEEPSEEK_API_KEY
    return 0
  fi
  if [[ -f "$DEEPSEEK_API_FILE" ]]; then
    DEEPSEEK_API_KEY="$(tr -d '\r' < "$DEEPSEEK_API_FILE" | head -n 1 | xargs)"
    if [[ -n "$DEEPSEEK_API_KEY" ]]; then
      export DEEPSEEK_API_KEY
      return 0
    fi
  fi
  echo "未找到可用的 DEEPSEEK_API_KEY。请先设置环境变量，或在 $DEEPSEEK_API_FILE 中写入 API Key。" >&2
  return 1
}

BASE_PYTHON="$(choose_python)"
ensure_python_version "$BASE_PYTHON"
ensure_venv "$BASE_PYTHON"

PYTHON_BIN="$VENV_DIR/bin/python"
ensure_python_version "$PYTHON_BIN"
ensure_dependencies "$PYTHON_BIN"
ensure_deepseek_api_key

export PYTHONPATH="$REPO_ROOT/src:$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -f "$SOURCE_TXT" ]]; then
  echo "源文件不存在: $SOURCE_TXT" >&2
  exit 1
fi

mkdir -p "$WORK_ROOT" "$RUNS_DIR" "$SAMPLE_DIR"

echo "使用解释器: $PYTHON_BIN"
echo "工作目录: $WORK_ROOT"
echo "数据库路径: $DB_PATH"
echo "样本目录: $SAMPLE_DIR"
echo "阶段 1/3: 导入原文，只读取前 $MAX_READ_CHARS 字符"

"$PYTHON_BIN" -m novel_agent.app.run_segment_book \
  --repo-root "$REPO_ROOT" \
  --db "$DB_PATH" \
  --book-id "$BOOK_ID" \
  --source-root "$SOURCE_TXT" \
  --max-read-chars "$MAX_READ_CHARS"

echo "阶段 2/3: 开始阅读，只处理前 $MAX_CHAPTERS 章"

"$PYTHON_BIN" -m novel_agent.app.run_close_read \
  --repo-root "$REPO_ROOT" \
  --db "$DB_PATH" \
  --book-id "$BOOK_ID" \
  --max-chapters "$MAX_CHAPTERS"

echo "阶段 3/3: 生成 chapter-$TARGET_CHAPTER_NO 双段 smoke 样本草案"

"$PYTHON_BIN" - <<'PY' "$SOURCE_TXT" "$SAMPLE_DIR" "$BOOK_ID" "$TARGET_CHAPTER_NO" "$ANCHOR_TAIL_CHARS" "$TRUTH_HEAD_CHARS" "$STEP_TARGET_CHARS"
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

source_txt = Path(sys.argv[1]).expanduser().resolve()
sample_dir = Path(sys.argv[2]).expanduser().resolve()
book_id = sys.argv[3]
target_chapter_no = int(sys.argv[4])
anchor_tail_chars = int(sys.argv[5])
truth_head_chars = int(sys.argv[6])
step_target_chars = int(sys.argv[7])

text = source_txt.read_text(encoding="utf-8", errors="replace")
chapter_pattern = re.compile(r"（([一二三四五六七八九十]+)）")
cn_map = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
    "十三": 13,
    "十四": 14,
    "十五": 15,
    "十六": 16,
    "十七": 17,
    "十八": 18,
    "十九": 19,
    "二十": 20,
}

matches = list(chapter_pattern.finditer(text))
chapters: dict[int, str] = {}
for index, match in enumerate(matches):
    label = match.group(1)
    chapter_no = cn_map.get(label)
    if chapter_no is None:
        continue
    start = match.end()
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    body = text[start:end].strip()
    chapters[chapter_no] = body

required = [target_chapter_no - 2, target_chapter_no - 1, target_chapter_no]
missing = [number for number in required if not chapters.get(number)]
if missing:
    raise SystemExit(f"章节提取失败，缺少章节: {missing}")

sample_dir.mkdir(parents=True, exist_ok=True)

recent_1 = chapters[target_chapter_no - 2].strip()
recent_2 = chapters[target_chapter_no - 1].strip()
chapter_text = chapters[target_chapter_no].strip()
truth_text = chapter_text[:truth_head_chars].strip()
if not truth_text:
    raise SystemExit("目标章节真值片段为空，无法生成 smoke sample")

def split_two_steps(text: str) -> tuple[str, str]:
    text = text.strip()
    if not text:
        return "", ""
    split_index = max(len(text) // 2, min(700, len(text)))
    punctuation_indexes = [
        index for index, ch in enumerate(text)
        if ch in "。！？!?；;\n"
    ]
    candidate_indexes = [index + 1 for index in punctuation_indexes if split_index - 220 <= index + 1 <= split_index + 220]
    if candidate_indexes:
        split_index = candidate_indexes[0]
    first = text[:split_index].strip()
    second = text[split_index:].strip()
    if not second:
        second = first
    return first, second

truth_1, truth_2 = split_two_steps(truth_text)
anchor_text = recent_2[-anchor_tail_chars:].strip()
anchor_2 = truth_1[-anchor_tail_chars:].strip() or truth_1
recent_step_2 = truth_1.strip()

(sample_dir / "recent_13.md").write_text(recent_1 + "\n", encoding="utf-8")
(sample_dir / "recent_14.md").write_text(recent_2 + "\n", encoding="utf-8")
(sample_dir / "anchor_step_1.md").write_text(anchor_text + "\n", encoding="utf-8")
(sample_dir / "truth_step_1.md").write_text(truth_1 + "\n", encoding="utf-8")
(sample_dir / "recent_step_2.md").write_text(recent_step_2 + "\n", encoding="utf-8")
(sample_dir / "anchor_step_2.md").write_text(anchor_2 + "\n", encoding="utf-8")
(sample_dir / "truth_step_2.md").write_text(truth_2 + "\n", encoding="utf-8")

sample_payload = {
    "sample_id": f"couple-ch{target_chapter_no}-two-step",
    "book_id": book_id,
    "target_chapter_id": f"chapter-{target_chapter_no}",
    "target_segment_id": "step-2-followup",
    "mode": "chapter_authorized",
    "anchor_context_path": "anchor_step_1.md",
    "recent_window_refs": ["recent_13.md", "recent_14.md"],
    "documents_cutoff": {
        "max_document_title_index": str(target_chapter_no - 1)
    },
    "allowed_outline_scope": {
        "chapter_range": [
            str(target_chapter_no),
            f"第{target_chapter_no}章",
            "（十五）",
        ],
        "allow_future_outline": False,
    },
    "reference_truth_path": "truth_step_1.md",
    "metadata": {
        "target_length_chars": step_target_chars,
        "window_size": 2,
        "source_text_path": str(source_txt),
        "note": "该草案将第15章开头拆成两段 smoke，并将每一步目标生成长度提高到约 2000 字。",
    },
    "continuation_steps": [
        {
            "step_id": "step-1",
            "target_segment_id": "opening",
            "anchor_context_path": "anchor_step_1.md",
            "recent_window_refs": ["recent_13.md", "recent_14.md"],
            "reference_truth_path": "truth_step_1.md",
            "metadata": {
                "target_length_chars": step_target_chars,
                "window_size": 2,
                "expansion_note": "允许在不违背原文走向的前提下显著扩写细节、动作、心理和对白。",
            },
        },
        {
            "step_id": "step-2",
            "target_segment_id": "followup",
            "anchor_context_path": "anchor_step_2.md",
            "recent_window_refs": ["recent_14.md", "recent_step_2.md"],
            "reference_truth_path": "truth_step_2.md",
            "metadata": {
                "target_length_chars": step_target_chars,
                "window_size": 2,
                "expansion_note": "在承接 step-1 回填人物状态的基础上继续扩写，保持剧情推进。",
            },
        },
    ],
}

(sample_dir / "sample.json").write_text(
    json.dumps(sample_payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

(sample_dir / "README.txt").write_text(
    "\n".join(
        [
            f"source: {source_txt}",
            f"target_chapter: {target_chapter_no}",
            "recent_window_refs: recent_13.md + recent_14.md",
            "step-1: anchor_step_1.md + truth_step_1.md",
            "step-2: anchor_step_2.md + truth_step_2.md",
            f"step target chars: {step_target_chars}",
            "即便真值较短，sample 也会把目标生成长度提升到更长的扩写尺度。",
            "如需更长的真值片段，可提高 TRUTH_HEAD_CHARS。",
        ]
    )
    + "\n",
    encoding="utf-8",
)

print(
    json.dumps(
        {
            "sample_path": str(sample_dir / "sample.json"),
            "step_1_anchor_path": str(sample_dir / "anchor_step_1.md"),
            "step_1_truth_path": str(sample_dir / "truth_step_1.md"),
            "step_2_anchor_path": str(sample_dir / "anchor_step_2.md"),
            "step_2_truth_path": str(sample_dir / "truth_step_2.md"),
            "recent_window_refs": [
                str(sample_dir / "recent_13.md"),
                str(sample_dir / "recent_14.md"),
                str(sample_dir / "recent_step_2.md"),
            ],
            "step_1_truth_chars": len(truth_1),
            "step_2_truth_chars": len(truth_2),
            "step_target_chars": step_target_chars,
        },
        ensure_ascii=False,
        indent=2,
    )
)
PY

echo ""
echo "准备完成。下一步可运行："
echo "\"$REPO_ROOT/run_single_sample_smoke.sh\" --sample \"$SAMPLE_DIR/sample.json\" --repo-root \"$REPO_ROOT\" --db \"$DB_PATH\" --runs-dir \"$RUNS_DIR\""
echo ""
echo "若要启用真实模型生成，请在上面的命令后继续追加："
echo "--use-real-model --model-type OpenAIModel --model-id deepseek-v4-pro --api-base https://api.deepseek.com --api-key \$DEEPSEEK_API_KEY --thinking enabled --reasoning-effort high --save-reasoning"
