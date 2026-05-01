from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Sequence

from .character_mention_service import KNOWN_CHARACTER_NAMES


@dataclass(slots=True)
class CharacterEvidenceValidator:
    """
    Filters model-provided character mentions using evidence strings that must be verifiable
    against the original document text.

    Design goals:
    - Avoid "hallucinated" names by requiring evidence snippets to be literal substrings.
    - Avoid obvious false positives like verb phrases being treated as names (e.g. 张开/张望)
      without hard blacklisting: apply higher evidentiary bar for high-risk tokens.
    """

    # Second character often used as a verb morpheme; names matching Surname+VerbChar are high risk.
    _verbish_chars: frozenset[str] = frozenset(
        set(
            "开望看走跑跳笑哭喊叫问说道想拿把推拉放起落站坐转伸抱抓挥"
            "盯瞪抬低闯冲扑退躲闪掀拍摸捏掐踢踩啃咬撕扔吼啸"
        )
    )

    _speech_verbs = ("说", "问", "道", "喊", "叫", "答", "回道", "说道")
    _honorifics = ("先生", "小姐", "同学", "学长", "学姐", "教授", "校长", "队长", "秘书")

    def filter_names(
        self,
        *,
        doc_text: str,
        names: Sequence[str],
        evidence_map: Mapping[str, object] | None,
    ) -> list[str]:
        doc_text = self._norm(doc_text)
        if not doc_text.strip():
            return []

        cleaned: list[str] = []
        for raw in names:
            name = self._norm(str(raw)).strip()
            if not name:
                continue
            if not self._passes_known_prefix_guard(name=name, doc_text=doc_text):
                continue
            evidence_list = self._get_evidence_list(evidence_map=evidence_map, name=name)
            if not self._has_valid_evidence(name=name, evidence_list=evidence_list, doc_text=doc_text):
                continue
            if self._is_high_risk_name(name=name) and not self._passes_high_risk_bar(name=name, doc_text=doc_text):
                continue
            cleaned.append(name)
        return self._dedupe_preserve_order(cleaned)

    def _get_evidence_list(self, *, evidence_map: Mapping[str, object] | None, name: str) -> list[str]:
        if not evidence_map:
            return []
        raw = evidence_map.get(name)
        if isinstance(raw, list):
            return [self._norm(str(x)) for x in raw if isinstance(x, (str, int, float)) and str(x).strip()]
        if isinstance(raw, str) and raw.strip():
            return [self._norm(raw.strip())]
        return []

    def _has_valid_evidence(self, *, name: str, evidence_list: Sequence[str], doc_text: str) -> bool:
        if not evidence_list:
            return False
        for snippet in evidence_list:
            s = self._norm(str(snippet)).strip()
            if not s:
                continue
            if name not in s:
                continue
            if s not in doc_text:
                continue
            # For known characters, substring evidence is sufficient.
            if name in KNOWN_CHARACTER_NAMES:
                return True
            # For unknown tokens, require a personness cue in the evidence snippet.
            if not self._snippet_has_name_cue(name=name, snippet=s):
                continue
            return True
        return False

    def _is_high_risk_name(self, *, name: str) -> bool:
        # 2-char tokens like "张开" are often verb phrases.
        if len(name) != 2:
            return False
        return name[1] in self._verbish_chars

    def _passes_high_risk_bar(self, *, name: str, doc_text: str) -> bool:
        # For high-risk tokens, require stronger cues:
        # - introduced via naming pattern ("名叫张开"); OR
        # - used with explicit speaking verb ("张开说/问/道/喊").
        if re.search(rf"(?:名叫|叫做|名字是){re.escape(name)}", doc_text):
            return True
        if re.search(rf"{re.escape(name)}(?:说|问|道|喊|叫|答)", doc_text):
            return True
        return False

    def _passes_known_prefix_guard(self, *, name: str, doc_text: str) -> bool:
        # Drop partial prefixes when a longer known name appears in the same document.
        for known_raw in KNOWN_CHARACTER_NAMES:
            known = self._norm(known_raw)
            if known != name and known.startswith(name) and known in doc_text:
                return False
        return True

    def _dedupe_preserve_order(self, items: Sequence[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    def _snippet_has_name_cue(self, *, name: str, snippet: str) -> bool:
        escaped = re.escape(name)
        # Introduction patterns.
        if re.search(rf"(?:名叫|叫做|名字是){escaped}", snippet):
            return True
        # Speaking attribution: name directly followed by a speech verb.
        if re.search(rf"{escaped}(?:{'|'.join(map(re.escape, self._speech_verbs))})", snippet):
            return True
        # "对{name}说/问..." patterns.
        if re.search(rf"对{escaped}.{{0,8}}(?:{'|'.join(map(re.escape, self._speech_verbs))})", snippet):
            return True
        # Honorifics.
        if re.search(rf"{escaped}(?:{'|'.join(map(re.escape, self._honorifics))})", snippet):
            return True
        if re.search(rf"(?:{'|'.join(map(re.escape, self._honorifics))}){escaped}", snippet):
            return True
        return False

    def _norm(self, text: str) -> str:
        return unicodedata.normalize("NFKC", text)
