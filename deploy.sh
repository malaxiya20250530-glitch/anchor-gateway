#!/bin/bash
# ╔══════════════════════════════════════════╗
# ║  Anchor 事实锚定网关 — VPS 一键部署             ║
# ║  支持: Docker / 裸机 / systemd          ║
# ╚══════════════════════════════════════════╝
set -e

RED='\033[31m'; GREEN='\033[32m'; CYAN='\033[36m'
BOLD='\033[1m'; RESET='\033[0m'

MODE="${1:-docker}"
PORT="${PORT:-8800}"

banner() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════╗${RESET}"
    echo -e "${CYAN}║  Anchor 事实锚定网关 v2.3 — VPS 部署        ║${RESET}"
    echo -e "${CYAN}╚══════════════════════════════════════╝${RESET}"
    echo ""
}

check_prereq() {
    local cmd="$1" name="$2"
    if ! command -v "$cmd" &>/dev/null; then
        echo -e "${RED}✗ 缺少依赖: $name${RESET}"
        echo "  安装: apt install $name"
        return 1
    fi
    echo -e "  ${GREEN}✓${RESET} $name"
}

deploy_docker() {
    echo -e "${BOLD}模式: Docker Compose${RESET}"
    echo ""

    check_prereq docker "Docker" || return 1
    check_prereq docker-compose "docker-compose" || check_prereq "docker compose" "docker compose plugin" || return 1

    echo ""
    echo "构建镜像..."
    docker compose build --quiet

    echo ""
    echo "启动服务..."
    docker compose up -d

    sleep 3
    echo ""
    if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 部署成功${RESET}"
        echo ""
        echo "  服务:"
        echo "    网关:     http://localhost:8800"
        echo "    仪表盘:   http://localhost:8801"
        echo "    Prometheus: http://localhost:9091"
        echo "    Grafana:    http://localhost:3000 (admin/admin)"
    else
        echo -e "${RED}⚠ 健康检查未通过，查看日志: docker compose logs${RESET}"
    fi
}

deploy_baremetal() {
    echo -e "${BOLD}模式: 裸机部署${RESET}"
    echo ""

    check_prereq python3 "Python 3.10+" || return 1

    # 安装
    pip3 install --user -e . 2>/dev/null || true

    # 初始化
    rm -f feedback.db web_cache.db
    python3 -c "import feedback_store; feedback_store.init_db()"

    # 启动
    python3 awareness_gateway.py --port "$PORT" --mock &
    PID=$!
    sleep 2

    if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 已启动: http://localhost:$PORT${RESET}"
        echo "  PID: $PID"
    else
        echo -e "${RED}⚠ 启动失败${RESET}"
    fi
}

deploy_systemd() {
    echo -e "${BOLD}模式: systemd 服务${RESET}"
    echo ""

    local SERVICE_FILE="/etc/systemd/system/anchor-gateway.service"
    local WORKDIR="$(pwd)"
    local TMPFILE="$(mktemp /tmp/anchor-gateway.XXXXXX)"  # TM-023: 安全临时文件

    cat > "$TMPFILE" << EOF
[Unit]
Description=Anchor 事实锚定网关
After=network.target

[Service]
Type=simple
WorkingDirectory=$WORKDIR
ExecStart=/usr/bin/python3 $WORKDIR/awareness_gateway.py --port $PORT --mock
Restart=always
RestartSec=5
User=nobody
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    if [ "$(id -u)" -eq 0 ]; then
        cp "$TMPFILE" "$SERVICE_FILE" && rm -f "$TMPFILE"
        systemctl daemon-reload
        systemctl enable anchor-gateway
        systemctl start anchor-gateway
        sleep 2
        if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ systemd 服务已启动${RESET}"
            echo "  systemctl status anchor-gateway"
        fi
    else
        echo "需要 root 权限安装 systemd 服务"
        echo "已生成: $TMPFILE"
        echo "手动安装: sudo cp $TMPFILE $SERVICE_FILE"
    fi
}

# ── 入口 ──
banner

case "$MODE" in
    docker|d|compose|c)
        deploy_docker
        ;;
    bare|b|metal|m)
        deploy_baremetal
        ;;
    systemd|s|service)
        deploy_systemd
        ;;
    health|h)
        curl -s "http://localhost:$PORT/health" | python3 -m json.tool 2>/dev/null || echo "网关未运行"
        ;;
    stop)
        docker compose down 2>/dev/null || pkill -f awareness_gateway
        echo "已停止"
        ;;
    *)
        echo "用法: bash deploy.sh [模式]"
        echo ""
        echo "模式:"
        echo "  docker     Docker Compose 部署 (含监控栈)"
        echo "  bare       裸机 Python 直接运行"
        echo "  systemd    注册为系统服务 (需 root)"
        echo "  health     健康检查"
        echo "  stop       停止所有服务"
        ;;
esac
