from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache


_FALLBACK_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")


class ChineseTextAnalyzer:
    def __init__(self) -> None:
        self._jieba, self._jieba_posseg = _load_jieba_modules()

    @property
    def is_available(self) -> bool:
        return self._jieba is not None

    def segment(self, text: str) -> list[str]:
        if self._jieba is not None:
            return [token.strip() for token in self._jieba.cut(text, HMM=True) if token.strip()]
        return _fallback_segment(text)

    def pos_tag(self, text: str) -> list[tuple[str, str]]:
        if self._jieba_posseg is not None:
            return [(item.word.strip(), item.flag) for item in self._jieba_posseg.cut(text) if item.word.strip()]
        return [(token, "") for token in _fallback_segment(text)]

    def token_counter(self, text: str) -> Counter[str]:
        return Counter(self.segment(text))


@lru_cache(maxsize=1)
def _load_jieba_modules():
    try:
        import jieba  # type: ignore
        import jieba.posseg as pseg  # type: ignore
    except ImportError:
        return None, None
    _prime_jieba_dictionary(jieba)
    return jieba, pseg


def _prime_jieba_dictionary(jieba_module) -> None:
    _ = jieba_module


def _fallback_segment(text: str) -> list[str]:
    return [match.group(0) for match in _FALLBACK_TOKEN_PATTERN.finditer(text)]
