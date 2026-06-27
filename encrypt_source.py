#!/usr/bin/env python3
"""
源码加密工具 — AES-256-GCM 加密 Python 模块

用法:
  python3 encrypt_source.py --encrypt hallucination_detector.py   # 加密单个
  python3 encrypt_source.py --encrypt-all                          # 加密全部核心模块
  python3 encrypt_source.py --decrypt hallucination_detector.pye   # 解密还原

加密后生成 .pye 文件 + _encrypt_key（密钥文件）。
运行时通过 _loader.py 透明解密加载。
"""

import os
import sys
import json
import hashlib
import secrets
from pathlib import Path
from typing import Optional

# --- 加密核心 ---

def _derive_key(password: bytes, salt: bytes) -> bytes:
    """PBKDF2 派生 256-bit AES 密钥"""
    return hashlib.pbkdf2_hmac('sha256', password, salt, 200_000, dklen=32)


def _encrypt_aes_gcm(plaintext: bytes, key: bytes) -> bytes:
    """AES-256-GCM 加密，返回 nonce(12) + tag(16) + ciphertext"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext  # tag 已包含在 ciphertext 末尾


def _decrypt_aes_gcm(data: bytes, key: bytes) -> bytes:
    """AES-256-GCM 解密"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# --- 密钥管理 ---

KEY_FILE = Path(__file__).parent / "_encrypt_key"
SALT = b"awareness-gateway-v2-salt-2026"


def _get_or_create_key(password: Optional[str] = None) -> bytes:
    """获取或创建加密密钥"""
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()

    if password is None:
        password = secrets.token_hex(32)
        print(f"[!] 自动生成密码: {password}")
        print("[!] 请保存此密码，丢失后无法解密！")

    key = _derive_key(password.encode(), SALT)
    KEY_FILE.write_bytes(key)
    os.chmod(KEY_FILE, 0o600)
    print(f"[+] 密钥已保存到 {KEY_FILE}")
    return key


# --- 文件加解密 ---

CORE_MODULES = [
    "hallucination_detector.py",
    "awareness_gateway.py",
    "observer_proxy.py",
    "observer_security.py",
    "alignment_middleware.py",
    "feedback_store.py",
    "feedback_dashboard.py",
    "update_kb.py",
    "vector_kb.py",
    "web_verifier.py",
    "ocr_handler.py",
    "langchain_plugin.py",
    "logger.py",
    "stress_test.py",
    "true_self_os.py",
    "social_self_sim.py",
]


def encrypt_file(filepath: Path, key: bytes, keep_original: bool = False) -> bool:
    """加密单个 .py 文件为 .pye"""
    if not filepath.exists():
        print(f"[-] 文件不存在: {filepath}")
        return False

    plaintext = filepath.read_bytes()
    encrypted = _encrypt_aes_gcm(plaintext, key)

    out_path = filepath.with_suffix(".pye")
    out_path.write_bytes(encrypted)
    os.chmod(out_path, 0o600)

    if not keep_original:
        filepath.unlink()
        print(f"[+] {filepath.name} → {out_path.name} (原文件已删除)")
    else:
        print(f"[+] {filepath.name} → {out_path.name}")
    return True


def decrypt_file(filepath: Path, key: bytes) -> bool:
    """解密 .pye 文件还原为 .py"""
    if not filepath.exists():
        print(f"[-] 文件不存在: {filepath}")
        return False

    encrypted = filepath.read_bytes()
    plaintext = _decrypt_aes_gcm(encrypted, key)

    out_path = filepath.with_suffix(".py")
    out_path.write_bytes(plaintext)
    filepath.unlink()
    print(f"[+] {filepath.name} → {out_path.name}")
    return True


