from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CHINESE_CHAR_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def count_chinese_chars(text: str) -> int:
    return len(CHINESE_CHAR_PATTERN.findall(text))


def find_split_aligned_to_newline(text: str) -> int:
    total_chinese = count_chinese_chars(text)
    half_chinese = total_chinese // 2
    seen = 0
    half_index = 0
    for index, char in enumerate(text):
        if CHINESE_CHAR_PATTERN.fullmatch(char):
            seen += 1
            if seen >= half_chinese:
                half_index = index + 1
                break

    newline_index = text.rfind("\n", 0, half_index)
    if newline_index < 0:
        raise ValueError("No newline found before the Chinese-character midpoint.")
    return newline_index + 1


def inspect(path: Path) -> dict[str, object]:
    raw = path.expanduser().read_bytes()
    text = raw.decode("utf-8")
    split_index = find_split_aligned_to_newline(text)
    prefix = text[:split_index]
    reference = text[split_index:]
    return {
        "path": str(path),
        "total_bytes": len(raw),
        "total_python_chars": len(text),
        "total_chinese_chars": count_chinese_chars(text),
        "split_index_python_chars": split_index,
        "split_endswith_newline": prefix.endswith("\n"),
        "prefix": {
            "python_chars": len(prefix),
            "chinese_chars": count_chinese_chars(prefix),
            "bytes": len(prefix.encode("utf-8")),
        },
        "reference": {
            "python_chars": len(reference),
            "chinese_chars": count_chinese_chars(reference),
            "bytes": len(reference.encode("utf-8")),
        },
        "recommended_smoke_args": {
            "prefix_min_chars": len(prefix),
            "reference_min_chars": len(reference),
            "note": "run_single_sample_smoke compares len(text), not Chinese-only character count.",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a Chinese-character half split aligned to newline.")
    parser.add_argument("path", nargs="?", default="novel_agent/tests/longzu_240kb.txt")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = inspect(Path(args.path))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
