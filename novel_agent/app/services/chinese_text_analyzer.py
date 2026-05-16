from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache


_FALLBACK_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")


class ChineseTextAnalyzer:
    def __init__(self) -> None:
        self._jieba = _load_jieba_module()

    @property
    def is_available(self) -> bool:
        return self._jieba is not None

    def segment(self, text: str) -> list[str]:
        if self._jieba is not None:
            return [token.strip() for token in self._jieba.cut(text, HMM=True) if token.strip()]
        return _fallback_segment(text)

    def token_counter(self, text: str) -> Counter[str]:
        return Counter(self.segment(text))


@lru_cache(maxsize=1)
def _load_jieba_module():
    try:
        import jieba  # type: ignore
    except ImportError:
        return None
    _prime_jieba_dictionary(jieba)
    return jieba


def _prime_jieba_dictionary(jieba_module) -> None:
    _ = jieba_module


def _fallback_segment(text: str) -> list[str]:
    return [match.group(0) for match in _FALLBACK_TOKEN_PATTERN.finditer(text)]
