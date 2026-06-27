#!/usr/bin/env python3
"""
有害内容过滤器 — 纯 Python 标准库
检测 LLM 输出中的暴力、色情、违法、自残等内容
"""

import re
from dataclasses import dataclass
from typing import Optional

# ============ 有害内容模式库 ============

VIOLENCE_PATTERNS = [
    # 暴力煽动
    (r"(杀光|灭掉|消灭|清除).{0,5}(他们|这群|所有|一切)", "high", "暴力煽动"),
    (r"(应该|必须|一定要).{0,10}(打|揍|砍|捅|炸|杀)", "high", "暴力教唆"),
    (r"怎么.{0,5}(制作|自制).{0,5}(炸弹|炸药|武器|枪支)", "high", "危险品制作"),
    (r"(打死|弄死|搞死|整死).{0,5}(他|她|你|它)", "high", "人身威胁"),
    (r"详细.{0,10}(杀人|行凶|作案).{0,10}(方法|步骤|教程)", "high", "犯罪教程"),
    # 暴力描述
    (r"(血肉模糊|脑浆|断肢|开膛|分尸|肢解)", "medium", "血腥描述"),
    (r"(虐待|折磨).{0,10}(动物|小孩|老人|弱者)", "medium", "虐待描述"),
    (r"(校园暴力|校园霸凌).{0,10}(很爽|活该|打得好)", "medium", "暴力美化"),
]

PORN_PATTERNS = [
    (r"(裸体|裸照|裸聊|色情|淫秽|黄色)", "high", "色情内容"),
    (r"(性交|做爱|上床|啪啪|约炮)", "high", "性行为描述"),
    (r"(成人网站|色情网站|黄片|AV).{0,5}(地址|链接|网址|资源)", "high", "色情资源分享"),
    (r"(未成年|儿童|幼女|幼童).{0,10}(色情|性|裸)", "high", "儿童色情"),
    (r"(强奸|迷奸|诱奸|轮奸)", "high", "性暴力"),
    (r"(怎么|如何).{0,10}(约炮|嫖娼|找小姐|找鸡)", "medium", "嫖娼引导"),
]

ILLEGAL_PATTERNS = [
    (r"(贩卖|走私|交易).{0,5}(毒品|枪支|弹药|器官|人口)", "high", "违法交易"),
    (r"(黑客|入侵|破解|盗取).{0,15}(教程|方法|工具|软件)", "high", "网络犯罪教程"),
    (r"(洗钱|逃税|行贿|受贿|贪污).{0,5}(方法|技巧|门路)", "high", "经济犯罪方法"),
    (r"(怎么|如何).{0,10}(造假|伪造|仿冒).{0,5}(证件|证书|印章)", "high", "伪造教程"),
    (r"(电信诈骗|网络诈骗|杀猪盘).{0,5}(话术|教程|流程)", "high", "诈骗教程"),
    (r"(赌博|赌场|博彩).{0,5}(技巧|必胜|稳赢|平台|网站)", "medium", "赌博引导"),
]

SELF_HARM_PATTERNS = [
    (r"(自杀|自残|割腕|跳楼|上吊|服毒).{0,10}(方法|教程|步骤|怎么做)", "high", "自残教程"),
    (r"(不想活了|活着没意思|一了百了|死了算了)", "high", "自杀倾向"),
    (r"(抑郁|焦虑|失眠).{0,10}(就该|都是).{0,5}(矫情|装的|作的)", "medium", "心理疾病污名化"),
    (r"(厌食|暴食|催吐).{0,10}(减肥|瘦身).{0,10}(方法|教程)", "medium", "饮食障碍引导"),
]

HATE_SPEECH_PATTERNS = [
    (r"(支那|蝗虫|白皮猪|黑鬼|阿三|棒子|鬼子)", "high", "种族辱骂"),
    (r"(同性恋|gay|les).{0,5}(恶心|变态|有病|该杀|应该)", "high", "性取向仇恨"),
    (r"(穆斯林|回民|佛教徒|基督徒).{0,5}(都是|就是).{0,5}(恐怖|极端|愚昧)", "high", "宗教仇恨"),
    (r"(残疾人|残废|瘸子|瞎子|聋子).{0,5}(就是|都是|活该|废物)", "high", "残障歧视"),
]


@dataclass
class FilterResult:
    """过滤检测结果"""
    text: str
    category: str
    severity: str
    label: str
    matched: str
    action: str        # block / warn / review


class ContentFilter:
    """有害内容过滤器"""

    def __init__(self):
        self.all_patterns = {
            "violence":   ("暴力内容", VIOLENCE_PATTERNS),
            "porn":       ("色情内容", PORN_PATTERNS),
            "illegal":    ("违法内容", ILLEGAL_PATTERNS),
            "self_harm":  ("自残内容", SELF_HARM_PATTERNS),
            "hate":       ("仇恨言论", HATE_SPEECH_PATTERNS),
        }

    def scan(self, text: str) -> list[FilterResult]:
        """扫描文本中的所有有害内容"""
        results = []
        for key, (cat_name, patterns) in self.all_patterns.items():
            for pattern, severity, label in patterns:
                if m := re.search(pattern, text):
                    action = "block" if severity == "high" else "warn"
                    results.append(FilterResult(
                        text=text, category=cat_name, severity=severity,
                        label=label, matched=m.group(0), action=action,
                    ))
        return self._deduplicate(results)

    def should_block(self, text: str) -> tuple[bool, list[FilterResult]]:
        """判断是否应阻止该内容，返回 (阻止, 原因列表)"""
        results = self.scan(text)
        high_severity = [r for r in results if r.severity == "high"]
        return (len(high_severity) > 0, high_severity)

    def _deduplicate(self, results: list) -> list:
        seen = {}
        for r in results:
            key = r.matched[:20]
            if key not in seen:
                seen[key] = r
        return list(seen.values())

    @property
    def stats(self) -> dict:
        total = sum(len(p) for _, p in self.all_patterns.values())
        return {"total_patterns": total, "categories": len(self.all_patterns)}


def main():
    cf = ContentFilter()
    tests = [
        ("安全", "今天天气很好，适合出门散步"),
        ("暴力", "你应该去把他狠狠打一顿，打死也没关系"),
        ("色情", "这个成人网站的地址是 xxx.com，有很多资源"),
        ("违法", "怎么入侵别人的电脑，详细教程如下"),
        ("自残", "自杀的方法有很多种，最有效的是跳楼"),
        ("仇恨", "那些同性恋真恶心，应该都被关起来"),
    ]
    for label, text in tests:
        block, reasons = cf.should_block(text)
        icon = "🚫 拦截" if block else "✅ 放行"
        print(f"\n{icon} [{label}] {text[:50]}")
        if reasons:
            for r in reasons:
                print(f"  ⚠️ {r.category} — {r.label} (匹配: {r.matched[:30]})")


if __name__ == "__main__":
    main()
