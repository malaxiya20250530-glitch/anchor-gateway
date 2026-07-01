#!/usr/bin/env python3
"""
Anchor 网关 · 实时观察器仪表盘
================================
实时推送 + 动态指标卡 + 事件流 + 知识图谱健康

用法:
  python3 observer_dashboard.py --port 8080
  python3 observer_dashboard.py --port 8080 --gateway http://localhost:8800

浏览器打开 http://localhost:8080 即看到实时仪表盘
"""

import json
import os
import sys
import time
import threading
import argparse
import sqlite3
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from collections import deque
from urllib.request import Request, urlopen
from urllib.error import URLError

ROOT = Path(__file__).parent

# ── 全局状态 (线程安全) ──
state_lock = threading.Lock()
state = {
    "gateway": {
        "status": "unknown",
        "uptime": 0,
        "version": "?",
        "last_seen": 0,
    },
    "observer": {
        "segments_observed": 0,
        "interruptions": 0,
        "unique_flags": [],
        "sensitivity": 0.5,
        "fact_check_enabled": True,
    },
    "requests": {
        "total": 0,
        "contradicted": 0,
        "verified": 0,
        "uncertain": 0,
        "latency_avg": 0,
    },
    "events": deque(maxlen=200),
    "slo": {
        "uptime_percent": 100.0,
        "error_rate": 0.0,
        "p50_latency": 0,
        "p95_latency": 0,
    },
    "alerts": [],
    "checker_stats": {},
    "kb_stats": {"entries": 0, "domains": []},
    "system": {
        "cpu_percent": 0,
        "memory_percent": 0,
        "load_avg": (0, 0, 0),
    },
}

sse_clients = []  # list of queue.Queue
sse_lock = threading.Lock()


def add_event(event_type, data):
    """添加事件并广播给所有 SSE 客户端"""
    event = {
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
    }
    with state_lock:
        state["events"].append(event)
    # 广播
    with sse_lock:
        dead = []
        for q in sse_clients:
            try:
                q.put(event)
            except:
                dead.append(q)
        for q in dead:
            sse_clients.remove(q)


# ── 数据采集线程 ──
def poll_gateway(gateway_url, interval=2.0):
    """轮询网关各端点"""
    while True:
        try:
            # /health
            try:
                req = Request(f"{gateway_url}/health", headers={"User-Agent": "observer-dashboard/1.0"})
                resp = urlopen(req, timeout=3)
                health = json.loads(resp.read().decode())
                with state_lock:
                    state["gateway"].update({
                        "status": "online",
                        "uptime": health.get("uptime_seconds", 0),
                        "version": health.get("version", "?"),
                        "last_seen": time.time(),
                    })
                add_event("gateway_health", {"status": "online"})
            except URLError:
                with state_lock:
                    state["gateway"]["status"] = "offline"
                add_event("gateway_health", {"status": "offline"})

            # /metrics
            try:
                req = Request(f"{gateway_url}/metrics", headers={"User-Agent": "observer-dashboard/1.0"})
                resp = urlopen(req, timeout=3)
                observer_data = json.loads(resp.read().decode())
                with state_lock:
                    state["observer"].update(observer_data)
                add_event("observer_metrics", observer_data)
            except URLError:
                pass

            # /logs (仅取最新几条)
            try:
                req = Request(f"{gateway_url}/logs", headers={"User-Agent": "observer-dashboard/1.0"})
                resp = urlopen(req, timeout=3)
                logs_data = json.loads(resp.read().decode())
                total = logs_data.get("total", 0)
                with state_lock:
                    state["requests"]["total"] = total
                for log_entry in logs_data.get("logs", [])[-5:]:
                    add_event("request_log", log_entry)
            except URLError:
                pass

        except Exception as e:
            add_event("poll_error", {"error": str(e)})

        time.sleep(interval)


