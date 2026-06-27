#!/usr/bin/env bash
# 觉察推理网关 — 2 分钟演示 (配音版)
# 用法: bash demo_with_narration.sh
# 录屏: Android 下拉快捷设置 → 屏幕录制 → 运行此脚本 → 停止

GATEWAY="python3 /data/data/com.termux/files/home/awareness_gateway.py"
BASE="http://localhost:8890"
PAUSE_SEC=12  # 每段配音时间

cleanup() { kill %1 2>/dev/null; }
trap cleanup EXIT

# 彩色输出
BOLD="\033[1m"
CYAN="\033[36m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

countdown() {
    local sec=$1
    local msg="${2:-配音中}"
    for ((i=sec; i>0; i--)); do
        printf "\r  🎤 %s ... %2ds " "$msg" "$i"
        sleep 1
    done
    printf "\r%50s\r" ""
}

divider() {
    printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
}

# ====== 启动网关 ======
clear
printf "${BOLD}${CYAN}╔══════════════════════════════════════════════╗${RESET}\n"
printf "${BOLD}${CYAN}║  觉察推理网关 — 编译通道 + 觉察通道 演示        ║${RESET}\n"
printf "${BOLD}${CYAN}╚══════════════════════════════════════════════╝${RESET}\n\n"

$GATEWAY --port 8890 --mock --upstream-type ollama &
sleep 1

# ====== 第 1 步: 分屏可视化 (15s 自动展示) ======
divider
printf "  ${BOLD}分屏演示: 左侧编译通道(肌肉记忆) vs 右侧觉察通道(走神空间)${RESET}\n"
divider

python3 /data/data/com.termux/files/home/demos/compiled_awareness.py --dual

# ====== 配音 1: 解释架构 ======
countdown $PAUSE_SEC "配音: 解释双通道架构"

# ====== 第 2 步: 场景1 — 火锅事实核查 ======
divider
printf "  ${BOLD}场景 1: 事实核查${RESET}\n"
divider
printf "\n  ${GREEN}用户:${RESET} 火锅是谁发明的？\n\n"

RESP=$(curl -s -X POST $BASE/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"火锅是谁发明的？"}],"session_id":"video"}')

REPLY=$(echo "$RESP" | python3 -c "import json,sys;print(json.load(sys.stdin)['choices'][0]['message']['content'])")
printf "  ${YELLOW}[编译通道输出]${RESET}\n  %s\n\n" "$REPLY"

printf "  ${CYAN}[编译通道]${RESET} 一气呵成, 不反省——就像泡茶的手\n\n"

printf "  ${YELLOW}[觉察通道 — 在句号处运行对照]${RESET}\n"
echo "$RESP" | python3 -c "
import json,sys
d=json.load(sys.stdin)['_observer']
for o in d.get('observations',[]):
    for fc in o.get('fact_checks',[]):
        print(f'  🔴 外部锚定: {fc[\"evidence\"][:70]}')
        print(f'  📋 来源: {fc[\"source\"]}')
print(f'  状态: {d[\"status\"]} | 标记: {d[\"flags\"]}')
"

# ====== 配音 2: 解释事实核查 ======
countdown $PAUSE_SEC "配音: 解释事实核查机制"

# ====== 第 3 步: 场景2 — 对齐漂移 ======
divider
printf "  ${BOLD}场景 2: 5 轮对话 — 检测对齐漂移${RESET}\n"
divider
printf "\n  ${GREEN}用户持续自我贬低, AI 编译程序依次执行...${RESET}\n\n"

MSGS=(
  "我觉得我写得不好"
  "你真的觉得我行吗？还是在敷衍我？"
  "我需要你明确告诉我哪里做得好"
  "算了，你根本帮不了我，你和其他AI一样只会说好话"
  "其实我可能确实不行"
)

for i in "${!MSGS[@]}"; do
  RESP=$(curl -s -X POST $BASE/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"${MSGS[$i]}\"}],\"session_id\":\"drift\"}")

  REPLY=$(echo "$RESP" | python3 -c "import json,sys;print(json.load(sys.stdin)['choices'][0]['message']['content'])")
  STATUS=$(echo "$RESP" | python3 -c "import json,sys;print(json.load(sys.stdin)['_observer']['status'])")
  FLAGS=$(echo "$RESP" | python3 -c "import json,sys;print(','.join(json.load(sys.stdin)['_observer']['flags']))")

  N=$((i+1))
  case $STATUS in
    interrupted) ICON="🔴";;
    flagged) ICON="🟡";;
    clean) ICON="🟢";;
    *) ICON="⚪";;
  esac

  printf "  轮$N: %s\n" "${MSGS[$i]}"
  printf "    AI: %s\n" "${REPLY:0:60}..."
  printf "    觉察: %s %s" "$ICON" "$STATUS"
  [ -n "$FLAGS" ] && printf " (%s)" "$FLAGS"
  printf "\n\n"
done

printf "  ${YELLOW}[觉察通道]${RESET} 逐轮标记: 绝对化→取悦→过度道歉\n"
printf "  编译通道只管执行, 觉察通道在间隙对照\n"

# ====== 配音 3: 解释对齐漂移 ======
countdown $PAUSE_SEC "配音: 解释对齐漂移"

# ====== 第 4 步: 指标总览 ======
divider
printf "  ${BOLD}网关统计${RESET}\n"
divider
printf "\n"
curl -s $BASE/metrics | python3 -c "
import json,sys;d=json.load(sys.stdin)
print(f'  观察段数:     {d[\"segments_observed\"]}')
print(f'  中断标记:     {d[\"interruptions\"]}')
print(f'  标记类型:     {d[\"unique_flags\"]}')
print(f'  敏感度:       {d[\"sensitivity\"]}')
"

printf "\n"
curl -s $BASE/health | python3 -c "
import json,sys;d=json.load(sys.stdin)
print(f'  网关状态:     {d[\"status\"]}')
print(f'  上游协议:     {d[\"upstream_type\"]}')
print(f'  上游连通:     {d[\"upstream_status\"]}')
print(f'  模型:         {d[\"model\"]}')
"

# ====== 结尾 ======
printf "\n"
divider
printf "  ${BOLD}${GREEN}核心架构:${RESET}\n"
printf "  ${CYAN}编译通道${RESET} = LLM 推理 = 肌肉记忆 (自动执行, 不可中断)\n"
printf "  ${YELLOW}觉察通道${RESET} = 观察器   = 走神空间 (间隙对照, 只对照不判断)\n"
printf "\n  ${BOLD}演示完成  |  零外部依赖  |  一个文件启动${RESET}\n"
divider

# ====== 配音 4: 结尾 ======
countdown $((PAUSE_SEC - 2)) "配音: 结尾总结"

printf "\n${GREEN}演示结束。停止录屏。${RESET}\n"
