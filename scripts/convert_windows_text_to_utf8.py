#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ConversionResult:
    source_path: Path
    output_path: Path
    encoding: str
    backup_path: Path | None


class TextEncodingConverter:
    """Convert Windows-edited text files to UTF-8 for macOS-friendly editing."""

    def __init__(self, candidate_encodings: Iterable[str] | None = None) -> None:
        self._candidate_encodings = tuple(
            candidate_encodings
            or (
                "utf-8-sig",
                "gb18030",
                "gbk",
                "big5",
                "cp1252",
                "latin-1",
            )
        )

    def detect_encoding(self, data: bytes) -> str:
        bom_encoding = self._detect_bom_encoding(data)
        if bom_encoding is not None:
            return bom_encoding

        if self._looks_like_utf16_without_bom(data):
            for encoding in ("utf-16le", "utf-16be"):
                try:
                    data.decode(encoding)
                    return encoding
                except UnicodeDecodeError:
                    continue

        for encoding in self._candidate_encodings:
            try:
                data.decode(encoding)
                return encoding
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("unknown", data, 0, 1, "unable to detect a supported encoding")

    def convert_file(
        self,
        source_path: str | Path,
        output_path: str | Path | None = None,
        *,
        overwrite: bool = False,
        backup_suffix: str = ".bak",
    ) -> ConversionResult:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"File not found: {source}")

        raw_data = source.read_bytes()
        encoding = self.detect_encoding(raw_data)
        text = raw_data.decode(encoding)
        normalized_text = self._normalize_newlines(text)

        backup_path: Path | None = None
        if overwrite:
            backup_path = source.with_name(f"{source.name}{backup_suffix}")
            backup_path.write_bytes(raw_data)
            target = source
        else:
            target = Path(output_path).expanduser().resolve() if output_path else self._default_output_path(source)

        with target.open("w", encoding="utf-8", newline="\n") as file:
            file.write(normalized_text)
        return ConversionResult(source_path=source, output_path=target, encoding=encoding, backup_path=backup_path)

    @staticmethod
    def _default_output_path(source: Path) -> Path:
        return source.with_name(f"{source.stem}.utf8{source.suffix}")

    @staticmethod
    def _normalize_newlines(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _detect_bom_encoding(data: bytes) -> str | None:
        if data.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
            return "utf-16"
        return None

    @staticmethod
    def _looks_like_utf16_without_bom(data: bytes) -> bool:
        if len(data) < 4:
            return False

        even_nuls = sum(1 for byte in data[0::2] if byte == 0)
        odd_nuls = sum(1 for byte in data[1::2] if byte == 0)
        even_ratio = even_nuls / max(len(data[0::2]), 1)
        odd_ratio = odd_nuls / max(len(data[1::2]), 1)
        return max(even_ratio, odd_ratio) > 0.3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a Windows text file to UTF-8 with Unix newlines.")
    parser.add_argument("source", help="Path to the source text file")
    parser.add_argument(
        "--output",
        help="Path to the converted UTF-8 file. Defaults to '<name>.utf8<suffix>' when not overwriting.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the source file after creating a backup copy.",
    )
    parser.add_argument(
        "--backup-suffix",
        default=".bak",
        help="Backup suffix used when --overwrite is enabled. Default: .bak",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.overwrite and args.output:
        parser.error("--output cannot be used together with --overwrite")

    converter = TextEncodingConverter()
    result = converter.convert_file(
        args.source,
        output_path=args.output,
        overwrite=args.overwrite,
        backup_suffix=args.backup_suffix,
    )

    print(f"Detected encoding: {result.encoding}")
    print(f"Converted file: {result.output_path}")
    if result.backup_path is not None:
        print(f"Backup file: {result.backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
