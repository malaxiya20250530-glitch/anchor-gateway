#!/usr/bin/env python3
"""
安全加固模块 — 纯标准库，零外部依赖
提供 URL 校验、输入净化、配置权限检查等通用安全功能。
"""

import os
import re
import stat
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


# ============================================================
# URL Scheme 白名单
# ============================================================

ALLOWED_SCHEMES = {"https", "http"}  # http 仅允许 localhost

def validate_url(url: str, allow_localhost: bool = True) -> str:
    """
    校验 URL，只允许白名单 scheme。

    规则:
        - https:// → 始终允许
        - http://  → 仅允许 localhost/127.0.0.1 (Ollama 等本地服务)
        - file://   → 拒绝

    返回原 URL，无效则抛出 ValueError。
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if not scheme:
        raise ValueError(f"URL 缺少 scheme: {url}")

    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"不允许的 URL scheme: {scheme} (仅允许 {ALLOWED_SCHEMES})")

    if scheme == "http":
        hostname = (parsed.hostname or "").lower()
        if not allow_localhost or hostname not in ("localhost", "127.0.0.1", "::1", ""):
            raise ValueError(
                f"HTTP 仅允许 localhost，拒绝: {hostname}。"
                f"外部调用请使用 HTTPS。"
            )

    return url


# ============================================================
# 输入净化
# ============================================================

MAX_MESSAGE_LENGTH = 32_768   # 32KB
MAX_MESSAGES_PER_REQUEST = 50

def sanitize_input(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """
    净化用户输入: 截断超长内容，移除 null 字节。

    返回净化后的字符串。
    """
    if not isinstance(text, str):
        raise TypeError(f"输入必须是字符串，收到 {type(text).__name__}")

    # 移除 null 字节（可能用于绕过检查）
    text = text.replace("\x00", "")

    # 截断超长输入
    if len(text) > max_length:
        text = text[:max_length]

    return text


def validate_chat_request(body: dict) -> dict:
    """
    校验 Chat Completions 请求结构，返回净化后的 body。

    规则:
        - messages 必须是 list，最多 MAX_MESSAGES_PER_REQUEST 条
        - 每条 message 的 content 净化
        - model 字段存在性检查
    """
    if not isinstance(body, dict):
        raise ValueError("请求体必须是 JSON 对象")

    if "model" not in body:
        raise ValueError("缺少 model 字段")

    messages = body.get("messages", [])
    if not isinstance(messages, list):
        raise ValueError("messages 必须是数组")

    if len(messages) > MAX_MESSAGES_PER_REQUEST:
        raise ValueError(f"单次请求最多 {MAX_MESSAGES_PER_REQUEST} 条消息")

    # TM-020: role 白名单 — 防止 prompt injection 通过伪造 role
    _ALLOWED_ROLES = {"system", "user", "assistant", "tool", "function"}
    for msg in messages:
        if not isinstance(msg, dict):
            raise ValueError("每条消息必须是对象")
        role = msg.get("role", "")
        if role not in _ALLOWED_ROLES:
            raise ValueError(f"不允许的消息角色: {repr(role)}")
        content = msg.get("content", "")
        if isinstance(content, str):
            msg["content"] = sanitize_input(content)

    return body


# ============================================================
# 配置文件权限检查
# ============================================================

def check_config_permissions(config_path: Path) -> Optional[str]:
    """
    检查配置文件权限，防止 API key 泄露。

    Unix: 警告如果文件是 world-readable (0o644 或更宽松)。
    返回警告信息，安全则返回 None。
    """
    if not config_path.exists():
        return f"配置文件不存在: {config_path}"

    try:
        file_stat = config_path.stat()
        mode = file_stat.st_mode

        # Unix 权限检查
        if os.name == "posix":
            # 检查 group/other 是否有读权限
            if mode & stat.S_IROTH:
                return (
                    f"⚠️  {config_path} 对 other 可读 (权限 {oct(mode & 0o777)})！"
                    f"\n   该文件包含 API key，建议: chmod 600 {config_path}"
                )
            if mode & stat.S_IRGRP:
                return (
                    f"⚠️  {config_path} 对 group 可读 (权限 {oct(mode & 0o777)})"
                    f"\n   建议: chmod 600 {config_path}"
                )
    except OSError:
        return f"无法检查配置文件权限: {config_path}"

    return None


# ============================================================
# 日志脱敏
# ============================================================

_SENSITIVE_PATTERNS = [
    # JSON 字段值脱敏: "api_key": "xxx" → "api_key": "***"
    (re.compile(r'"(api_key|apikey|secret|password|token)"\s*:\s*"[^"]*"', re.I),
     r'"\1": "***"'),
    # 裸 token 脱敏
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), 'sk-***'),
    (re.compile(r'Bearer\s+[a-zA-Z0-9\-_\.]+'), 'Bearer ***'),
]


def sanitize_log(entry: dict) -> dict:
    """
    脱敏日志条目: 移除 API key / token 等敏感字段。

    返回脱敏后的 dict (新对象，不修改原对象)。
    """
    import json
    # 序列化 → 替换 → 反序列化
    raw = json.dumps(entry, ensure_ascii=False)
    for pattern, replacement in _SENSITIVE_PATTERNS:
        raw = pattern.sub(replacement, raw)
    return json.loads(raw)
