#!/usr/bin/env bash
# ============================================================
# 🔒 质量门禁脚本（第13课 — 超级QA测试）
# 运行所有测试，任何失败均阻止合并/部署
# 用法: bash quality_gate.sh [--ci]
# ============================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color
PASS=0
FAIL=0
SKIP=0
CI_MODE=false

[[ "${1:-}" == "--ci" ]] && CI_MODE=true

HOME_DIR="/data/data/com.termux/files/home"
cd "$HOME_DIR"

log_pass() { echo -e "  ${GREEN}✓ PASS${NC} $1"; PASS=$((PASS+1)); }
log_fail() { echo -e "  ${RED}✗ FAIL${NC} $1"; FAIL=$((FAIL+1)); }
log_skip() { echo -e "  ${YELLOW}⊘ SKIP${NC} $1"; SKIP=$((SKIP+1)); }
log_section() { echo -e "\n${YELLOW}━━━ $1 ━━━${NC}"; }

# ============================================================
# 门禁 1: 语法检查
# ============================================================
log_section "门禁 1/5: Python 语法检查"

for pyfile in hallucination_detector.py checker_classes.py checker_registry.py \
              awareness_gateway.py codex_memory.py codex_mcp_memory.py; do
    if [ -f "$pyfile" ]; then
        if python3 -c "import py_compile; py_compile.compile('$pyfile', doraise=True)" 2>/dev/null; then
            log_pass "$pyfile 语法正确"
        else
            log_fail "$pyfile 语法错误"
        fi
    else
        log_skip "$pyfile 不存在"
    fi
done

# ============================================================
# 门禁 2: 幻觉检测器导入检查
# ============================================================
log_section "门禁 2/5: hallucination_detector 导入检查"

if python3 -c "import hallucination_detector; print('导入成功')" 2>&1; then
    log_pass "hallucination_detector 可正常导入"
else
    log_fail "hallucination_detector 导入失败"
fi

# ============================================================
# 门禁 3: 单元测试（5组核心测试）
# ============================================================
log_section "门禁 3/5: 事实检查器单元测试 (test_fact_checker.py)"

if python3 test_fact_checker.py 2>&1; then
    log_pass "test_fact_checker.py 全部通过"
else
    log_fail "test_fact_checker.py 有测试失败"
fi

# ============================================================
# 门禁 4: 扩展测试
# ============================================================
log_section "门禁 4/5: 扩展测试套件"

for testfile in test_graph_checker.py test_knowledge_graph.py \
                test_vector_kb.py test_feedback_store.py; do
    if [ -f "$testfile" ]; then
        if python3 "$testfile" 2>&1; then
            log_pass "$testfile 通过"
        else
            log_fail "$testfile 失败"
        fi
    else
        log_skip "$testfile 不存在"
    fi
done

# ============================================================
# 门禁 5: 代码规范扫描
# ============================================================
log_section "门禁 5/5: 代码规范扫描"

# 检查 bare except
BARES=$(grep -rn "except:" hallucination_detector.py checker_classes.py 2>/dev/null | grep -v "#noqa" || true)
if [ -z "$BARES" ]; then
    log_pass "无 bare except"
else
    log_fail "发现 bare except: $BARES"
fi

# 检查嵌套深度（缩进超过32空格≈8层）
DEEP=$(awk '/^                                /{found=1} END{print found+0}' hallucination_detector.py 2>/dev/null || echo 0)
if [ "$DEEP" -eq 0 ]; then
    log_pass "无超过8层嵌套"
else
    log_fail "可能存在超过8层嵌套"
fi

# ============================================================
# 汇总
# ============================================================
log_section "📊 质量门禁汇总"
echo -e "  ${GREEN}通过: $PASS${NC}"
echo -e "  ${RED}失败: $FAIL${NC}"
echo -e "  ${YELLOW}跳过: $SKIP${NC}"

if [ "$FAIL" -eq 0 ]; then
    echo -e "\n${GREEN}🎉 所有门禁通过！可以安全部署。${NC}"
    exit 0
else
    echo -e "\n${RED}🚨 $FAIL 项门禁失败，请修复后再部署。${NC}"
    exit 1
fi