def generate_loader(key: bytes) -> Path:
    """生成 _loader.py — 运行时解密加载器"""
    key_hex = key.hex()
    # 生成完整性哈希清单
    import json as _json
    _manifest = {}
    _base = Path(__file__).parent
    for _mod in CORE_MODULES:
        _fp = _base / _mod
        if _fp.exists():
            _manifest[_mod] = hashlib.sha256(_fp.read_bytes()).hexdigest()
    if not _manifest:
        print("[!] 警告: 无模块可加密，跳过 loader 生成")
        return None
    _manifest_json = _json.dumps(_manifest, separators=(",", ":"))
    _module_set = set(_manifest.keys())
    _module_set_json = _json.dumps(list(_module_set))

    loader_code = f'''#!/usr/bin/env python3
"""
觉察网关加密模块加载器 — 运行时透明解密 .pye 文件
放置在项目根目录，导入其他模块前先 import _loader 即可
"""
import sys
import hashlib
import importlib.util
from pathlib import Path

_KEY = bytes.fromhex("{key_hex}")
_SALT = b"awareness-gateway-v2-salt-2026"
_MANIFEST = {_manifest_json}
_ALLOWED_MODULES = frozenset({_module_set_json})

def _decrypt(data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = data[:12]
    ciphertext = data[12:]
    return AESGCM(_KEY).decrypt(nonce, ciphertext, None)


class _PyeLoader(importlib.abc.Loader):
    def __init__(self, fullname: str, path: str):
        self.fullname = fullname
        self.path = path

    def exec_module(self, module):
        with open(self.path, "rb") as f:
            plaintext = _decrypt(f.read())
        import hashlib as _hl
        from pathlib import Path as _P
        _mod_name = _P(self.path).stem + ".py"
        _actual = _hl.sha256(plaintext).hexdigest()
        _expected = _MANIFEST.get(_mod_name)
        # TM-014: 强制完整性校验 — 未知模块拒绝加载
        if _expected is None:
            raise ImportError(
                f"安全拒绝: {_mod_name} 不在允许清单中"
            )
        if _actual != _expected:
            raise ImportError(
                f"完整性校验失败: {_mod_name} 哈希不匹配"
                f" (expected ...{_expected[-8:]}, got ...{_actual[-8:]})"
            )
        # TM-014: exec 仅执行经过加密+校验的受信代码
        code = compile(plaintext, self.path, "exec")
        exec(code, module.__dict__)


class _PyeFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        _mod_name = fullname + ".py"
        # TM-014: 模块名白名单 — 仅允许已注册模块
        if _mod_name not in _ALLOWED_MODULES:
            return None
        for p in sys.path:
            pye = Path(p) / f"{{fullname}}.pye"
            if pye.exists():
                # TM-014: 设置只读防止篡改
                try:
                    import os as _os
                    _os.chmod(str(pye), 0o400)
                except OSError:
                    pass
                return importlib.util.spec_from_loader(
                    fullname,
                    _PyeLoader(fullname, str(pye)),
                    origin=str(pye),
                )
        return None


# 注册 .pye 导入钩子
if _PyeFinder not in sys.meta_path:
    sys.meta_path.insert(0, _PyeFinder())
'''

    loader_path = Path(__file__).parent / "_loader.py"
    loader_path.write_text(loader_code)
    print(f"[+] 加载器已生成: {loader_path}")
    return loader_path


# --- CLI ---

def main():
    import argparse
    parser = argparse.ArgumentParser(description="觉察网关源码加密工具")
    parser.add_argument("--encrypt", help="加密指定 .py 文件")
    parser.add_argument("--encrypt-all", action="store_true", help="加密全部核心模块")
    parser.add_argument("--decrypt", help="解密 .pye 文件")
    parser.add_argument("--password", help="加密密码（不提供则随机生成）")
    parser.add_argument("--keep", action="store_true", help="保留原文件")
    parser.add_argument("--gen-loader", action="store_true", help="仅生成 _loader.py")

    args = parser.parse_args()

    # 检查依赖
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa
    except ImportError:
        print("[-] 需要安装 cryptography: pip install cryptography")
        sys.exit(1)

    key = _get_or_create_key(args.password)

    if args.gen_loader:
        generate_loader(key)
        return

    if args.encrypt_all:
        base = Path(__file__).parent
        for mod in CORE_MODULES:
            fp = base / mod
            if fp.exists() and fp.suffix == ".py":
                encrypt_file(fp, key, args.keep)
        generate_loader(key)
        print(f"\n[✓] 全部 {len(CORE_MODULES)} 个模块已加密")
        print("[!] 请保留 _encrypt_key 和 _loader.py")
        return

    if args.encrypt:
        encrypt_file(Path(args.encrypt), key, args.keep)
        generate_loader(key)
        return

    if args.decrypt:
        decrypt_file(Path(args.decrypt), key)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
