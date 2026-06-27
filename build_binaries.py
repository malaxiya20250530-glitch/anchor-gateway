#!/usr/bin/env python3
"""
跨平台 Cython 编译脚本 — 一键生成 .so / .pyd 二进制
用法:
    python3 build_binaries.py              # 编译当前平台
    python3 build_binaries.py --list       # 列出目标平台

支持平台:
    Linux   x86_64 / aarch64  → .cpython-XXX-linux-gnu.so
    macOS   x86_64 / arm64    → .cpython-XXX-darwin.so
    Android aarch64           → .cpython-XXX-linux-android.so
    Windows x86_64            → .cpython-XXX-win_amd64.pyd
"""

import os, sys, subprocess, shutil, platform

# Windows 控制台强制 UTF-8，避免 emoji 乱码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

# ============ 编译清单 ============
CYTHON_MODULES = [
    "hallucination_detector.py",
    "checker_classes.py",
    "checker_registry.py",
    "knowledge_graph.py",
    "logger.py",
    "observer_security.py",
    "alignment_middleware.py",
    "web_verifier.py",
    "vector_kb.py",
    "consensus_engine.py",
    "ml_consensus.py",
    "fuzzy_matcher.py",
    "billing.py",
    "rate_limiter.py",
    "security_logger.py",
    "waf.py",
    "circuit_breaker.py",
    "backpressure.py",
    "secrets_manager.py",
    "db_protection.py",
]

# ============ 平台检测 ============
def detect_platform():
    """返回 (os_tag, arch_tag, ext_suffix)"""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # 标准化架构名
    arch_map = {
        "x86_64": "x86_64", "amd64": "x86_64",
        "aarch64": "aarch64", "arm64": "arm64",
        "armv7l": "armv7l",
    }
    arch = arch_map.get(machine, machine)

    # 扩展名
    ext = sysconfig_get("EXT_SUFFIX") or (
        ".pyd" if system == "windows" else ".so"
    )

    return system, arch, ext


def sysconfig_get(key):
    try:
        import sysconfig
        return sysconfig.get_config_var(key)
    except Exception:
        return None


def get_ext_suffix_for(os_name, arch):
    """生成目标平台的标准扩展后缀"""
    py_ver = f"{sys.version_info.major}{sys.version_info.minor}"
    if os_name == "linux":
        return f".cpython-{py_ver}-{arch}-linux-gnu.so"
    elif os_name == "darwin":
        return f".cpython-{py_ver}-{arch}-darwin.so"
    elif os_name == "android":
        return f".cpython-{py_ver}-{arch}-linux-android.so"
    elif os_name == "windows":
        return f".cpython-{py_ver}-win_amd64.pyd"
    return f".cpython-{py_ver}-{os_name}-{arch}.so"


def compile_module(py_path, so_path):
    """Cython .py → .c → .so"""
    name = py_path.stem
    c_path = ROOT / f"{name}.c"

    # 步骤1: Cython → C
    r = subprocess.run(
        [shutil.which("cython") or "cython", "-3", str(py_path), "-o", str(c_path)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f"  [FAIL] cython 失败: {r.stderr.strip()[:150]}")
        return False

    # 步骤2: 编译参数
    inc = subprocess.run(
        ["python3-config", "--includes"], capture_output=True, text=True
    ).stdout.strip()

    ldflags = subprocess.run(
        ["python3-config", "--ldflags"], capture_output=True, text=True
    ).stdout.strip()

    cc = os.getenv("CC", "gcc")
    cflags = os.getenv("CFLAGS", "-shared -fPIC -O2")

    cmd = [cc] + cflags.split() + inc.split() + ldflags.split() + [
        "-o", str(so_path), str(c_path)
    ]

    r = subprocess.run(cmd, capture_output=True, text=True)
    c_path.unlink(missing_ok=True)

    if r.returncode != 0:
        print(f"  [FAIL] {cc} 失败: {r.stderr.strip()[:200]}")
        return False

    return True


def main():
    os_name, arch, ext = detect_platform()
    suffix = get_ext_suffix_for(os_name, arch)

    print("=" * 60)
    print(f"  [BUILD] Cython 二进制编译")
    print(f"  平台: {os_name} / {arch}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  后缀: {suffix}")
    print("=" * 60)

    # 检查 Cython
    try:
        subprocess.run(["cython", "--version"], capture_output=True)
    except FileNotFoundError:
        print("\n[FAIL] 未安装 Cython，请先运行: pip install cython")
        sys.exit(1)

    ok = 0
    for mod in CYTHON_MODULES:
        py_path = ROOT / mod
        if not py_path.exists():
            print(f"  [WARN]  {mod} 不存在，跳过")
            continue

        name = mod.replace(".py", "")
        so_path = ROOT / f"{name}{suffix}"

        print(f"[BUILD] {mod} → {so_path.name} ...", end=" ", flush=True)
        if compile_module(py_path, so_path):
            size_kb = so_path.stat().st_size / 1024
            print(f"[OK] {size_kb:.0f} KB")
            ok += 1

    print(f"\n{'=' * 60}")
    print(f"  [OK] 完成: {ok}/{len(CYTHON_MODULES)} 个模块")
    print(f"  输出目录: {ROOT}")

    if os_name == "darwin":
        print(f"\n  [TIP] macOS 提示:")
        print(f"     如需通用二进制 (x86_64 + arm64)，用 lipo 合并:")
        print(f"     lipo -create arm64.so x86_64.so -output universal.so")
    print("=" * 60)


if __name__ == "__main__":
    main()
