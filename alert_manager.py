#!/usr/bin/env python3
"""异常告警系统 — 阈值触发 + 多渠道通知。

支持渠道:
  - Telegram Bot
  - Discord Webhook
  - Email (SMTP)
  - stdout (fallback)

告警规则:
  - 5分钟内 429 > 100 → 触发
  - 5分钟内 500 > 20  → 触发
  - 5分钟内封禁 > 50 → 触发
  - WAF拦截率 > 10%   → 触发

用法:
    from alert_manager import AlertManager

    am = AlertManager(telegram_token="...", telegram_chat_id="...")
    am.record_status(429)          # 记录一次 429
    am.record_status(500)          # 记录一次 500
    am.record_block()              # 记录一次封禁
    am.check_and_alert()           # 检查阈值并告警
"""

import json
import os
import smtplib
import time
import urllib.request
from collections import defaultdict
from email.mime.text import MIMEText
from typing import Optional

from security_logger import get_security_logger


# ═══════════════════════════════════════════════════════════
# 告警规则
# ═══════════════════════════════════════════════════════════

_RULES = {
    "http_429":    {"window_sec": 300, "threshold": 100, "message": "5分钟内 429 错误超过 100 次"},
    "http_500":    {"window_sec": 300, "threshold": 20,  "message": "5分钟内 500 错误超过 20 次"},
    "blocked_ip":  {"window_sec": 300, "threshold": 50,  "message": "5分钟内 IP 封禁超过 50 次"},
    "waf_hit":     {"window_sec": 300, "threshold": 30,  "message": "5分钟内 WAF 拦截超过 30 次"},
}


class AlertManager:
    """多渠道告警管理器"""

    def __init__(self,
                 telegram_token: str = "",
                 telegram_chat_id: str = "",
                 discord_webhook: str = "",
                 smtp_host: str = "",
                 smtp_port: int = 587,
                 smtp_user: str = "",
                 smtp_pass: str = "",
                 alert_email: str = "",
                 cooldown_sec: int = 120):
        self.telegram_token = os.getenv("ALERT_TELEGRAM_TOKEN", telegram_token)
        self.telegram_chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID", telegram_chat_id)
        self.discord_webhook = os.getenv("ALERT_DISCORD_WEBHOOK", discord_webhook)
        self.smtp_host = os.getenv("ALERT_SMTP_HOST", smtp_host)
        self.smtp_port = int(os.getenv("ALERT_SMTP_PORT", str(smtp_port)))
        self.smtp_user = os.getenv("ALERT_SMTP_USER", smtp_user)
        self.smtp_pass = os.getenv("ALERT_SMTP_PASS", smtp_pass)
        self.alert_email = os.getenv("ALERT_EMAIL", alert_email)
        self.cooldown_sec = cooldown_sec

        # 计数器: rule_name → [(timestamp, count)]
        self._counters: dict = defaultdict(list)
        self._last_alert: dict = {}  # rule_name → last_alert_time

        self._slog = get_security_logger()

    # ── 记录 ────────────────────────────────────

    def record_status(self, status_code: int, ip: str = "") -> None:
        """记录一次 HTTP 状态码"""
        now = time.time()
        if status_code == 429:
            self._counters["http_429"].append((now, ip))
        elif status_code >= 500:
            self._counters["http_500"].append((now, ip))

    def record_block(self, ip: str = "") -> None:
        """记录一次 IP 封禁"""
        self._counters["blocked_ip"].append((time.time(), ip))

    def record_waf_hit(self, ip: str = "", rule: str = "") -> None:
        """记录一次 WAF 拦截"""
        self._counters["waf_hit"].append((time.time(), f"{ip}/{rule}"))

    # ── 检查与告警 ──────────────────────────────

    def check_and_alert(self) -> list[str]:
        """检查所有规则，触发告警。返回触发的规则列表。"""
        triggered = []
        now = time.time()

        for rule_name, rule in _RULES.items():
            window = rule["window_sec"]
            threshold = rule["threshold"]

            # 清理过期记录
            self._counters[rule_name] = [
                (t, d) for t, d in self._counters[rule_name]
                if now - t < window
            ]

            count = len(self._counters[rule_name])

            if count >= threshold:
                # 冷却检查
                last = self._last_alert.get(rule_name, 0)
                if now - last >= self.cooldown_sec:
                    self._last_alert[rule_name] = now
                    self._send_alert(rule_name, rule["message"], count)
                    triggered.append(rule_name)

        return triggered

    def _send_alert(self, rule_name: str, message: str, count: int) -> None:
        """发送告警到所有已配置渠道"""
        full_msg = f"🚨 [{rule_name}] {message}\n当前计数: {count}"

        # stdout (始终启用)
        self._slog.security_alert(
            ip="0.0.0.0", threat_type=rule_name,
            action="alert", detail=f"{message} (count={count})"
        )

        # Telegram
        if self.telegram_token and self.telegram_chat_id:
            try:
                self._send_telegram(full_msg)
            except Exception as e:
                self._slog.error(event="alert_fail", channel="telegram", message=str(e))

        # Discord
        if self.discord_webhook:
            try:
                self._send_discord(full_msg)
            except Exception as e:
                self._slog.error(event="alert_fail", channel="discord", message=str(e))

        # Email
        if self.smtp_host and self.alert_email:
            try:
                self._send_email(full_msg)
            except Exception as e:
                self._slog.error(event="alert_fail", channel="email", message=str(e))

    # ── 渠道实现 ────────────────────────────────

    def _send_telegram(self, message: str) -> None:
        """通过 Telegram Bot 发送消息"""
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        body = json.dumps({
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)

    def _send_discord(self, message: str) -> None:
        """通过 Discord Webhook 发送消息"""
        body = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            self.discord_webhook, data=body,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)

    def _send_email(self, message: str) -> None:
        """通过 SMTP 发送邮件"""
        msg = MIMEText(message, "plain", "utf-8")
        msg["Subject"] = f"[ALERT] Awareness Gateway 安全告警"
        msg["From"] = self.smtp_user
        msg["To"] = self.alert_email

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
            server.starttls()
            if self.smtp_user and self.smtp_pass:
                server.login(self.smtp_user, self.smtp_pass)
            server.send_message(msg)

    def get_stats(self) -> dict:
        """获取当前告警统计（供 dashboard 使用）"""
        now = time.time()
        stats = {}
        for rule_name in _RULES:
            stats[rule_name] = len([
                t for t, _ in self._counters.get(rule_name, [])
                if now - t < _RULES[rule_name]["window_sec"]
            ])
        return stats

    def reset(self) -> None:
        """重置所有计数器"""
        self._counters.clear()
        self._last_alert.clear()
