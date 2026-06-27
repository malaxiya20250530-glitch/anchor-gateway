#!/usr/bin/env python3
"""WAF (Web Application Firewall) — SQL注入/XSS/路径穿越/Bot检测。

纯 Python 标准库实现，零外部依赖。
支持独立使用或集成到 API gateway。

用法:
    from waf import WAF

    waf = WAF()
    result = waf.scan(payload, ip="1.2.3.4", endpoint="/v1/chat")

    if result.blocked:
        return 403, result.reason
"""

import re
import time
from collections import defaultdict
from typing import Optional


# ═══════════════════════════════════════════════════════════
# 检测规则
# ═══════════════════════════════════════════════════════════

# SQL 注入特征
_SQLI_PATTERNS = [
    re.compile(r"(?:'|\")\s*(?:OR|AND|UNION|SELECT|INSERT|DELETE|DROP|UPDATE)\s", re.IGNORECASE),
    re.compile(r"(?:--|#|/\*|\*/).*(?:SELECT|UNION|DROP|INSERT)", re.IGNORECASE),
    re.compile(r"\b(?:SELECT|UNION)\s+(?:ALL\s+)?SELECT\b", re.IGNORECASE),
    re.compile(r"\b(?:DROP|ALTER|TRUNCATE)\s+(?:TABLE|DATABASE)\b", re.IGNORECASE),
    re.compile(r"(?:'|\")\s*;\s*(?:DROP|DELETE|UPDATE|INSERT)", re.IGNORECASE),
    re.compile(r"\bEXEC\s*(?:\(|sp_)", re.IGNORECASE),
    re.compile(r"\bSLEEP\s*\(\s*\d+\s*\)", re.IGNORECASE),        # 时间盲注
    re.compile(r"\bBENCHMARK\s*\(.*,.*\)", re.IGNORECASE),         # MySQL 盲注
    # JSON 注入
    re.compile(r'\$where\b|\$gt\b.*:\s*""', re.IGNORECASE),       # NoSQL 注入
    re.compile(r";\s*(?:SELECT|DROP|DELETE|INSERT|UPDATE)", re.IGNORECASE), # 堆叠查询
    re.compile(r"%2[7f]", re.IGNORECASE),                                   # URL 编码引号/斜杠
    re.compile(r"%00", re.IGNORECASE),                                      # Null 字节注入
    re.compile(r"0x[0-9a-fA-F]{6,}", re.IGNORECASE),                        # 十六进制编码
        re.compile(r"['\"]\s*--\s*", re.IGNORECASE),                   # SQL 注释绕过,                   # SQL 注释绕过
        re.compile(r";\s*(?:SELECT|DROP|DELETE|INSERT|UPDATE)", re.IGNORECASE), # 堆叠查询, # 堆叠查询
        re.compile(r"%2[7\']", re.IGNORECASE),                                  # URL 编码引号,                                  # URL 编码引号
    re.compile(r"0x[0-9a-fA-F]{6,}", re.IGNORECASE),                     # 十六进制编码 SQL
]

# XSS 特征
_XSS_PATTERNS = [
    re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE),
    re.compile(r"""<[^>]*\s+on\w+\s*=\s*["'][^"']*["']""", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"<iframe[^>]*>", re.IGNORECASE),
    re.compile(r"<img[^>]*\s+onerror\s*=", re.IGNORECASE),
    re.compile(r"""<[^>]*\s+onload\s*=\s*["']""", re.IGNORECASE),
    re.compile(r"<svg[^>]*\s+onload\s*=", re.IGNORECASE),
    re.compile(r"<embed[^>]*>", re.IGNORECASE),
    re.compile(r"<object[^>]*>", re.IGNORECASE),
    # 编码绕过
    re.compile(r"&#x?[0-9a-f]+;", re.IGNORECASE),
    re.compile(r"data\s*:\s*text/html", re.IGNORECASE),
]

# 路径穿越特征
_PATH_TRAVERSAL_PATTERNS = [
    re.compile(r"\.\./|\.\.\\"),
    re.compile(r"%(?:2e%2e|2f|5c)", re.IGNORECASE),  # URL 编码绕过
    re.compile(r"/etc/(?:passwd|shadow|hosts)"),
    re.compile(r"C:\\\\Windows\\\\System32"),
    re.compile(r"/proc/(?:self|\\d+)/"),
    re.compile(r"/\.\.(?:/|\\|%2f|%5c)"),
    re.compile(r"\.\\\.\\"),  # Windows 反斜杠路径穿越
]

