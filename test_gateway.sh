#!/bin/bash
cd ~
python3 -u awareness_gateway.py --port 8800 --mock &
PID=$!
sleep 2
curl -s http://127.0.0.1:8800/health
echo ""
echo "网关PID: $PID (30秒后自动关)"
sleep 28
kill $PID 2>/dev/null
echo "已关闭"
