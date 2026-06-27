"""
统一哈希工具 — Content-Addressed ID
=====================================
类比 Git object hash: CID = sha256(meta + "\n" + text)

用法:
  from knowledge.hash_utils import cid, stable_hash
  
  cid("地球是圆的", meta="source=wikipedia")  # 全 hex
  stable_hash("地球是圆的")                   # 64位 int, 兼容旧接口
"""
import hashlib
import builtins

# ── Content-Addressed ID（推荐） ─────────────

def cid(text: str, meta: str = "") -> str:
    """
    Content-Addressed ID — 类似 Git object hash.
    
    cid = sha256(meta + "\n" + text)
    
    优点:
      - 可追溯: meta 参与哈希，不同来源的同文本有不同 ID
      - 去重天然稳定: 同文本+同meta → 同ID
      - 支持版本演化: 改 meta 即改 ID
    """
    payload = (meta + "\n" + text).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def cid_short(text: str, meta: str = "") -> str:
    """CID 前 16 字符（用于显示）"""
    return cid(text, meta)[:16]


# ── 64位整数哈希（兼容旧接口） ─────────────────

def stable_hash(text: str) -> int:
    """
    确定性 64 位整数哈希。
    = sha256(text) 截断 64 位。
    与 fact_store.db 兼容。
    如需带 meta，用 cid()。
    """
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16) & 0x7FFFFFFFFFFFFFFF


# ── 安全防护 ─────────────────────────────────

_original_hash = builtins.hash

def _forbidden_hash(*args, **kwargs):
    raise RuntimeError(
        "禁止 Python hash()！使用 cid() 或 stable_hash()。"
        "Python hash() 的 PYTHONHASHSEED 导致跨进程不一致。"
    )

# 生产环境取消注释:
# builtins.hash = _forbidden_hash
