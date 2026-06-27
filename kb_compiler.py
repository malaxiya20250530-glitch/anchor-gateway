#!/usr/bin/env python3
"""
知识库编译器 — JSON → 二进制索引，支持增量编译 + 校验 + CLI
纯标准库，零外部依赖。

用法:
  python3 kb_compiler.py compile          # 全量编译
  python3 kb_compiler.py compile --incr   # 增量编译
  python3 kb_compiler.py diff             # 显示变更条目
  python3 kb_compiler.py verify           # 校验索引完整性
  python3 kb_compiler.py watch            # 监控源文件自动重编译
"""

import json
import struct
import hashlib
import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

KB_DIR = Path(__file__).parent
JSON_PATH = KB_DIR / "kb_core.json"
IDX_PATH = KB_DIR / "kb_core.idx"
MANIFEST_PATH = KB_DIR / "kb_core.manifest"

# 二进制格式常量
MAGIC = b"KBID"
VERSION = 1


# ============================================================
# 核心编译引擎
# ============================================================

def _hash_entry(facts: list[str], source: str) -> str:
    """计算单条 KB 条目的 SHA256"""
    h = hashlib.sha256()
    for f in sorted(facts):
        h.update(f.encode("utf-8"))
    h.update(source.encode("utf-8"))
    return h.hexdigest()


def _hash_file(path: Path) -> str:
    """计算文件 SHA256"""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _hash_data(data: bytes) -> str:
    """计算数据 SHA256"""
    return hashlib.sha256(data).hexdigest()


def compile_full(kb: dict) -> tuple[bytes, dict]:
    """
    全量编译 — 构建二进制索引 + 清单。

    二进制格式:
        [4B magic] [2B version] [4B entry_count] [4B crc32]
        [entries...] 每个: [2B key_len][key][2B fact_count]
                        [2B fact_len][fact]* [2B src_len][src]

    返回: (index_bytes, manifest_dict)
    """
    buf = bytearray()
    buf.extend(MAGIC)                       # magic
    buf.extend(struct.pack("<H", VERSION))  # version
    buf.extend(struct.pack("<I", len(kb)))  # entry_count

    # 预留 crc32 占位
    crc_offset = len(buf)
    buf.extend(b"\x00\x00\x00\x00")

    manifest_entries = {}

    for key in sorted(kb.keys()):
        entry = kb[key]
        key_bytes = key.encode("utf-8")
        facts = entry.get("facts", [])
        source = entry.get("source", "")

        buf.extend(struct.pack("<H", len(key_bytes)))
        buf.extend(key_bytes)
        buf.extend(struct.pack("<H", len(facts)))

        for fact in facts:
            fact_bytes = fact.encode("utf-8")
            buf.extend(struct.pack("<H", len(fact_bytes)))
            buf.extend(fact_bytes)

        src_bytes = source.encode("utf-8")
        buf.extend(struct.pack("<H", len(src_bytes)))
        buf.extend(src_bytes)

        # 记录逐条 hash
        manifest_entries[key] = _hash_entry(facts, source)

    # 计算数据区 CRC32
    import zlib
    data_region = bytes(buf[crc_offset + 4:])
    crc = zlib.crc32(data_region) & 0xFFFFFFFF
    struct.pack_into("<I", buf, crc_offset, crc)

    index_bytes = bytes(buf)
    manifest = {
        "source_hash": _hash_file(JSON_PATH),
        "index_hash": _hash_data(index_bytes),
        "entry_count": len(kb),
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "entries": manifest_entries,
    }

    return index_bytes, manifest


def compile_incremental(kb: dict, old_manifest: dict) -> tuple[bytes, dict, dict]:
    """
    增量编译 — 只重建变更的条目。

    返回: (index_bytes, manifest, diff_report)
    """
    old_entries = old_manifest.get("entries", {})
    diff = {"added": [], "modified": [], "removed": [], "unchanged": 0}

    # 检测变更
    for key in kb:
        entry_hash = _hash_entry(kb[key].get("facts", []), kb[key].get("source", ""))
        if key not in old_entries:
            diff["added"].append(key)
        elif old_entries[key] != entry_hash:
            diff["modified"].append(key)
        else:
            diff["unchanged"] += 1

    for key in old_entries:
        if key not in kb:
            diff["removed"].append(key)

    total_changes = len(diff["added"]) + len(diff["modified"]) + len(diff["removed"])

    if total_changes == 0 and len(kb) == old_manifest.get("entry_count", 0):
        # 无变更，重用旧索引
        if IDX_PATH.exists():
            with open(IDX_PATH, "rb") as f:
                return f.read(), old_manifest, diff

    # 有变更 → 全量重建（简单可靠）
    index_bytes, manifest = compile_full(kb)
    return index_bytes, manifest, diff


