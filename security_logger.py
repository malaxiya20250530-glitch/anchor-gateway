#!/usr/bin/env python3
"""结构化安全日志 — JSON 格式输出，兼容 Loki / Elasticsearch / OpenSearch。

每条日志为一个 JSON 对象，包含:
  - ts: ISO 8601 时间戳
  - level: INFO/WARN/ERROR
  - event: 事件类型 (request/response/security/audit)
  - 请求上下文: ip, key_id, endpoint, method, status, latency_ms
  - token 统计: tokens_in, tokens_out
  - 安全字段: waf_hit, threat_type, action
  - 自定义字段: extra

用法:
    from security_logger import SecurityLogger
    slog = SecurityLogger()

    slog.request(ip="1.2.3.4", key_id="usr_381", endpoint="/v1/chat",
                 method="POST", status=200, latency_ms=1240,
                 tokens_in=3150, tokens_out=892)

    slog.security_alert(ip="5.6.7.8", threat_type="sql_injection",
                        action="blocked", detail="UNION SELECT detected")

日志输出:
    stdout → 实时控制台
    file → 持久化到 $HOME/security_audit.jsonl
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from secrets_manager import redact_dict


class SecurityLogger:
    """企业级结构化安全日志记录器"""

    def __init__(self, log_file: str = None, app_name: str = "awareness-gateway"):
        self.app_name = app_name
        self._hostname = os.uname().nodename if hasattr(os, 'uname') else "unknown"

        # 文件输出
        if log_file is None:
            log_file = str(Path.home() / "security_audit.jsonl")
        self._log_path = log_file
        self._file = None
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            self._file = open(log_file, "a")
        except OSError:
            pass

    def _emit(self, event: str, level: str = "INFO", **fields: Any) -> None:
        """发射一条结构化日志"""
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": level,
            "event": event,
            "app": self.app_name,
            "host": self._hostname,
            **fields,
        }

        # 脱敏
        record = redact_dict(record)

        line = json.dumps(record, ensure_ascii=False)

        # stdout
        print(line, file=sys.stderr, flush=True)

        # file
        if self._file:
            try:
                self._file.write(line + "\n")
                self._file.flush()
            except OSError:
                pass

    # ── 请求/响应日志 ──────────────────────────

    def request(self, *, ip: str, endpoint: str, method: str = "POST",
                key_id: str = "anonymous", status: int = 200,
                latency_ms: float = 0, tokens_in: int = 0, tokens_out: int = 0,
                user_agent: str = "", model: str = "", **extra) -> None:
        """记录 API 请求"""
        self._emit("request", level="INFO",
                   ip=ip, key_id=key_id, endpoint=endpoint, method=method,
                   status=status, latency_ms=round(latency_ms, 2),
                   tokens_in=tokens_in, tokens_out=tokens_out,
                   user_agent=user_agent, model=model, **extra)

    def response(self, *, ip: str, endpoint: str, status: int,
                 latency_ms: float, tokens_out: int = 0, **extra) -> None:
        """记录 API 响应"""
        level = "WARN" if status >= 400 else "INFO"
        self._emit("response", level=level,
                   ip=ip, endpoint=endpoint, status=status,
                   latency_ms=round(latency_ms, 2),
                   tokens_out=tokens_out, **extra)

    # ── 安全事件 ────────────────────────────────

    def security_alert(self, *, ip: str, threat_type: str,
                       action: str = "blocked", detail: str = "",
                       endpoint: str = "", **extra) -> None:
        """记录安全告警"""
        self._emit("security", level="WARN",
                   ip=ip, threat_type=threat_type, action=action,
                   detail=detail, endpoint=endpoint, **extra)

    def waf_hit(self, *, ip: str, rule: str, payload_snippet: str = "",
                endpoint: str = "", **extra) -> None:
        """WAF 拦截记录"""
        self._emit("waf", level="WARN",
                   ip=ip, rule=rule, payload_snippet=payload_snippet[:200],
                   endpoint=endpoint, action="blocked", **extra)

    def rate_limit(self, *, ip: str, endpoint: str, count: int,
                   limit: int, window_sec: int, **extra) -> None:
        """速率限制触发记录"""
        self._emit("rate_limit", level="WARN",
                   ip=ip, endpoint=endpoint, count=count, limit=limit,
                   window_sec=window_sec, action="throttled", **extra)

    # ── 审计 ───────────────────────────────────

    def audit(self, *, action: str, subject: str, detail: str = "",
              ip: str = "", **extra) -> None:
        """通用审计日志"""
        self._emit("audit", level="INFO",
                   action=action, subject=subject, detail=detail,
                   ip=ip, **extra)

    def error(self, *, event: str = "error", message: str = "",
              **extra) -> None:
        """错误日志"""
        self._emit(event, level="ERROR", message=message, **extra)

    def close(self) -> None:
        """关闭文件句柄"""
        if self._file:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None


# 模块级单例
_singleton: Optional[SecurityLogger] = None


def get_security_logger() -> SecurityLogger:
    """获取 SecurityLogger 单例"""
    global _singleton
    if _singleton is None:
        _singleton = SecurityLogger()
    return _singleton
