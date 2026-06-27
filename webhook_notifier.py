#!/usr/bin/env python3
"""
Phase 2 Webhook 异步通知模块

当检测到高风险幻觉（可信度 < 20%）时，
异步推送结构化告警到配置的 Webhook 地址。
不阻塞主检测流程。

用法:
    from webhook_notifier import WebhookNotifier
    notifier = WebhookNotifier("https://hooks.example.com/alert")
    notifier.send_async(alert_data)

配置:
    config.json → webhook.url, webhook.threshold
"""

import json
import urllib.request
import threading
from typing import Optional


class WebhookNotifier:
    """异步 Webhook 推送 — 不阻塞主流程"""

    def __init__(self, url: str = None, threshold: float = 0.20):
        self.url = url
        self.threshold = threshold
        self.sent = 0
        self.failed = 0
        self._load_config()

    def _load_config(self):
        """从 config.json 加载 webhook 配置"""
        try:
            with open("config.json") as f:
                cfg = json.load(f)
            wh = cfg.get("webhook", {})
            if not self.url:
                self.url = wh.get("url", "")
            self.threshold = wh.get("threshold", self.threshold)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def should_alert(self, result: dict) -> bool:
        """判断是否需要发送告警"""
        confidence = result.get("confidence", 1.0)
        verdict = result.get("verdict", "")
        return verdict == "contradicted" and confidence > 0.7

    def build_payload(self, claim: str, result: dict, meta: dict = None) -> dict:
        """构建结构化告警数据包"""
        payload = {
            "type": "hallucination_alert",
            "timestamp": __import__('time').strftime("%Y-%m-%dT%H:%M:%SZ", __import__('time').gmtime()),
            "claim": claim[:200],
            "verdict": result.get("verdict", "uncertain"),
            "confidence": result.get("confidence", 0),
            "evidence": result.get("evidence", "")[:200],
            "source": result.get("source", ""),
            "error_category": result.get("error_category", "unknown"),
            "circuit": meta,
        }
        return payload

    def send_sync(self, payload: dict) -> bool:
        """同步发送（用于调试）"""
        if not self.url:
            return False
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    self.sent += 1
                    return True
        except Exception:
            self.failed += 1
        return False

    def send_async(self, payload: dict):
        """异步发送 — 不阻塞调用方"""
        t = threading.Thread(target=self.send_sync, args=(payload,), daemon=True)
        t.start()

    def stats(self) -> dict:
        return {"sent": self.sent, "failed": self.failed, "url": self.url[:50] if self.url else "(未配置)"}
