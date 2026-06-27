#!/bin/bash
# 跨平台二进制打包 — 在每台机器上运行 build_binaries.py 后执行此脚本
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
DIST="$ROOT/dist"

echo "📦 打包跨平台二进制..."
rm -rf "$DIST"
mkdir -p "$DIST"/{android-arm64,linux-x86_64,macos-arm64,macos-x86_64,windows-x86_64}

# 按后缀自动分类
for so in "$ROOT"/*.cpython*.so "$ROOT"/*.cpython*.pyd; do
    [ -f "$so" ] || continue
    name=$(basename "$so")
    case "$name" in
        *android*)     cp "$so" "$DIST/android-arm64/"    ; echo "  🤖 $name → android-arm64" ;;
        *linux-gnu*)   cp "$so" "$DIST/linux-x86_64/"    ; echo "  🐧 $name → linux-x86_64" ;;
        *darwin*arm*)  cp "$so" "$DIST/macos-arm64/"     ; echo "  🍎 $name → macos-arm64" ;;
        *darwin*)      cp "$so" "$DIST/macos-x86_64/"    ; echo "  🍏 $name → macos-x86_64" ;;
        *win*)         cp "$so" "$DIST/windows-x86_64/"  ; echo "  🪟 $name → windows-x86_64" ;;
    esac
done

# 复制运行时必需文件
cp "$ROOT"/build_binaries.py "$DIST/"
cp "$ROOT"/config.json "$DIST/" 2>/dev/null || echo "  ⚠️ config.json 未找到，部署时需手动提供"

echo ""
echo "✅ 打包完成: $DIST"
echo ""
echo "📋 部署步骤:"
echo "  1. 复制 dist/<平台>/*.so 到目标机器的项目目录"
echo "  2. 删除或重命名对应的 .py 源文件"
echo "  3. 运行: python3 -c 'import hallucination_detector' 验证"
echo ""
echo "🔄 在其他平台上编译:"
echo "  复制 build_binaries.py 到目标机器 → python3 build_binaries.py"