def load_index_verified(path: Path = IDX_PATH) -> dict:
    """
    加载二进制索引并验证完整性。

    返回: kb_dict
    异常: ValueError 若校验失败
    """
    if not path.exists():
        raise FileNotFoundError(f"索引文件不存在: {path}")

    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 14:
        raise ValueError("索引文件损坏: 过短")

    # 验证 magic
    if data[:4] != MAGIC:
        raise ValueError(f"无效魔数: {data[:4]!r}, 期望 {MAGIC!r}")

    # 验证版本
    ver = struct.unpack_from("<H", data, 4)[0]
    if ver != VERSION:
        raise ValueError(f"索引版本不匹配: {ver}, 期望 {VERSION}")

    count = struct.unpack_from("<I", data, 6)[0]
    stored_crc = struct.unpack_from("<I", data, 10)[0]

    # 验证 CRC32
    import zlib
    actual_crc = zlib.crc32(data[14:]) & 0xFFFFFFFF
    if stored_crc != actual_crc:
        raise ValueError(f"CRC32 校验失败: 存储={stored_crc:08x}, 实际={actual_crc:08x}")

    # 解析条目
    offset = 14
    kb = {}
    for _ in range(count):
        key_len = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        key = data[offset:offset + key_len].decode("utf-8")
        offset += key_len

        fact_count = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        facts = []
        for _ in range(fact_count):
            fact_len = struct.unpack_from("<H", data, offset)[0]
            offset += 2
            fact = data[offset:offset + fact_len].decode("utf-8")
            offset += fact_len
            facts.append(fact)

        src_len = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        source = data[offset:offset + src_len].decode("utf-8") if src_len else ""
        offset += src_len

        kb[key] = {"facts": facts, "source": source}

    return kb


# ============================================================
# 清单管理
# ============================================================

def load_manifest() -> dict:
    """加载编译清单"""
    if not MANIFEST_PATH.exists():
        return {}
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def save_manifest(manifest: dict):
    """保存编译清单"""
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def is_stale() -> bool:
    """检查源文件是否比索引新"""
    if not IDX_PATH.exists():
        return True
    if not JSON_PATH.exists():
        return False
    manifest = load_manifest()
    if not manifest:
        return True
    current_hash = _hash_file(JSON_PATH)
    return current_hash != manifest.get("source_hash", "")


def save_index(index_bytes: bytes):
    """写入二进制索引"""
    with open(IDX_PATH, "wb") as f:
        f.write(index_bytes)


# ============================================================
# 加载入口（供外部使用）
# ============================================================

def get_kb() -> dict:
    """
    获取知识库 — 优先级: 二进制索引 > JSON 源

    自动检测索引是否过期，过期则回退到 JSON。
    """
    if IDX_PATH.exists() and not is_stale():
        try:
            return load_index_verified()
        except (ValueError, FileNotFoundError):
            pass

    # 回退到 JSON
    if JSON_PATH.exists():
        with open(JSON_PATH, encoding="utf-8") as f:
            return json.load(f)

    # 终极回退
    try:
        from hallucination_detector import KNOWLEDGE_BASE
        return KNOWLEDGE_BASE
    except ImportError:
        return {}


# ============================================================
# CLI
# ============================================================

