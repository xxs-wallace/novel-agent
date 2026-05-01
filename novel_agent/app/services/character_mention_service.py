from __future__ import annotations

import re
from collections.abc import Sequence

from .chinese_text_analyzer import ChineseTextAnalyzer

COMMON_NAME_PREFIXES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉"
    "岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元顾孟平黄和穆萧尹"
    "姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席"
    "季麻强贾路娄危江童颜郭梅盛林刁钟徐丘骆高夏蔡田樊胡凌霍虞万支柯昝管"
    "卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑裴陆荣楚"
)

CHARACTER_NAME_STOPWORDS = {
    "版权信息",
    "纸质版编目数据",
    "目录",
    "开篇",
    "本书",
    "电子邮箱",
    "数字传媒",
    "体育场路",
    "最后修订",
    "互联网",
    "许可证",
    "高中生",
    "高中三年级",
    "衰小孩",
    "学院",
    "手机",
    "通知",
    "录取通知",
    "时候",
    "房间",
    "地方",
    "东西",
    "消息",
    "电话",
    "短信",
}

KNOWN_CHARACTER_NAMES: set[str] = set()


class CharacterMentionService:
    def __init__(self) -> None:
        self.text_analyzer = ChineseTextAnalyzer()
        self._name_pattern = re.compile(
            r"([赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
            r"戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉"
            r"岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元顾孟平黄和穆萧尹"
            r"姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席"
            r"季麻强贾路娄危江童颜郭梅盛林刁钟徐丘骆高夏蔡田樊胡凌霍虞万支柯昝管"
            r"卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑裴陆荣楚]"
            r"[\u4e00-\u9fff]{1,2})(?=[说道问看想站走跑笑哭叫拿把朝向对跟给与进出回来去了"
            r"，。！？；：、“”‘’（）\s])"
        )

    def is_valid_character_name(self, keyword: str) -> bool:
        normalized = keyword.strip()
        if not normalized:
            return False
        if normalized in CHARACTER_NAME_STOPWORDS:
            return False
        if len(normalized) < 2 or len(normalized) > 12:
            return False
        if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]{2,12}", normalized):
            return False
        if normalized.endswith(("学院", "公司", "目录", "信息", "数据", "手机", "通知")):
            return False
        if len(normalized) <= 4 and normalized[0] in COMMON_NAME_PREFIXES:
            return True
        if "·" in normalized:
            return True
        if normalized in KNOWN_CHARACTER_NAMES:
            return True
        return False

    def clean_names(self, items: Sequence[object]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            keyword = str(item).strip()
            if not self.is_valid_character_name(keyword):
                continue
            if keyword in seen:
                continue
            seen.add(keyword)
            cleaned.append(keyword)
        return cleaned

    def extract_local_candidates(self, text: str, *, limit: int = 12) -> list[str]:
        counts: dict[str, int] = {}
        order: list[str] = []

        def add(token: str, *, weight: int = 1) -> None:
            normalized = token.strip()
            if not normalized:
                return
            if normalized not in counts:
                order.append(normalized)
            counts[normalized] = counts.get(normalized, 0) + weight

        for token, flag in self.text_analyzer.pos_tag(text[:8000]):
            if len(token) < 2 or len(token) > 12:
                continue
            if flag.startswith("nr") or flag.upper() in {"PER", "PERSON"}:
                add(token, weight=2)

        for token in self._name_pattern.findall(text):
            add(token)

        for token in re.findall(r"(?:名为|叫做|名字是)([\u4e00-\u9fff·]{2,8})", text):
            add(token)

        ranked = sorted(order, key=lambda item: (-counts[item], order.index(item)))
        return self.clean_names(ranked[:limit])

    def extract_document_mentions(self, documents: Sequence[object], *, per_doc_limit: int = 8) -> dict[int, list[str]]:
        mentions_by_doc_id: dict[int, list[str]] = {}
        for document in documents:
            doc_id = int(getattr(document, "doc_id"))
            content = str(getattr(document, "content", ""))
            mentions_by_doc_id[doc_id] = self.extract_local_candidates(content, limit=per_doc_limit)
        return mentions_by_doc_id
