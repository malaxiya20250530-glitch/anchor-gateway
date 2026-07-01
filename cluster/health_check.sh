#!/bin/bash
# Anchor Gateway 健康检查 + 自动故障转移
# 检测两个隧道和各网关，自动恢复

GATEWAY1_PORT=8800
GATEWAY2_PORT=8801
NGINX_PORT=8080
TUNNEL1_LOG=$PREFIX/tmp/tunnel.log
TUNNEL2_LOG=$PREFIX/tmp/tunnel2.log
TUNNEL1_URL_FILE=$PREFIX/tmp/tunnel_url.txt
TUNNEL2_URL_FILE=$PREFIX/tmp/tunnel2_url.txt
STATUS_FILE=$PREFIX/tmp/cluster_status.txt

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

check() {
    local name="$1" cmd="$2"
    if eval "$cmd" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✅${NC} $name"
        return 0
    else
        echo -e "  ${RED}❌${NC} $name"
        return 1
    fi
}

echo "=== Anchor 集群健康检查 $(date '+%H:%M:%S') ==="
echo ""

G1_OK=0; G2_OK=0; T1_OK=0; T2_OK=0; NX_OK=0

# 1. 检查网关实例
check "Gateway-1    (端口 $GATEWAY1_PORT)" "curl -sf http://localhost:$GATEWAY1_PORT/health" && G1_OK=1
check "Gateway-2    (端口 $GATEWAY2_PORT)" "curl -sf http://localhost:$GATEWAY2_PORT/health" && G2_OK=1

# 2. 检查 Nginx
check "Nginx LB     (端口 $NGINX_PORT)" "curl -sf http://localhost:$NGINX_PORT/health" && NX_OK=1

# 3. 检查隧道
TUNNEL1_URL=$(cat "$TUNNEL1_URL_FILE" 2>/dev/null || echo "无")
TUNNEL2_URL=$(cat "$TUNNEL2_URL_FILE" 2>/dev/null || echo "无")
pgrep -f "ssh.*8800.*nokey@localhost.run" >/dev/null && T1_OK=1
pgrep -f "ssh.*8801.*nokey@localhost.run" >/dev/null && T2_OK=1
[ $T1_OK -eq 1 ] && echo -e "  ${GREEN}✅${NC} Tunnel-1    → $TUNNEL1_URL" || echo -e "  ${RED}❌${NC} Tunnel-1    (localhost.run:8800)"
[ $T2_OK -eq 1 ] && echo -e "  ${GREEN}✅${NC} Tunnel-2    → $TUNNEL2_URL" || echo -e "  ${RED}❌${NC} Tunnel-2    (localhost.run:8801)"

# 4. 外部可达性测试
echo ""
echo "--- 外部可达性 ---"
if [ -n "$TUNNEL1_URL" ] && [ "$TUNNEL1_URL" != "无" ]; then
    check "公网 Tunnel-1" "curl -sf --connect-timeout 10 $TUNNEL1_URL/health"
fi
if [ -n "$TUNNEL2_URL" ] && [ "$TUNNEL2_URL" != "无" ]; then
    check "公网 Tunnel-2" "curl -sf --connect-timeout 10 $TUNNEL2_URL/health"
fi
check "Render 主网关" "curl -sf --connect-timeout 10 https://anchor-gateway.onrender.com/health"

# 5. 自愈
echo ""
echo "--- 自愈 ---"
NEEDS_FIX=0

# 启动网关
if [ $G1_OK -eq 0 ]; then
    echo "  ↻ 重启 Gateway-1..."
    cd /data/data/com.termux/files/home/anchor-gateway
    setsid python3 awareness_gateway.py --port $GATEWAY1_PORT --mock > $PREFIX/tmp/gateway.log 2>&1 &
    NEEDS_FIX=1
fi
if [ $G2_OK -eq 0 ]; then
    echo "  ↻ 重启 Gateway-2..."
    cd /data/data/com.termux/files/home/anchor-gateway
    setsid python3 awareness_gateway.py --port $GATEWAY2_PORT --mock > $PREFIX/tmp/gateway2.log 2>&1 &
    NEEDS_FIX=1
fi

# 启动 Nginx
if [ $NX_OK -eq 0 ]; then
    echo "  ↻ 重启 Nginx..."
    nginx -s stop 2>/dev/null
    sleep 1
    nginx 2>/dev/null
    NEEDS_FIX=1
fi

# 重启隧道
if [ $T1_OK -eq 0 ]; then
    echo "  ↻ 重启 Tunnel-1 (localhost.run → 8800)..."
    setsid ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
      -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
      -o ConnectTimeout=30 -R 80:localhost:$GATEWAY1_PORT \
      nokey@localhost.run > "$TUNNEL1_LOG" 2>&1 &
    NEEDS_FIX=1
fi
if [ $T2_OK -eq 0 ]; then
    echo "  ↻ 重启 Tunnel-2 (localhost.run → 8801)..."
    setsid ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
      -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
      -o ConnectTimeout=30 -R 80:localhost:$GATEWAY2_PORT \
      nokey@localhost.run > "$TUNNEL2_LOG" 2>&1 &
    NEEDS_FIX=1
fi

# 保存状态快照
echo "G1=$G1_OK G2=$G2_OK T1=$T1_OK T2=$T2_OK NX=$NX_OK TS=$(date +%s)" > "$STATUS_FILE"

if [ $NEEDS_FIX -eq 1 ]; then
    echo ""
    echo -e "${YELLOW}⚠ 部分组件已自动修复${NC}"
else
    echo -e "${GREEN}✓ 所有组件健康${NC}"
fi
