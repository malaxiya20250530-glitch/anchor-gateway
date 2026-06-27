#!/bin/bash
# 🚀 一键发布: PyPI + Docker Hub
# 用法: bash publish.sh
set -e

echo "============================================"
echo "  🚀 Anchor 发布脚本"
echo "============================================"

# ========== PyPI ==========
echo ""
echo "📦 [1/2] PyPI 发布..."

if [ ! -f "setup.py" ]; then
    echo "  ❌ setup.py 不存在"
    exit 1
fi

# 清理旧构建
rm -rf dist/ build/ *.egg-info/

python3 setup.py sdist bdist_wheel 2>/dev/null || python3 setup.py sdist

echo "  ✅ 构建完成:"
ls -lh dist/

echo ""
echo "  上传到 PyPI (需要 PyPI 账号):"
echo "    pip install twine"
echo "    twine upload dist/*"
echo ""
echo "  或上传到 Test PyPI (先测试):"
echo "    twine upload --repository testpypi dist/*"

# ========== Docker ==========
echo ""
echo "🐳 [2/2] Docker 发布..."

IMAGE_NAME="${DOCKER_USER:-你的DockerHub用户名}/hallucination-detector"
TAG="${1:-latest}"

docker build -t "$IMAGE_NAME:$TAG" . 2>/dev/null && \
  echo "  ✅ 镜像构建成功: $IMAGE_NAME:$TAG" || \
  echo "  ⚠️ Docker 未运行，跳过构建"

echo ""
echo "  推送到 Docker Hub:"
echo "    docker login"
echo "    docker push $IMAGE_NAME:$TAG"

# ========== 发布后验证 ==========
echo ""
echo "============================================"
echo "  ✅ 发布准备完成！"
echo ""
echo "  📋 后续步骤:"
echo "    1. twine upload dist/*          (PyPI)"
echo "    2. docker push $IMAGE_NAME      (Docker Hub)"
echo "    3. 在 GitHub Release 创建 v1.0.0"
echo "    4. 各大平台发帖推广"
echo "============================================"
