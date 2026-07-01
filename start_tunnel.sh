#!/data/data/com.termux/files/usr/bin/bash
# 启动SSH隧道到 localhost.run 并捕获URL
TUNNEL_LOG="$HOME/anchor-gateway/tunnel_output.log"
TARGET_PORT="${1:-8800}"

# 杀掉旧隧道
pkill -f "ssh.*nokey@localhost.run.*$TARGET_PORT" 2>/dev/null
sleep 1

# 启动新隧道
setsid ssh -o StrictHostKeyChecking=no \
           -o ServerAliveInterval=30 \
           -o ServerAliveCountMax=3 \
           -o ExitOnForwardFailure=yes \
           -o ConnectTimeout=30 \
           -R 80:localhost:"$TARGET_PORT" \
           nokey@localhost.run > "$TUNNEL_LOG" 2>&1 &

SSH_PID=$!
echo "SSH PID: $SSH_PID"
sleep 8

# 提取URL
TUNNEL_URL=$(grep -oP 'https://[a-z0-9]+\.lhr\.life' "$TUNNEL_LOG" | head -1)
echo "TUNNEL_URL=$TUNNEL_URL"

# 验证运行
if ps -p $SSH_PID > /dev/null 2>&1; then
    echo "STATUS=RUNNING"
    echo "$TUNNEL_URL" > "$HOME/anchor-gateway/current_tunnel_url.txt"
else
    echo "STATUS=DIED"
fi
