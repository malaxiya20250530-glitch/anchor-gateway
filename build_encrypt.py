#!/usr/bin/env python3
"""
源码加密构建脚本 — 混合方案
- 小模块: Cython → .so (最安全)
- 大模块: compileall → .pyc (字节码)
- 配置文件: 明文保留
用法: python3 build_encrypt.py
"""

import os, sys, shutil, subprocess, compileall, py_compile
from pathlib import Path

ROOT = Path(__file__).parent
BUILD = ROOT / "build"

# Cython 编译（小模块，<20KB）
CYTHON_MODS = [
    "logger.py", "update_kb.py", "feedback_store.py", "stress_test.py",
    "observer_proxy.py", "feedback_dashboard.py",
]

# compileall 编译（大模块）
PYC_MODS = [
    "hallucination_detector.py",
    "awareness_gateway.py",
    "observer_security.py",
    "alignment_middleware.py",
    "true_self_os.py",
    "social_self_sim.py",
]

KEEP_PLAIN = [
    "config.json", "kb_user.json", "demo_export.json",
    ".gitignore", "README.md", "Dockerfile", "docker-compose.yml",
]

def clean():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir()
    for d in ["demos", "scripts"]:
        (BUILD / d).mkdir(exist_ok=True)

def compile_cython(mod):
    """Cython → .so"""
    name = mod.replace(".py", "")
    py_file = ROOT / mod
    c_file = BUILD / f"{name}.c"
    so_file = BUILD / f"{name}.so"

    result = subprocess.run(
        ["cython", "-3", str(py_file), "-o", str(c_file)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False

    inc = subprocess.run(
        ["python3-config", "--includes"], capture_output=True, text=True
    ).stdout.strip()

    result = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O1"] + inc.split() +
        ["-o", str(so_file), str(c_file)],
        capture_output=True, text=True, cwd=str(BUILD),
    )
    c_file.unlink(missing_ok=True)
    return result.returncode == 0

def compile_pyc(mod):
    """compileall → .pyc 字节码"""
    name = mod.replace(".py", "")
    src = ROOT / mod
    dest = BUILD / f"{name}.pyc"
    py_compile.compile(str(src), cfile=str(dest), dfile=name, optimize=2)
    return dest.exists()

def copy_plain():
    for f in KEEP_PLAIN:
        src = ROOT / f
        if src.exists():
            shutil.copy2(src, BUILD / f)

def write_launcher():
    (BUILD / "run.py").write_text(f"""#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import awareness_gateway
awareness_gateway.main()
""")
    (BUILD / "run.py").chmod(0o755)

def copy_resources():
    for d in ["demos", "scripts"]:
        src_dir = ROOT / d
        if src_dir.exists():
            for f in src_dir.iterdir():
                shutil.copy2(f, BUILD / d / f.name)

def main():
    print("=" * 60)
    print("  源码加密构建 — Cython + compileall")
    print("=" * 60)
    clean()

    so_count = 0
    print("\n🔒 Cython → .so:")
    for m in CYTHON_MODS:
        ok = compile_cython(m)
        print(f"  {'✅' if ok else '❌'} {m}")
        if ok: so_count += 1

    pyc_count = 0
    print("\n📦 compileall → .pyc:")
    for m in PYC_MODS:
        ok = compile_pyc(m)
        print(f"  {'✅' if ok else '❌'} {m}")
        if ok: pyc_count += 1

    print("\n📄 配置:")
    copy_plain()
    for f in KEEP_PLAIN:
        if (ROOT / f).exists():
            print(f"  📄 {f}")

    write_launcher()
    copy_resources()

    so_size = sum(f.stat().st_size for f in BUILD.rglob("*.so"))
    pyc_size = sum(f.stat().st_size for f in BUILD.rglob("*.pyc"))
    print(f"\n{'=' * 60}")
    print(f"  ✅ .so: {so_count} 个 ({so_size/1024:.0f} KB)")
    print(f"  ✅ .pyc: {pyc_count} 个 ({pyc_size/1024:.0f} KB)")
    print(f"  启动: cd build && python3 run.py --mock")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()