def poll_local_metrics(interval=5.0):
    """采集本地指标 (SQLite 反馈库、系统负载)"""
    while True:
        try:
            # SQLite 反馈库
            db_path = ROOT / "feedback.db"
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                cur = conn.execute(
                    "SELECT verdict, COUNT(*) as cnt FROM feedback GROUP BY verdict"
                )
                with state_lock:
                    for verdict, cnt in cur:
                        if verdict in state["requests"]:
                            state["requests"][verdict] = cnt
                cur = conn.execute("SELECT COUNT(*) FROM feedback")
                total = cur.fetchone()[0]
                with state_lock:
                    state["requests"]["total"] = max(state["requests"]["total"], total)

                # 延迟统计
                cur = conn.execute(
                    "SELECT AVG(latency_ms) FROM feedback WHERE latency_ms IS NOT NULL"
                )
                row = cur.fetchone()
                if row and row[0]:
                    with state_lock:
                        state["requests"]["latency_avg"] = round(row[0], 1)

                conn.close()

            # 知识库统计
            try:
                from hallucination_detector import KNOWLEDGE_BASE
                with state_lock:
                    state["kb_stats"]["entries"] = len(KNOWLEDGE_BASE)
            except ImportError:
                pass

            # 检查器统计
            try:
                from checker_registry import Checker
                import checker_classes
                with state_lock:
                    chk = {}
                    for name, cls in Checker.registry.items():
                        chk[name] = {
                            "weight": getattr(cls, "weight", 1.0),
                            "priority": getattr(cls, "priority", 0),
                        }
                    state["checker_stats"] = chk
            except ImportError:
                pass

            # 系统负载 (通过 /proc)
            try:
                with open("/proc/loadavg") as f:
                    parts = f.read().strip().split()
                    with state_lock:
                        state["system"]["load_avg"] = tuple(float(x) for x in parts[:3])
            except:
                pass

            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            total_mem = int(line.split()[1])
                        elif line.startswith("MemAvailable:"):
                            avail = int(line.split()[1])
                            with state_lock:
                                state["system"]["memory_percent"] = round(
                                    (1 - avail / total_mem) * 100, 1
                                )
                            break
            except:
                pass

        except Exception as e:
            add_event("local_metrics_error", {"error": str(e)})

        time.sleep(interval)


# ── SSE 推送线程 ──
def sse_broadcast():
    """从队列取事件并推给所有 SSE 客户端"""
    while True:
        time.sleep(0.1)
        with sse_lock:
            if not sse_clients:
                continue
        with state_lock:
            events_snapshot = list(state["events"])[-10:] if state["events"] else []
        if not events_snapshot:
            continue
        payload = json.dumps(events_snapshot, ensure_ascii=False, default=str)
        with sse_lock:
            dead = []
            for q in sse_clients:
                try:
                    q.put_nowait(payload)
                except:
                    dead.append(q)
            for q in dead:
                sse_clients.remove(q)


# ── 完整状态快照 ──
def full_snapshot():
    with state_lock:
        return {
            "gateway": dict(state["gateway"]),
            "observer": dict(state["observer"]),
            "requests": dict(state["requests"]),
            "slo": dict(state["slo"]),
            "events": list(state["events"])[-50:],
            "alerts": list(state["alerts"]),
            "checker_stats": dict(state["checker_stats"]),
            "kb_stats": dict(state["kb_stats"]),
            "system": dict(state["system"]),
        }


# ═══════════════════════════════════════════════════════════════
# 仪表盘 HTML (完全内嵌)
# ═══════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>👁️ Anchor 实时观察器仪表盘</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'SF Mono','Cascadia Code','JetBrains Mono',monospace;background:#0d1117;color:#c9d1d9;overflow-x:hidden}

