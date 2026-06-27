#!/usr/bin/env python3
"""
encrypt_stdlib.py — 纯标准库源码加密（零外部依赖）
使用 hashlib PBKDF2 + XOR 流密码，兼容 Termux 限制环境。

加密: python3 encrypt_stdlib.py
解密: python3 encrypt_stdlib.py --decrypt
"""

import os
import sys
import hashlib
import secrets
import struct
from pathlib import Path

ROOT = Path(__file__).parent
KEY_FILE = ROOT / ".encrypt_key"
SALT = b"anchor-truth-salt-2026-v2"
ITERATIONS = 300_000

# 需要加密的核心模块
ENCRYPT_TARGETS = [
    "hallucination_detector.py",
    "checker_classes.py",
    "checker_registry.py",
    "prompt_injection_defense.py",
    "meta_weight_learner.py",
    "consensus_voter.py",
    "knowledge_graph.py",
    "truth_graph.py",
    "trust_engine.py",
    "awareness_gateway.py",
    "entity_index.py",
    "query_orchestrator.py",
    "embedding_search.py",
    "fuzzy_matcher.py",
    "injection_hardener.py",
    "security_gateway.py",
    "security_hardener.py",
    "content_filter.py",
    "db_protection.py",
    "alignment_middleware.py",
    "true_self_os.py",
    "social_self_sim.py",
    "observability.py",
    "observability_platform.py",
    "circuit_breaker.py",
    "rate_limiter.py",
    "backpressure.py",
    "chaos_engineering.py",
    "regression_watchdog.py",
    "production_guard.py",
    "production_stability.py",
    "production_validator.py",
]


def derive_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 派生 256 位密钥"""
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS, dklen=32)


def encrypt_file(filepath: Path, key: bytes) -> Path:
    """加密单个 .py → .pye"""
    plaintext = filepath.read_bytes()
    # 生成随机 nonce
    nonce = secrets.token_bytes(16)
    # 生成 keystream: HMAC-SHA256(key, nonce + counter)
    keystream = b''
    counter = 0
    while len(keystream) < len(plaintext):
        keystream += hashlib.sha256(key + nonce + struct.pack('>I', counter)).digest()
        counter += 1
    # XOR 加密
    ciphertext = bytes(p ^ k for p, k in zip(plaintext, keystream[:len(plaintext)]))
    # 格式: nonce(16) + ciphertext
    out_path = filepath.with_suffix('.pye')
    out_path.write_bytes(nonce + ciphertext)
    return out_path


def decrypt_file(filepath: Path, key: bytes) -> Path:
    """解密 .pye → .py"""
    data = filepath.read_bytes()
    nonce = data[:16]
    ciphertext = data[16:]
    # 生成相同 keystream
    keystream = b''
    counter = 0
    while len(keystream) < len(ciphertext):
        keystream += hashlib.sha256(key + nonce + struct.pack('>I', counter)).digest()
        counter += 1
    # XOR 解密
    plaintext = bytes(c ^ k for c, k in zip(ciphertext, keystream[:len(ciphertext)]))
    out_path = filepath.with_suffix('.py')
    out_path.write_bytes(plaintext)
    return out_path


def main():
    decrypt_mode = "--decrypt" in sys.argv

    if decrypt_mode:
        # 解密模式
        if not KEY_FILE.exists():
            sys.exit("❌ 找不到密钥文件 .encrypt_key")
        password = KEY_FILE.read_text().strip()
        key = derive_key(password, SALT)
        count = 0
        for target in ENCRYPT_TARGETS:
            pye = ROOT / (target.replace('.py', '.pye'))
            if pye.exists():
                out = decrypt_file(pye, key)
                print(f"  🔓 {pye.name} → {out.name}")
                count += 1
        print(f"\n✅ 解密完成: {count} 个文件")
    else:
        # 加密模式
        # 生成随机密码
        password = secrets.token_hex(32)
        KEY_FILE.write_text(password)
        os.chmod(KEY_FILE, 0o600)
        print(f"🔑 密钥已保存到 {KEY_FILE}（权限 600）")

        key = derive_key(password, SALT)
        count = 0
        for target in ENCRYPT_TARGETS:
            src = ROOT / target
            if src.exists():
                out = encrypt_file(src, key)
                print(f"  🔒 {src.name} → {out.name}")
                count += 1
        print(f"\n✅ 加密完成: {count} 个文件")
        print(f"\n⚠️  重要:")
        print(f"   1. 密钥文件 .encrypt_key 已加入 .gitignore，不会推送到 GitHub")
        print(f"   2. 加密后的 .pye 文件可安全推送")
        print(f"   3. 原 .py 文件请勿提交（已在 .gitignore 中）")


if __name__ == "__main__":
    main()
