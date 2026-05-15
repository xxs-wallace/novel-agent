from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_MAX_BYTES = 240 * 1024


def extract_prefix_at_newline(source_path: Path, max_bytes: int) -> bytes:
    raw = source_path.expanduser().read_bytes()
    if len(raw) < max_bytes:
        raise ValueError(f"source is only {len(raw)} bytes; need at least {max_bytes} bytes")

    prefix = raw[:max_bytes]
    newline_index = prefix.rfind(b"\n")
    if newline_index < 0:
        raise ValueError(f"no newline found in first {max_bytes} bytes")

    extracted = prefix[: newline_index + 1]
    extracted.decode("utf-8")
    if not extracted.endswith(b"\n"):
        raise AssertionError("extracted prefix must end with newline")
    return extracted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract a UTF-8 text prefix ending at a newline boundary.")
    parser.add_argument("--source", default="~/longzu.txt", help="Source UTF-8 text file")
    parser.add_argument("--output", default="novel_agent/tests/longzu_240kb.txt", help="Output fixture path")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="Maximum output bytes")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_path = Path(args.source).expanduser()
    output_path = Path(args.output).expanduser()
    extracted = extract_prefix_at_newline(source_path, int(args.max_bytes))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(extracted)
    print(f"wrote {output_path} ({len(extracted)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
