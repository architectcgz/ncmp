import re
from typing import Iterable, Optional, Tuple


# 只识别直接评价音乐的短语，避免把歌词中的悲伤或听众的生活经历当作差评。
OPINION_RULES = (
    (
        "A-1", "歌词表达",
        re.compile(r"歌词.{0,6}(?:走心|有共鸣|不错|很好|优秀|感人|用心|有深度)"),
        re.compile(r"歌词.{0,6}(?:空洞|尴尬|没共鸣|没有共鸣|不走心|很差|太差)"),
    ),
    (
        "B-1", "旋律和听感",
        re.compile(r"好听|耐听|悦耳|抓耳|上头|旋律.{0,6}(?:优美|不错|动听|有记忆点)"),
        re.compile(r"难听|不好听|不(?:太|怎么|够)好听|不耐听|刺耳|(?:旋律|编曲).{0,6}(?:平平|单调|生硬|很差|太差)"),
    ),
    (
        "C-1", "演唱表现",
        re.compile(r"(?:唱功|演唱|人声).{0,6}(?:不错|很好|扎实|惊艳|出色)|唱得(?:很好|好)"),
        re.compile(r"(?:唱功|演唱|人声).{0,6}(?:不好|很差|太差|不行)|唱得(?:不好|很差)|跑调|破音"),
    ),
)


def evaluate_comments(comments: Iterable[dict]) -> Optional[Tuple[str, str, str]]:
    """根据公开评论估计评分、标签和摘要，意见不足时返回 None。

    参数为评论接口返回的记录；相同文本或同一用户最多贡献一票。
    至少需要三条倾向明确的音乐评价，分数保守限定在 2～4 分。
    """
    seen_texts = set()
    seen_users = set()
    positive_counts = [0] * len(OPINION_RULES)
    negative_counts = [0] * len(OPINION_RULES)
    positive_votes = negative_votes = 0

    # ponytail: 短语规则无法理解反讽和复杂上下文，语义误判明显时改用人工确认或语义模型。
    for item in comments:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str):
            continue
        text = re.sub(r"\s+", "", item["content"]).casefold()
        user = item.get("user")
        user_id = user.get("userId") if isinstance(user, dict) else None
        user_key = str(user_id)
        if not user_key.isascii() or not user_key.isdigit() or int(user_key) <= 0:
            continue
        if not text or text in seen_texts or user_key in seen_users:
            continue
        seen_texts.add(text)

        # “不难听”不等于明确好评；先移除它，避免误算为差评。
        text = re.sub(r"(?:不(?:是|算|太)?|没(?:有)?)(?:难听|跑调|刺耳|单调|不好听|不耐听)", "", text)
        praise_text = re.sub(
            r"(?:不(?:太|怎么|够|算|是|觉得)?|没(?:有)?)(?:好听|耐听|上头|抓耳|共鸣|走心|惊艳|不错|悦耳|优美|动听|有记忆点|很好|优秀|感人|用心|有深度|扎实|出色)",
            "", text,
        )
        positive = [bool(rule[2].search(praise_text)) for rule in OPINION_RULES]
        negative = [bool(rule[3].search(text)) for rule in OPINION_RULES]
        # 同一条评论同时褒贬时不猜测其最终倾向。
        if any(positive) == any(negative):
            continue
        seen_users.add(user_key)
        if any(positive):
            positive_votes += 1
            positive_counts = [count + hit for count, hit in zip(positive_counts, positive)]
        else:
            negative_votes += 1
            negative_counts = [count + hit for count, hit in zip(negative_counts, negative)]

    total = positive_votes + negative_votes
    if total < 3:
        return None
    ratio = positive_votes / total
    score = 4 if ratio >= 2 / 3 else 2 if ratio <= 1 / 3 else 3
    counts = negative_counts if score == 2 else positive_counts
    dimension = max(range(len(counts)), key=counts.__getitem__)
    suffix, aspect, _, _ = OPINION_RULES[dimension]
    summary = {
        2: f"{aspect}的不足被多次提及。",
        3: f"听众对{aspect}的看法存在分歧。",
        4: f"{aspect}获得较多认可。",
    }[score]
    comment = f"参考{total}条公开评论（正面{positive_votes}条、负面{negative_votes}条），{summary}"
    return str(score), f"{score}-{suffix}", comment
