from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


def _char_width(char: str) -> int:
    if not char:
        return 0
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1


def _cluster_start(text: str, index: int) -> int:
    start = max(0, index - 1)
    while start > 0 and unicodedata.combining(text[start]):
        start -= 1
    return start


@dataclass(slots=True)
class ChineseInputBuffer:
    """Small input model with wcwidth-aware cursor math for tests and minimal CLI use."""

    text: str = ""
    cursor: int = 0
    history: list[str] = field(default_factory=list)

    @classmethod
    def from_text(cls, text: str) -> "ChineseInputBuffer":
        return cls(text=text, cursor=len(text))

    def insert(self, value: str) -> None:
        if not value:
            return
        self.text = f"{self.text[: self.cursor]}{value}{self.text[self.cursor :]}"
        self.cursor += len(value)

    def paste(self, value: str) -> None:
        self.insert(value.replace("\r\n", "\n").replace("\r", "\n"))

    def backspace(self) -> str:
        if self.cursor <= 0:
            return ""
        start = _cluster_start(self.text, self.cursor)
        removed = self.text[start : self.cursor]
        self.text = f"{self.text[:start]}{self.text[self.cursor:]}"
        self.cursor = start
        return removed

    def delete_word_back(self) -> str:
        if self.cursor <= 0:
            return ""
        index = self.cursor
        while index > 0 and self.text[index - 1].isspace():
            index -= 1
        while index > 0 and not self.text[index - 1].isspace():
            index -= 1
        removed = self.text[index : self.cursor]
        self.text = f"{self.text[:index]}{self.text[self.cursor:]}"
        self.cursor = index
        return removed

    def move_left(self) -> None:
        if self.cursor > 0:
            self.cursor = _cluster_start(self.text, self.cursor)

    def move_right(self) -> None:
        if self.cursor < len(self.text):
            self.cursor += 1
            while self.cursor < len(self.text) and unicodedata.combining(self.text[self.cursor]):
                self.cursor += 1

    def move_home(self) -> None:
        line_start = self.text.rfind("\n", 0, self.cursor) + 1
        self.cursor = max(0, line_start)

    def move_end(self) -> None:
        line_end = self.text.find("\n", self.cursor)
        self.cursor = len(self.text) if line_end < 0 else line_end

    def kill_to_end(self) -> str:
        line_end = self.text.find("\n", self.cursor)
        end = len(self.text) if line_end < 0 else line_end
        removed = self.text[self.cursor : end]
        self.text = f"{self.text[: self.cursor]}{self.text[end:]}"
        return removed

    def kill_to_start(self) -> str:
        line_start = self.text.rfind("\n", 0, self.cursor) + 1
        removed = self.text[line_start : self.cursor]
        self.text = f"{self.text[:line_start]}{self.text[self.cursor:]}"
        self.cursor = line_start
        return removed

    def commit(self) -> str:
        value = self.text
        if value:
            self.history.append(value)
        self.text = ""
        self.cursor = 0
        return value

    def display_cursor_column(self) -> int:
        line_start = self.text.rfind("\n", 0, self.cursor) + 1
        return sum(_char_width(char) for char in self.text[line_start : self.cursor])

    def visual_width(self) -> int:
        return max(sum(_char_width(char) for char in line) for line in self.text.split("\n") or [""])

    def handle_control_key(self, key: str) -> None:
        normalized = key.upper()
        if normalized == "CTRL+A":
            self.move_home()
        elif normalized == "CTRL+E":
            self.move_end()
        elif normalized == "CTRL+B":
            self.move_left()
        elif normalized == "CTRL+F":
            self.move_right()
        elif normalized == "CTRL+K":
            self.kill_to_end()
        elif normalized == "CTRL+U":
            self.kill_to_start()
        elif normalized == "CTRL+W":
            self.delete_word_back()
