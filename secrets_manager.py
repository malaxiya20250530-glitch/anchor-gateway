#!/usr/bin/env python3
"""密钥管理器 — 集中式环境变量解析 + 敏感信息脱敏。

用法:
    from secrets_manager import resolve_config, redact

    cfg = resolve_config(load_json("config.json"))
    api_key = cfg["deepseek"]["api_key"]  # 已从 ${DEEPSEEK_API_KEY} 解析

    log.info("request", api_key=redact(api_key))  # sk-abc...xyz → sk-abc***xyz
"""

import os
import re
from pathlib import Path
from typing import Any


# ── 环境变量解析 ──────────────────────────────

_ENV_VAR_PAT = re.compile(r'\$\{([^}:]+)(?::-[^}]*)?\}')

def resolve_env(value: str) -> str:
    """解析字符串中的 ${VAR} 或 ${VAR:-default} 模式"""
    def _replace(m):
        var_name = m.group(1)
        full = m.group(0)
        # 检查是否有默认值: ${VAR:-default}
        if ':-' in full:
            default = full[full.index(':-')+2:-1]
            return os.getenv(var_name, default)
        val = os.getenv(var_name)
        if val is None:
            raise EnvironmentError(
                f"环境变量 {var_name} 未设置，且无默认值。"
                f"请设置: export {var_name}=your_value"
            )
        return val
    return _ENV_VAR_PAT.sub(_replace, value)


def resolve_config(cfg: Any) -> Any:
    """递归解析配置中所有的 ${ENV_VAR} 引用"""
    if isinstance(cfg, dict):
        return {k: resolve_config(v) for k, v in cfg.items()}
    elif isinstance(cfg, list):
        return [resolve_config(v) for v in cfg]
    elif isinstance(cfg, str):
        return resolve_env(cfg)
    return cfg


# ── 敏感信息脱敏 ──────────────────────────────

def redact(value: str, keep_prefix: int = 4, keep_suffix: int = 4) -> str:
    """脱敏字符串: sk-abc123xyz → sk-ab***xyz"""
    if not value or len(value) <= keep_prefix + keep_suffix:
        return "***"
    return value[:keep_prefix] + "***" + value[-keep_suffix:]


def redact_dict(d: dict, sensitive_keys: set = None) -> dict:
    """递归脱敏字典中的敏感字段"""
    if sensitive_keys is None:
        sensitive_keys = {"api_key", "secret", "password", "token", "authorization"}
    result = {}
    for k, v in d.items():
        if k.lower() in sensitive_keys or any(s in k.lower() for s in sensitive_keys):
            result[k] = redact(str(v)) if v else "***"
        elif isinstance(v, dict):
            result[k] = redact_dict(v, sensitive_keys)
        elif isinstance(v, list):
            result[k] = [
                redact_dict(item, sensitive_keys) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


# ── 配置加载入口 ──────────────────────────────

_config_cache = None

def load_config(reload: bool = False) -> dict:
    """加载 config.json 并解析环境变量（带缓存）"""
    global _config_cache
    if _config_cache is not None and not reload:
        return _config_cache
    config_path = Path(__file__).parent / "config.json"
    import json
    with open(config_path) as f:
        raw = json.load(f)
    _config_cache = resolve_config(raw)
    return _config_cache