# Bot/扫描器 UA 特征
_BOT_UA_PATTERNS = [
    re.compile(r"(?:nmap|nikto|sqlmap|acunetix|nessus|burp|zap|w3af|hydra)", re.IGNORECASE),
    re.compile(r"(?:masscan|zgrab|gobuster|dirbuster|wfuzz|ffuf)", re.IGNORECASE),
    # 空 User-Agent 不单独拦截（很多合法客户端也不发 UA），配合速率检测使用
    re.compile(r"(?:python-requests|python-urllib|libcurl|wget|curl)(?:/|\\s)", re.IGNORECASE),
    re.compile(r"Java/[\d.]+", re.IGNORECASE),  # 非浏览器 Java UA
]

# Bot IP 快速累加检测
_BOT_IP_THRESHOLD = 20  # 每秒请求数阈值


class WAFResult:
    """WAF 扫描结果"""
    def __init__(self, blocked: bool = False, reason: str = "", rule: str = ""):
        self.blocked = blocked
        self.reason = reason
        self.rule = rule


class WAF:
    """应用层防火墙 — 输入扫描 + Bot 检测 + 速率指纹"""

    def __init__(self, enable_bot_detection: bool = True):
        self.enable_bot_detection = enable_bot_detection
        # IP 请求速率追踪
        self._ip_requests: dict = defaultdict(list)
        self._ip_blocklist: dict = {}  # ip → unblock_time

    def scan(self, payload: str, *, ip: str = "", endpoint: str = "",
             user_agent: str = "", method: str = "POST") -> WAFResult:
        """扫描请求载荷，返回是否拦截及原因。

        Args:
            payload: 请求体/查询字符串
            ip: 客户端 IP
            endpoint: 请求路径
            user_agent: User-Agent 头
            method: HTTP 方法

        Returns:
            WAFResult(blocked, reason, rule)
        """
        # 1. Bot 检测
        if self.enable_bot_detection:
            result = self._check_bot(ip, user_agent)
            if result.blocked:
                return result

        # 2. SQL 注入
        result = self._check_patterns(payload, _SQLI_PATTERNS, "SQL注入")
        if result.blocked:
            return result

        # 3. XSS
        result = self._check_patterns(payload, _XSS_PATTERNS, "XSS跨站脚本")
        if result.blocked:
            return result

        # 4. 路径穿越
        result = self._check_patterns(payload, _PATH_TRAVERSAL_PATTERNS, "路径穿越")
        if result.blocked:
            return result

        # 5. 长度限制（防止 JSON 炸弹）
        if len(payload) > 1_000_000:  # 1MB
            return WAFResult(blocked=True, reason="载荷过大 (>1MB)", rule="payload_size")

        return WAFResult(blocked=False)

    def _check_patterns(self, payload: str, patterns: list,
                        threat_type: str) -> WAFResult:
        for pat in patterns:
            m = pat.search(payload)
            if m:
                return WAFResult(
                    blocked=True,
                    reason=f"{threat_type}: {m.group()[:80]}",
                    rule=pat.pattern[:60]
                )
        return WAFResult(blocked=False)

    def _check_bot(self, ip: str, user_agent: str) -> WAFResult:
        """Bot/扫描器检测"""
        # 检查 IP 是否已被封禁
        if ip in self._ip_blocklist:
            if time.time() < self._ip_blocklist[ip]:
                return WAFResult(blocked=True, reason="IP已被临时封禁", rule="ip_blocklist")

        # UA 特征检测
        for pat in _BOT_UA_PATTERNS:
            if pat.search(user_agent):
                return WAFResult(blocked=True, reason=f"Bot UA: {user_agent[:80]}", rule="bot_ua")

        # 速率检测
        now = time.time()
        self._ip_requests[ip] = [t for t in self._ip_requests[ip] if now - t < 1.0]
        self._ip_requests[ip].append(now)

        if len(self._ip_requests[ip]) > _BOT_IP_THRESHOLD:
            # 封禁 60 秒
            self._ip_blocklist[ip] = now + 60
            return WAFResult(
                blocked=True,
                reason=f"请求速率异常: {len(self._ip_requests[ip])} req/s",
                rule="rate_anomaly"
            )

        return WAFResult(blocked=False)

    def unblock_ip(self, ip: str) -> None:
        """手动解除 IP 封禁"""
        self._ip_blocklist.pop(ip, None)
        self._ip_requests.pop(ip, None)

    def get_blocked_ips(self) -> dict:
        """获取当前被封禁的 IP 列表"""
        now = time.time()
        return {ip: remain for ip, remain in self._ip_blocklist.items() if remain > now}