/* ── 顶部状态栏 ── */
.topbar{display:flex;align-items:center;justify-content:space-between;padding:12px 20px;background:#161b22;border-bottom:1px solid #30363d;position:sticky;top:0;z-index:100}
.topbar h1{font-size:16px;font-weight:600;color:#f0f6fc}
.topbar h1 span{color:#58a6ff}
.gateway-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:500}
.gateway-badge.online{background:rgba(63,185,80,.15);color:#3fb950;border:1px solid rgba(63,185,80,.3)}
.gateway-badge.offline{background:rgba(248,81,73,.15);color:#f85149;border:1px solid rgba(248,81,73,.3)}
.gateway-badge.unknown{background:rgba(139,148,158,.15);color:#8b949e;border:1px solid rgba(139,148,158,.3)}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dot.online{background:#3fb950;box-shadow:0 0 6px rgba(63,185,80,.5)}
.dot.offline{background:#f85149;box-shadow:0 0 6px rgba(248,81,73,.5)}
.dot.unknown{background:#8b949e}

.topbar-right{display:flex;align-items:center;gap:16px;font-size:12px;color:#8b949e}
#updateTime{font-size:11px}

/* ── 指标网格 ── */
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;padding:16px 20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 16px;transition:border-color .15s}
.card:hover{border-color:#58a6ff}
.card .label{font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.card .value{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums}
.card .sub{font-size:11px;color:#8b949e;margin-top:4px}
.val-green{color:#3fb950}.val-red{color:#f85149}.val-yellow{color:#d2991d}.val-blue{color:#58a6ff}.val-white{color:#f0f6fc}
.minibar{display:flex;gap:4px;align-items:flex-end;height:32px;margin-top:8px}
.minibar div{width:6px;border-radius:2px;transition:height .3s;background:#58a6ff;opacity:.6}

/* ── 双栏主布局 ── */
.main-split{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:0 20px 20px}
.panel{background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}
.panel-header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#1c2333;border-bottom:1px solid #30363d;font-size:12px;font-weight:600;color:#8b949e}
.panel-body{padding:10px 14px;max-height:400px;overflow-y:auto}
.panel-body::-webkit-scrollbar{width:4px}
.panel-body::-webkit-scrollbar-track{background:transparent}
.panel-body::-webkit-scrollbar-thumb{background:#30363d;border-radius:2px}

/* ── 事件流 ── */
.event-entry{padding:6px 0;border-bottom:1px solid #21262d;font-size:12px;line-height:1.5;font-family:'SF Mono',monospace}
.event-entry:last-child{border-bottom:none}
.event-time{color:#484f58;margin-right:8px;font-size:11px}
.event-type{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;margin-right:6px}
.type-gateway_health{background:rgba(63,185,80,.15);color:#3fb950}
.type-observer_metrics{background:rgba(88,166,255,.15);color:#58a6ff}
.type-request_log{background:rgba(210,153,29,.15);color:#d2991d}
.type-poll_error{background:rgba(248,81,73,.15);color:#f85149}
.type-local_metrics_error{background:rgba(248,81,73,.15);color:#f85149}
.event-msg{color:#c9d1d9;word-break:break-all}

/* ── 日志表 ── */
.events-table{width:100%;border-collapse:collapse;font-size:11px}
.events-table th{text-align:left;padding:6px 8px;color:#8b949e;font-weight:500;border-bottom:1px solid #30363d;position:sticky;top:0;background:#1c2333}
.events-table td{padding:4px 8px;border-bottom:1px solid #21262d;font-family:'SF Mono',monospace;vertical-align:top}
.events-table tr:hover{background:rgba(88,166,255,.04)}
.verdict-badge{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600}
.verdict-badge.contradicted{background:rgba(248,81,73,.2);color:#f85149}
.verdict-badge.verified{background:rgba(63,185,80,.2);color:#3fb950}
.verdict-badge.uncertain{background:rgba(210,153,29,.2);color:#d2991d}

/* ── 检查器进度条 ── */
.checker-bar{margin:4px 0}
.checker-bar .row{display:flex;align-items:center;gap:8px;padding:2px 0}
.checker-bar .name{width:100px;font-size:11px;color:#8b949e;text-align:right}
.checker-bar .track{flex:1;height:6px;background:#21262d;border-radius:3px;overflow:hidden}
.checker-bar .fill{height:100%;border-radius:3px;transition:width .3s}
.checker-bar .weight{font-size:10px;color:#484f58;width:30px}

/* ── SLO 仪表 ── */
.slo-ring{display:inline-flex;align-items:center;gap:12px;margin:4px 0}
.slo-ring .ring{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700}

/* ── 响应式 ── */
@media(max-width:768px){
  .grid{grid-template-columns:repeat(2,1fr);padding:12px}
  .main-split{grid-template-columns:1fr;padding:0 12px 12px}
  .topbar{flex-wrap:wrap;gap:8px}
}

/* ── 闪烁动画 ── */
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.blink{animation:pulse 1.5s ease-in-out infinite}

/* ── 迷你火焰图 ── */
.flame-container{display:flex;flex-direction:column;gap:2px;margin-top:8px}
.flame-row{display:flex;gap:2px;height:14px}
.flame-block{border-radius:2px;min-width:4px;flex:1;transition:background .3s}
</style>
</head>
<body>

<div class="topbar">
  <div>
    <h1>👁️ <span>Anchor</span> 实时观察器</h1>
  </div>
  <div class="topbar-right">
    <span id="gatewayBadge" class="gateway-badge unknown">
      <span class="dot unknown"></span>
      <span>网关</span>
      <span id="gwStatus">未知</span>
    </span>
    <span id="updateTime">连接中...</span>
  </div>
</div>

<div class="grid" id="metricCards">
  <div class="card"><div class="label">已观察段数</div><div class="value val-blue" id="mSegments">0</div><div class="sub">累计分析</div></div>
  <div class="card"><div class="label">中断/标记</div><div class="value val-red" id="mInterruptions">0</div><div class="sub">触发觉察</div></div>
  <div class="card"><div class="label">请求总数</div><div class="value val-white" id="mTotal">0</div><div class="sub">含 SQLite</div></div>
  <div class="card"><div class="label">事实矛盾</div><div class="value val-red" id="mContradicted">0</div><div class="sub">需纠正</div></div>
  <div class="card"><div class="label">验证通过</div><div class="value val-green" id="mVerified">0</div><div class="sub">事实正确</div></div>
  <div class="card"><div class="label">不确定</div><div class="value val-yellow" id="mUncertain">0</div><div class="sub">待核查</div></div>
  <div class="card"><div class="label">平均延迟</div><div class="value val-blue" id="mLatency">0ms</div><div class="sub">网关响应</div></div>
  <div class="card"><div class="label">知识库条目</div><div class="value val-green" id="mKb">0</div><div class="sub">事实锚点</div></div>
  <div class="card"><div class="label">觉察灵敏度</div><div class="value val-yellow" id="mSens">0.5</div><div class="sub">当前阈值</div></div>
  <div class="card"><div class="label">系统负载</div><div class="value val-blue" id="mLoad">0.00</div><div class="sub">1min 平均</div></div>
</div>

<div class="main-split">
  <!-- 左: 实时事件流 -->
  <div class="panel">
    <div class="panel-header">
      <span>📡 实时事件流</span>
      <span id="eventCount" style="color:#484f58">0 条</span>
    </div>
    <div class="panel-body" id="eventStream"></div>
  </div>

  <!-- 右: 请求日志 -->
  <div class="panel">
    <div class="panel-header">
      <span>📋 请求日志</span>
      <span id="logCount" style="color:#484f58">0 条</span>
    </div>
    <div class="panel-body" id="logTableWrap">
      <table class="events-table">
        <thead><tr><th>时间</th><th>声明</th><th>判定</th><th>证据</th></tr></thead>
        <tbody id="logBody"></tbody>
      </table>
    </div>
  </div>
</div>

<div class="main-split" style="padding-top:0">
  <!-- 左: 检查器责任链 -->
  <div class="panel">
    <div class="panel-header">
      <span>⚖️ 检查器责任链</span>
      <span id="checkerCount" style="color:#484f58">0 个</span>
    </div>
    <div class="panel-body" id="checkerPanel"></div>
  </div>

  <!-- 右: SLO + 系统 -->
  <div class="panel">
    <div class="panel-header">
      <span>🎯 SLO 健康</span>
      <span>uptime · 延迟 · 错误率</span>
    </div>
    <div class="panel-body" id="sloPanel"></div>
  </div>
</div>

<script>
// ── SSE 连接 ──
const evtSource = new EventSource('/events');
const eventStream = document.getElementById('eventStream');
const logBody = document.getElementById('logBody');
const metricCards = {};

function init() {
  ['mSegments','mInterruptions','mTotal','mContradicted','mVerified','mUncertain','mLatency','mKb','mSens','mLoad'].forEach(id => {
    metricCards[id] = document.getElementById(id);
  });
  pollFull();
  setInterval(pollFull, 5000);
}
init();

evtSource.onmessage = (e) => {
  try {
    const events = JSON.parse(e.data);
    events.forEach(ev => {
      renderEvent(ev);
      if (ev.type === 'request_log' && ev.data) renderLogRow(ev.data);
    });
    document.getElementById('eventCount').textContent = eventStream.children.length + ' 条';
  } catch(_) {}
};

evtSource.onerror = () => {
  document.getElementById('updateTime').textContent = '⚠️ SSE 断开: ' + new Date().toLocaleTimeString();
};

// ── 完整状态轮询 ──
async function pollFull() {
  try {
    const res = await fetch('/api/snapshot');
    const d = await res.json();
    updateAll(d);
  } catch(_) {}
}

function updateAll(d) {
  const o = d.observer || {};
  const r = d.requests || {};
  const kb = d.kb_stats || {};
  const sys = d.system || {};
  const gw = d.gateway || {};

  // 指标卡
  metricCards.mSegments.textContent = (o.segments_observed || 0).toLocaleString();
  metricCards.mInterruptions.textContent = (o.interruptions || 0).toLocaleString();
  metricCards.mTotal.textContent = (r.total || 0).toLocaleString();
  metricCards.mContradicted.textContent = (r.contradicted || 0).toLocaleString();
  metricCards.mVerified.textContent = (r.verified || 0).toLocaleString();
  metricCards.mUncertain.textContent = (r.uncertain || 0).toLocaleString();
  metricCards.mLatency.textContent = (r.latency_avg || 0) + 'ms';
  metricCards.mKb.textContent = (kb.entries || 0).toLocaleString();
  metricCards.mSens.textContent = (o.sensitivity || 0.5).toFixed(2);
  metricCards.mLoad.textContent = (sys.load_avg || [0])[0].toFixed(2);

  // 网关状态
  const badge = document.getElementById('gatewayBadge');
  const dot = badge.querySelector('.dot');
  const txt = badge.querySelector('#gwStatus');
  const status = gw.status || 'unknown';
  badge.className = 'gateway-badge ' + status;
  dot.className = 'dot ' + status;
  txt.textContent = status === 'online' ? ('运行 ' + fmtUptime(gw.uptime || 0)) : (status === 'offline' ? '离线' : '未知');

  // 更新时间
  document.getElementById('updateTime').textContent = '更新: ' + new Date().toLocaleTimeString();

  // 检查器
  const chk = d.checker_stats || {};
  renderCheckers(chk);

  // SLO
  renderSLO(d);

  // 日志计数
  document.getElementById('logCount').textContent = logBody.children.length + ' 条';
}

function fmtUptime(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h + 'h ' + m + 'm';
}

// ── 事件渲染 ──
function renderEvent(ev) {
  const div = document.createElement('div');
  div.className = 'event-entry';
  const t = new Date((ev.timestamp || 0) * 1000);
  const ts = t.toLocaleTimeString();
  let msg = '';
  if (ev.type === 'gateway_health') msg = '网关状态: ' + (ev.data?.status || '?');
  else if (ev.type === 'observer_metrics') msg = '觉察指标更新: ' + JSON.stringify(ev.data).slice(0,60);
  else if (ev.type === 'request_log') msg = (ev.data?.claim || '').slice(0,80) + ' — ' + (ev.data?.verdict || '');
  else if (ev.type === 'poll_error') msg = '⚠️ ' + (ev.data?.error || '未知错误');
  else msg = JSON.stringify(ev.data).slice(0,80);
  div.innerHTML = '<span class="event-time">' + ts + '</span>'
    + '<span class="event-type type-' + ev.type + '">' + ev.type + '</span>'
    + '<span class="event-msg">' + escapeHtml(msg) + '</span>';
  eventStream.prepend(div);
  while (eventStream.children.length > 100) eventStream.removeChild(eventStream.lastChild);
}

function renderLogRow(data) {
  if (!data || !data.claim) return;
  const tr = document.createElement('tr');
  const t = new Date((data.timestamp || Date.now()/1000) * 1000);
  tr.innerHTML = '<td>' + t.toLocaleTimeString() + '</td>'
    + '<td>' + escapeHtml((data.claim || '').slice(0,50)) + '</td>'
    + '<td><span class="verdict-badge ' + (data.verdict || '') + '">' + (data.verdict || '?') + '</span></td>'
    + '<td>' + escapeHtml((data.evidence || '').slice(0,40)) + '</td>';
  logBody.prepend(tr);
  while (logBody.children.length > 50) logBody.removeChild(logBody.lastChild);
}

// ── 检查器渲染 ──
function renderCheckers(chk) {
  const panel = document.getElementById('checkerPanel');
  const names = Object.keys(chk);
  document.getElementById('checkerCount').textContent = names.length + ' 个';
  if (names.length === 0) {
    panel.innerHTML = '<div style="color:#484f58;font-size:12px;padding:8px">等待检查器数据...</div>';
    return;
  }
  const maxWeight = Math.max(...names.map(n => chk[n].weight || 1), 1);
  let html = '';
  names.sort((a, b) => (chk[b].priority || 0) - (chk[a].priority || 0));
  for (const name of names) {
    const w = chk[name].weight || 1;
    const pct = (w / maxWeight) * 100;
    const colors = ['#3fb950','#58a6ff','#d2991d','#f85149','#bc8cff','#f0883e'];
    const ci = names.indexOf(name) % colors.length;
    html += '<div class="checker-bar"><div class="row">'
      + '<span class="name">' + name + '</span>'
      + '<div class="track"><div class="fill" style="width:' + pct + '%;background:' + colors[ci] + '"></div></div>'
      + '<span class="weight">w=' + w.toFixed(1) + '</span>'
      + '</div></div>';
  }
  panel.innerHTML = html;
}

// ── SLO 渲染 ──
function renderSLO(d) {
  const panel = document.getElementById('sloPanel');
  const gw = d.gateway || {};
  const sys = d.system || {};
  const r = d.requests || {};
  const load = sys.load_avg || [0, 0, 0];
  const uptime = gw.uptime || 0;
  const mem = sys.memory_percent || 0;

  const uptimePct = uptime > 0 ? Math.min(100, (uptime / 86400) * 100) : 0;
  const errRate = r.total > 0 ? ((r.contradicted || 0) / r.total * 100) : 0;

  const ringColor = uptimePct > 99 ? '#3fb950' : uptimePct > 95 ? '#d2991d' : '#f85149';

  panel.innerHTML = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'
    + '<div><div class="slo-ring">'
    + '<div class="ring" style="border:3px solid ' + ringColor + ';color:' + ringColor + '">' + uptimePct.toFixed(1) + '%</div>'
    + '<div><div style="font-size:13px;font-weight:600">运行时间</div><div style="font-size:11px;color:#8b949e">' + fmtUptime(uptime) + '</div></div>'
    + '</div></div>'
    + '<div><div style="margin-bottom:8px"><div style="font-size:11px;color:#8b949e">错误率</div><div style="font-size:20px;font-weight:700;color:' + (errRate > 5 ? '#f85149' : '#3fb950') + '">' + errRate.toFixed(1) + '%</div></div></div>'
    + '<div><div style="font-size:11px;color:#8b949e">系统负载</div><div style="font-size:14px">' + load.map(x => x.toFixed(2)).join(' · ') + '</div><div style="font-size:10px;color:#484f58">1min · 5min · 15min</div></div>'
    + '<div><div style="font-size:11px;color:#8b949e">内存使用</div><div style="font-size:14px">' + mem + '%</div><div class="bar-bg" style="margin-top:4px"><div class="bar-fill" style="width:' + mem + '%;background:' + (mem > 80 ? '#f85149' : '#58a6ff') + ';height:6px;border-radius:3px"></div></div></div>'
    + '</div>';
}

function escapeHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
</script>
<style>
.bar-bg{background:#21262d;border-radius:3px;height:6px;overflow:hidden}
.bar-fill{height:100%;border-radius:3px;transition:width .3s}
</style>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
# HTTP 处理器
# ═══════════════════════════════════════════════════════════════

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/snapshot":
            self._json(full_snapshot())
        elif self.path == "/events":
            self._handle_sse()
        elif self.path == "/health":
            self._json({"status": "ok", "type": "observer-dashboard"})
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode("utf-8"))

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        import queue
        q = queue.Queue()
        with sse_lock:
            sse_clients.append(q)
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                    if isinstance(data, str):
                        # 批处理消息
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    else:
                        # 单事件
                        payload = json.dumps([data], ensure_ascii=False, default=str)
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # 心跳
                    self.wfile.write(": heartbeat\n\n".encode("utf-8"))
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with sse_lock:
                if q in sse_clients:
                    sse_clients.remove(q)

    def log_message(self, fmt, *args):
        if args and args[0] != "/events":
            print(f"  [{time.strftime('%H:%M:%S')}] {args[0]}")


def main():
    parser = argparse.ArgumentParser(description="Anchor 实时观察器仪表盘")
    parser.add_argument("--port", type=int, default=8080, help="仪表盘端口")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--gateway", default="http://localhost:8800", help="Anchor 网关地址")
    args = parser.parse_args()

    print(f"""
  👁️ Anchor 实时观察器仪表盘
  ═══════════════════════════
  仪表盘: http://localhost:{args.port}
  网关:   {args.gateway}
  SSE:    http://localhost:{args.port}/events
  API:    http://localhost:{args.port}/api/snapshot
    """)

    # 启动轮询线程
    gw_thread = threading.Thread(
        target=poll_gateway, args=(args.gateway,), daemon=True
    )
    gw_thread.start()

    local_thread = threading.Thread(
        target=poll_local_metrics, daemon=True
    )
    local_thread.start()

    sse_thread = threading.Thread(target=sse_broadcast, daemon=True)
    sse_thread.start()

    # 启动 HTTP
    server = HTTPServer((args.host, args.port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 关闭")
        server.shutdown()


if __name__ == "__main__":
    main()
