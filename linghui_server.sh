#!/data/data/com.termux/files/usr/bin/bash
# 灵绘 HTTP 服务启动脚本
PORT=${1:-8900}
DIR=/data/data/com.termux/files/home/docs/linghui

# 先杀旧进程
OLD=$(ps aux | grep "http.server $PORT" | grep -v grep | awk '{print $2}')
[ -n "$OLD" ] && kill $OLD 2>/dev/null && sleep 0.3

cd "$DIR"
setsid python3 -m http.server $PORT > /dev/null 2>&1 < /dev/null &
sleep 1
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:$PORT/
echo "灵绘服务已启动: http://127.0.0.1:$PORT/index.html"