def cmd_compile(incremental: bool = False):
    """编译命令"""
    if not JSON_PATH.exists():
        print("❌ kb_core.json 不存在")
        sys.exit(1)

    with open(JSON_PATH, encoding="utf-8") as f:
        kb = json.load(f)

    t0 = time.time()

    if incremental and MANIFEST_PATH.exists():
        old_manifest = load_manifest()
        index_bytes, manifest, diff = compile_incremental(kb, old_manifest)
    else:
        index_bytes, manifest = compile_full(kb)
        diff = {"added": list(kb.keys()), "modified": [], "removed": [], "unchanged": 0}

    save_index(index_bytes)
    save_manifest(manifest)

    elapsed = (time.time() - t0) * 1000

    # 统计
    total_changes = len(diff.get("added", [])) + len(diff.get("modified", [])) + len(diff.get("removed", []))
    mode = "增量" if incremental and MANIFEST_PATH.exists() else "全量"

    print(f"✅ {mode}编译完成 ({elapsed:.1f}ms)")
    print(f"   条目: {manifest['entry_count']}")
    print(f"   索引: {len(index_bytes)/1024:.1f}KB ({IDX_PATH})")
    if total_changes > 0:
        print(f"   变更: +{len(diff.get('added',[]))} ~{len(diff.get('modified',[]))} -{len(diff.get('removed',[]))}")


def cmd_diff():
    """差异命令 — 显示源码与索引的差异"""
    if not JSON_PATH.exists():
        print("❌ kb_core.json 不存在")
        return

    with open(JSON_PATH, encoding="utf-8") as f:
        kb = json.load(f)

    manifest = load_manifest()
    if not manifest:
        print("📝 清单不存在，需首次编译")
        return

    old_entries = manifest.get("entries", {})

    added, modified, removed = [], [], []
    for key in kb:
        h = _hash_entry(kb[key].get("facts", []), kb[key].get("source", ""))
        if key not in old_entries:
            added.append(key)
        elif old_entries[key] != h:
            modified.append(key)

    for key in old_entries:
        if key not in kb:
            removed.append(key)

    if not (added or modified or removed):
        print("✅ 源码与索引一致，无变更")
        return

    for key in added:
        print(f"  + {key}")
    for key in modified:
        print(f"  ~ {key}")
    for key in removed:
        print(f"  - {key}")
    print(f"\n共 {len(added)+len(modified)+len(removed)} 条变更")


def cmd_verify():
    """校验命令"""
    if not IDX_PATH.exists():
        print("❌ 索引文件不存在")
        sys.exit(1)

    try:
        kb = load_index_verified()
        print(f"✅ 索引有效 — {len(kb)} 条, {IDX_PATH.stat().st_size/1024:.1f}KB")

        # 与清单比对
        manifest = load_manifest()
        if manifest:
            if manifest.get("entry_count") == len(kb):
                print("✅ 与清单一致")
            else:
                print(f"⚠️  条目数不匹配: 清单={manifest.get('entry_count')}, 索引={len(kb)}")
    except (ValueError, FileNotFoundError) as e:
        print(f"❌ 校验失败: {e}")
        sys.exit(1)


def cmd_watch(interval: float = 2.0):
    """监控命令 — 轮询源文件变更自动重编译"""
    print(f"👁️  监控 {JSON_PATH.name} (间隔 {interval}s)...")
    last_hash = _hash_file(JSON_PATH) if JSON_PATH.exists() else ""

    try:
        while True:
            time.sleep(interval)
            current_hash = _hash_file(JSON_PATH)
            if current_hash and current_hash != last_hash:
                print(f"\n🔔 {time.strftime('%H:%M:%S')} 检测到变更，重新编译...")
                cmd_compile(incremental=True)
                last_hash = current_hash
    except KeyboardInterrupt:
        print("\n👋 停止监控")


def main():
    parser = argparse.ArgumentParser(description="知识库编译器 — JSON → 二进制索引")
    sub = parser.add_subparsers(dest="cmd", help="子命令")

    sub.add_parser("compile", help="编译索引").add_argument(
        "--incr", action="store_true", help="增量模式（只重建变更条目）")
    sub.add_parser("diff", help="显示源码与索引差异")
    sub.add_parser("verify", help="校验索引完整性")
    wp = sub.add_parser("watch", help="监控源文件自动重编译")
    wp.add_argument("--interval", "-i", type=float, default=2.0, help="轮询间隔(秒)")

    args = parser.parse_args()

    if args.cmd == "compile":
        cmd_compile(incremental=getattr(args, 'incr', False))
    elif args.cmd == "diff":
        cmd_diff()
    elif args.cmd == "verify":
        cmd_verify()
    elif args.cmd == "watch":
        cmd_watch(interval=getattr(args, 'interval', 2.0))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
