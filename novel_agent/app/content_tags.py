from __future__ import annotations

from itertools import chain


CONTENT_TAG_GROUPS: dict[str, list[str]] = {
    "描写方式": [
        "景色描写",
        "环境描写",
        "天气描写",
        "季节描写",
        "外貌描写",
        "神态描写",
        "动作描写",
        "语言描写",
        "人物对话",
        "心理活动",
        "内心独白",
        "感官描写",
        "细节描写",
        "侧面描写",
        "群像描写",
        "设定说明",
    ],
    "剧情结构": [
        "开场铺垫",
        "日常展开",
        "信息揭示",
        "伏笔埋设",
        "悬念制造",
        "冲突升级",
        "危机爆发",
        "高潮对抗",
        "反转揭晓",
        "收束过渡",
        "回忆插叙",
        "梦境幻觉",
        "预示暗示",
        "世界观引入",
        "任务发布",
        "情报交换",
    ],
    "人物关系": [
        "初次相遇",
        "重逢",
        "告别",
        "误会",
        "和解",
        "试探",
        "对峙",
        "合作",
        "背叛",
        "保护",
        "救援",
        "暧昧互动",
        "亲情互动",
        "友情互动",
        "师生互动",
        "敌对互动",
    ],
    "事件类型": [
        "追逐",
        "逃亡",
        "潜入",
        "调查",
        "审讯",
        "谈判",
        "仪式",
        "训练",
        "战斗描写",
        "群体冲突",
        "受伤疗伤",
        "旅行移动",
        "饮食场景",
        "学习考试",
        "社交聚会",
        "通信联络",
        "入学面试",
        "礼物赠送",
    ],
    "空间场景": [
        "校园",
        "教室",
        "宿舍",
        "图书馆",
        "操场",
        "食堂",
        "家庭住宅",
        "城市",
        "城市街道",
        "商场",
        "医院",
        "乡村",
        "森林",
        "山地",
        "河湖海",
        "地下空间",
        "遗迹古城",
        "车站机场",
        "酒店餐馆",
        "办公室",
        "实验室",
    ],
    "时间氛围": [
        "白天",
        "夜晚",
        "清晨",
        "黄昏",
        "雨天",
        "雪天",
        "节日",
        "紧张压迫",
        "温馨日常",
        "神秘诡异",
        "浪漫暧昧",
        "悲伤低落",
        "热血激昂",
        "荒诞幽默",
        "孤独感",
        "宿命感",
    ],
}


ALL_CONTENT_TAGS: tuple[str, ...] = tuple(chain.from_iterable(CONTENT_TAG_GROUPS.values()))
ALLOWED_CONTENT_TAGS: frozenset[str] = frozenset(ALL_CONTENT_TAGS)
CONTENT_TAG_TO_GROUP: dict[str, str] = {
    tag: group_name for group_name, tags in CONTENT_TAG_GROUPS.items() for tag in tags
}
CONTENT_TAG_GROUP_PRIORITY: dict[str, int] = {
    "空间场景": 6,
    "事件类型": 5,
    "时间氛围": 4,
    "剧情结构": 3,
    "人物关系": 2,
    "描写方式": 1,
}


def build_content_tag_reference_text() -> str:
    lines = [
        "以下是允许使用的内容标签词典；每个 document 只可从词典中选择最相关的 1-4 个标签。",
        "标签选择应优先遵循分组配额：先在各组内选出最高置信标签，再按全局相关性排序截取最多 4 个。",
        "不要自造标签，不要输出词典之外的近义词。",
    ]
    for group_name, tags in CONTENT_TAG_GROUPS.items():
        lines.append(f"- {group_name}: " + "、".join(tags))
    return "\n".join(lines)
