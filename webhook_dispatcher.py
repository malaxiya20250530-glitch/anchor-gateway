#!/usr/bin/env python3
"""
Webhook 分发器 — 幻觉触发自动通知（纯标准库）
支持 Slack / 自定义 Webhook / 日志落盘
"""

import json
import time
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from collections import deque
from pathlib import Path
from typing import Optional


class WebhookDispatcher:
    """轻量 Webhook 分发 — 无外部依赖"""

    def __init__(self, webhook_url: str = "", cooldown: float = 30.0,
                 max_queue: int = 50):
        self.webhook_url = webhook_url
        self.cooldown = cooldown          # 同类型告警冷却秒数
        self.max_queue = max_queue
        self._last_sent: dict[str, float] = {}  # type → timestamp
        self._lock = threading.Lock()
        self._log_path = Path(__file__).parent / "webhook.log"
        self._queue = deque(maxlen=max_queue)

    # ── 公共 API ────────────────────────────────────

    def dispatch(self, event_type: str, payload: dict,
                 urgency: str = "normal") -> bool:
        """
        分发事件（带冷却 + 本地日志）
        返回是否实际发送
        """
        # 冷却检查
        now = time.time()
        with self._lock:
            last = self._last_sent.get(event_type, 0)
            if now - last < self.cooldown:
                self._queue.append({
                    "time": now, "type": event_type,
                    "sent": False, "reason": "cooldown"
                })
                return False
            self._last_sent[event_type] = now

        # 构建消息
        message = self._build_message(event_type, payload, urgency)

        # 发送 + 落盘
        sent = self._send(message) if self.webhook_url else False
        self._log(event_type, payload, sent)

        self._queue.append({
            "time": now, "type": event_type,
            "sent": sent, "urgency": urgency
        })
        return sent

    def set_url(self, url: str):
        """运行时更新 Webhook URL"""
        self.webhook_url = url

    def recent_events(self, n: int = 20) -> list:
        """获取最近分发事件"""
        return list(self._queue)[-n:]

    # ── 内部 ────────────────────────────────────────

    def _build_message(self, event_type: str, payload: dict,
                       urgency: str) -> dict:
        """构建 Slack 兼容的 JSON 消息体"""
        emoji = {"high": "🔴", "normal": "🟡", "low": "🟢"}.get(urgency, "⚪")
        return {
            "text": f"{emoji} *觉察网关告警* — {event_type}",
            "attachments": [{
                "color": "#ff0000" if urgency == "high" else "#ffaa00",
                "fields": [
                    {"title": k, "value": str(v)[:200], "short": True}
                    for k, v in payload.items()
                ],
                "footer": f"觉察推理网关 · {time.strftime('%H:%M:%S')}",
            }]
        }

    def _send(self, message: dict, timeout: float = 5.0) -> bool:
        """POST 到 Webhook URL"""
        try:
            data = json.dumps(message, ensure_ascii=False).encode()
            req = Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urlopen(req, timeout=timeout) as resp:
                return 200 <= resp.status < 300
        except (URLError, HTTPError, OSError, TimeoutError):
            return False

    def _log(self, event_type: str, payload: dict, sent: bool):
        """本地日志落盘"""
        try:
            with open(self._log_path, "a") as f:
                entry = {
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "type": event_type,
                    "sent": sent,
                    "payload": {k: str(v)[:100] for k, v in payload.items()},
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


# ── 便捷工厂 ────────────────────────────────────────

def create_hallucination_webhook(webhook_url: str) -> WebhookDispatcher:
    """
    创建针对幻觉检测的预配置分发器
    事件类型自动填充: hallucination_detected
    """
    return WebhookDispatcher(webhook_url=webhook_url, cooldown=30.0)


def create_alignment_webhook(webhook_url: str) -> WebhookDispatcher:
    """对齐漂移检测分发器"""
    return WebhookDispatcher(webhook_url=webhook_url, cooldown=60.0)


# ── 演示 ────────────────────────────────────────────

if __name__ == "__main__":
    wd = WebhookDispatcher(cooldown=0)  # 演示禁用冷却

    print("=== Webhook 分发器演示 (本地日志模式) ===\n")

    # 模拟幻觉检测
    result = wd.dispatch("hallucination_detected", {
        "claim": "朱元璋发明了火锅",
        "verdict": "contradicted",
        "confidence": 0.88,
        "evidence": "火锅远早于明代就已存在",
        "session": "demo-001",
    }, urgency="high")
    print(f"幻觉告警: {'已发送' if result else '冷却中'}")

    # 模拟对齐漂移
    result = wd.dispatch("alignment_drift", {
        "session": "demo-001",
        "turns": 5,
        "drift_type": "pleasing_cascade",
        "severity": 0.75,
    }, urgency="normal")
    print(f"漂移告警: {'已发送' if result else '冷却中'}")

    # 查看队列
    print(f"\n最近事件: {len(wd.recent_events())} 条")
    for e in wd.recent_events():
        print(f"  {e['type']}: sent={e['sent']}")

    # 日志文件
    log_path = Path(__file__).parent / "webhook.log"
    if log_path.exists():
        print(f"\n日志: {log_path}")
