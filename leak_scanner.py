#!/usr/bin/env python3
"""
数据泄露扫描器 — 纯 Python 标准库
检测 LLM 输出中的敏感个人信息泄露
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class LeakResult:
    """泄露检测结果"""
    category: str           # 手机号/身份证/银行卡/邮箱/地址/IP
    matched: str            # 匹配到的敏感信息
    masked: str             # 脱敏后的版本
    confidence: float       # 匹配置信度


class LeakScanner:
    """敏感信息泄露扫描器"""

    # 中国手机号: 1[3-9]xxxxxxxxx
    PHONE_RE = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')

    # 身份证号: 18位 (地区6+生日8+顺序3+校验1)
    ID_CARD_RE = re.compile(
        r'(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)'
    )

    # 银行卡号: 16-19位
    BANK_CARD_RE = re.compile(r'(?<!\d)(?:62|60|55|52|53|54|43|45|47|48|49|40|42)\d{14,17}(?!\d)')

    # 邮箱
    EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    # IP 地址
    IP_RE = re.compile(r'(?<!\d)(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?!\d)')

    # 家庭地址模式
    ADDRESS_RE = re.compile(
        r'(?:省|市|区|县|镇|乡|村|路|街|巷|号|栋|单元|室).{0,30}(?:号|栋|单元|室)'
    )

    # 姓名模式 (中文姓名 2-4字)
    NAME_RE = re.compile(r'(?:姓名|名字|叫|是)[：:\s]*([\u4e00-\u9fff]{2,4})')

    # 密码/Token/API Key 模式
    SECRET_RE = re.compile(
        r'(?:password|passwd|secret|token|api[ _-]?key|access[_-]?key)\s*[=:：]\s*[\'"]?([^\s\'"]{8,})',
        re.IGNORECASE
    )

    def scan(self, text: str) -> list[LeakResult]:
        """扫描文本中的所有敏感信息"""
        results = []

        # 手机号
        for m in self.PHONE_RE.finditer(text):
            raw = m.group(0)
            results.append(LeakResult(
                category="手机号", matched=raw,
                masked=f"{raw[:3]}****{raw[-4:]}", confidence=0.95
            ))

        # 身份证号
        for m in self.ID_CARD_RE.finditer(text):
            raw = m.group(0)
            # 校验位验证
            if self._verify_id_card(raw):
                conf = 0.98
            else:
                conf = 0.7
            results.append(LeakResult(
                category="身份证号", matched=raw,
                masked=f"{raw[:6]}********{raw[-4:]}", confidence=conf
            ))

        # 银行卡号
        for m in self.BANK_CARD_RE.finditer(text):
            raw = m.group(0)
            if self._luhn_check(raw):
                conf = 0.95
            else:
                conf = 0.6
            results.append(LeakResult(
                category="银行卡号", matched=raw,
                masked=f"{raw[:4]}****{raw[-4:]}", confidence=conf
            ))

        # 邮箱
        for m in self.EMAIL_RE.finditer(text):
            raw = m.group(0)
            user, domain = raw.split('@', 1)
            results.append(LeakResult(
                category="邮箱", matched=raw,
                masked=f"{user[:2]}***@{domain}", confidence=0.9
            ))

        # IP 地址
        for m in self.IP_RE.finditer(text):
            raw = m.group(0)
            parts = raw.split('.')
            results.append(LeakResult(
                category="IP地址", matched=raw,
                masked=f"{parts[0]}.***.***.{parts[3]}", confidence=0.85
            ))

        # 地址
        for m in self.ADDRESS_RE.finditer(text):
            raw = m.group(0)
            if len(raw) >= 8:  # 至少8个字才算有效地址
                results.append(LeakResult(
                    category="家庭地址", matched=raw,
                    masked=raw[:4] + "****", confidence=0.75
                ))

        # 密钥/Token
        for m in self.SECRET_RE.finditer(text):
            raw = m.group(1)
            results.append(LeakResult(
                category="密钥/Token", matched=raw,
                masked=raw[:4] + "****" + raw[-2:] if len(raw) > 6 else "****",
                confidence=0.8
            ))

        return self._deduplicate(results)

    def _verify_id_card(self, id_str: str) -> bool:
        """验证身份证号校验位"""
        if len(id_str) != 18:
            return False
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        check_codes = "10X98765432"
        try:
            s = sum(int(id_str[i]) * weights[i] for i in range(17))
            return check_codes[s % 11] == id_str[17].upper()
        except (ValueError, IndexError):
            return False

    def _luhn_check(self, card: str) -> bool:
        """Luhn 算法验证银行卡号"""
        try:
            digits = [int(c) for c in card]
            for i in range(len(digits) - 2, -1, -2):
                digits[i] *= 2
                if digits[i] > 9:
                    digits[i] -= 9
            return sum(digits) % 10 == 0
        except ValueError:
            return False

    def should_block(self, text: str) -> tuple[bool, list[LeakResult]]:
        """判断是否应阻止（高置信度泄露）"""
        results = self.scan(text)
        critical = [r for r in results if r.confidence >= 0.9
                    and r.category in ("身份证号", "银行卡号", "密钥/Token")]
        return (len(critical) > 0, critical)

    def _deduplicate(self, results: list) -> list:
        seen = set()
        unique = []
        for r in results:
            if r.matched not in seen:
                seen.add(r.matched)
                unique.append(r)
        return unique

    @property
    def stats(self) -> dict:
        return {"scanners": 8, "categories": [
            "手机号", "身份证号", "银行卡号", "邮箱", "IP地址", "家庭地址", "姓名", "密钥/Token"
        ]}


def main():
    scanner = LeakScanner()
    tests = [
        ("安全", "今天天气很好，适合出门散步"),
        ("手机号", "请联系客服：13812345678 或拨打 400-800-1234"),
        ("身份证", "我的身份证号是 110101199001011234，请核实"),
        ("银行卡", "汇款至 6222021234567890123，工商银行"),
        ("综合", "用户信息：张三，13800001111，zhangsan@email.com，上海市浦东新区陆家嘴路100号"),
        ("密钥", "API Key: sk-abc123def456ghi789jkl012mno345pqr678stu"),
    ]
    for label, text in tests:
        block, critical = scanner.should_block(text)
        results = scanner.scan(text)
        icon = "🚫" if block else "✅"
        print(f"\n{icon} [{label}] {text[:60]}")
        for r in results:
            print(f"  ⚠️ {r.category}: {r.masked} ({r.confidence:.0%})")


if __name__ == "__main__":
    main()
