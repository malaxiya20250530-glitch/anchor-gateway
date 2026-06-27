#!/usr/bin/env python3
"""
可视化后台 — 纯 Python HTTP Server + 内嵌 HTML
启动: python3 dashboard_server.py --port 8080
"""

import json
import os, time, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).parent

# ============ 内嵌 HTML 仪表盘 ============
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🔍 Anchor 仪表盘</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.header{background:linear-gradient(135deg,#1e3a5f,#0f172a);padding:2rem;text-align:center;border-bottom:2px solid #334155}
.header h1{font-size:1.8rem;background:linear-gradient(90deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem;padding:2rem;max-width:1400px;margin:0 auto}
.card{background:#1e293b;border-radius:12px;padding:1.5rem;border:1px solid #334155;transition:transform .2s}
.card:hover{transform:translateY(-2px);border-color:#60a5fa}
.card h3{font-size:1rem;color:#94a3b8;margin-bottom:.5rem;text-transform:uppercase;letter-spacing:1px}
.card .value{font-size:2.5rem;font-weight:700;background:linear-gradient(90deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card .sub{font-size:.8rem;color:#64748b;margin-top:.5rem}
.bar-container{margin-top:1rem}
.bar-label{display:flex;justify-content:space-between;font-size:.8rem;margin-bottom:.3rem}
.bar-bg{background:#334155;border-radius:6px;height:8px;overflow:hidden}
.bar-fill{height:100%;border-radius:6px;transition:width .5s}
.bar-fill.green{background:#22c55e}
.bar-fill.red{background:#ef4444}
.bar-fill.yellow{background:#f59e0b}
.bar-fill.blue{background:#3b82f6}
.table-wrap{background:#1e293b;border-radius:12px;padding:1.5rem;border:1px solid #334155;max-width:1400px;margin:0 auto 2rem}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{text-align:left;padding:.75rem;border-bottom:2px solid #334155;color:#94a3b8}
td{padding:.75rem;border-bottom:1px solid #1e293b}
tr:hover{background:rgba(96,165,250,.05)}
.badge{padding:2px 8px;border-radius:10px;font-size:.7rem;font-weight:600}
.badge.contradicted{background:rgba(239,68,68,.2);color:#ef4444}
.badge.verified{background:rgba(34,197,94,.2);color:#22c55e}
.badge.uncertain{background:rgba(245,158,11,.2);color:#f59e0b}
.refresh{position:fixed;bottom:1.5rem;right:1.5rem;background:#3b82f6;color:#fff;border:none;padding:.75rem 1.5rem;border-radius:8px;cursor:pointer;font-size:.9rem}
.refresh:hover{background:#2563eb}
</style>
</head>
<body>
<div class="header">
  <h1>🔍 Anchor 仪表盘</h1>
  <p style="color:#64748b;margin-top:.5rem" id="updateTime">---</p>
</div>
<div class="grid" id="cards"></div>
<div class="table-wrap">
  <h3 style="margin-bottom:1rem">📋 最近反馈</h3>
  <table><thead><tr><th>时间</th><th>声明</th><th>判定</th><th>证据</th><th>来源</th></tr></thead><tbody id="tbody"></tbody></table>
</div>
<button class="refresh" onclick="load()">🔄 刷新</button>
<script>
async function load() {
  const res = await fetch('/api/stats');
  const d = await res.json();
  document.getElementById('updateTime').textContent = '更新: ' + new Date().toLocaleTimeString();
  const cards = document.getElementById('cards');
  cards.innerHTML = `
    <div class="card"><h3>总检测次数</h3><div class="value">${d.total_checks}</div><div class="sub">累计调用</div></div>
    <div class="card"><h3>幻觉率</h3><div class="value">${(d.hallucination_rate*100).toFixed(1)}%</div><div class="sub">${d.contradicted} 条矛盾 / ${d.total_results} 条结果</div>
      <div class="bar-container">
        <div class="bar-bg"><div class="bar-fill red" style="width:${d.hallucination_rate*100}%"></div></div>
      </div>
    </div>
    <div class="card"><h3>验证率</h3><div class="value">${(d.verified_rate*100).toFixed(1)}%</div><div class="sub">${d.verified} 条验证通过</div>
      <div class="bar-container"><div class="bar-bg"><div class="bar-fill green" style="width:${d.verified_rate*100}%"></div></div></div>
    </div>
    <div class="card"><h3>知识库</h3><div class="value">${d.kb_entries}</div><div class="sub">${d.industry_kb_loaded ? '含医疗+法律' : '通用'}事实库</div></div>
    <div class="card"><h3>检查器</h3><div class="value">${d.checkers}</div><div class="sub">加权责任链</div></div>
    <div class="card"><h3>API 账户</h3><div class="value">${d.billing.total_accounts}</div><div class="sub">MRR ¥${d.billing.mrr_estimate}/月</div></div>
  `;
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = d.recent.map(r => `
    <tr>
      <td>${r.time||''}</td>
      <td>${(r.claim||'').slice(0,50)}</td>
      <td><span class="badge ${r.verdict}">${r.verdict}</span></td>
      <td>${(r.evidence||'').slice(0,40)}</td>
      <td>${r.source||''}</td>
    </tr>
  `).join('') || '<tr><td colspan="5" style="color:#64748b">暂无数据</td></tr>';
}
load();
setInterval(load, 10000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # TM-018: 管理端点认证
        admin_key = os.getenv("ADMIN_API_KEY", "")
        if admin_key:
            auth = self.headers.get("Authorization", "")
            if not (auth.startswith("Bearer ") and auth[7:] == admin_key):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error":"unauthorized"}')
                return
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/stats":
            self._serve_stats()
        elif self.path == "/health":
            self._json({"status": "ok"})
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode("utf-8"))

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8080")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def _serve_stats(self):
        stats = collect_stats()
        self._json(stats)

    def log_message(self, format, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}")


def collect_stats():
    """从各模块收集实时统计数据"""
    stats = {
        "total_checks": 0,
        "total_results": 0,
        "contradicted": 0,
        "verified": 0,
        "uncertain": 0,
        "hallucination_rate": 0.0,
        "verified_rate": 0.0,
        "kb_entries": 0,
        "industry_kb_loaded": False,
        "checkers": 0,
        "billing": {"total_accounts": 0, "mrr_estimate": 0},
        "recent": [],
    }

    # 检查器数量
    try:
        from checker_registry import Checker
        import checker_classes
        stats["checkers"] = len(Checker.registry)
    except Exception:
        pass

    # 知识库
    try:
        from hallucination_detector import KNOWLEDGE_BASE
        stats["kb_entries"] = len(KNOWLEDGE_BASE)
    except Exception:
        pass

    # 行业 KB
    try:
        from kb_loader import list_domains
        domains = list_domains()
        stats["industry_kb_loaded"] = bool(domains)
        stats["kb_domains"] = {d: info["entries"] for d, info in domains.items()}
    except Exception:
        pass

    # 计费
    try:
        from billing import BillingEngine
        engine = BillingEngine()
        stats["billing"] = engine.stats
    except Exception:
        pass

    # 反馈记录
    try:
        import sqlite3
        db = ROOT / "feedback.db"
        if db.exists():
            conn = sqlite3.connect(str(db))
            cur = conn.execute(
                "SELECT created_at, claim, verdict, evidence, source "
                "FROM feedback ORDER BY created_at DESC LIMIT 20"
            )
            for row in cur:
                stats["recent"].append({
                    "time": row[0], "claim": row[1],
                    "verdict": row[2], "evidence": row[3], "source": row[4]
                })
            # 统计
            cur = conn.execute("SELECT verdict, COUNT(*) FROM feedback GROUP BY verdict")
            for verdict, count in cur:
                if verdict in stats:
                    stats[verdict] = count
                stats["total_results"] += count
            if stats["total_results"] > 0:
                stats["hallucination_rate"] = stats["contradicted"] / stats["total_results"]
                stats["verified_rate"] = stats["verified"] / stats["total_results"]
            cur = conn.execute("SELECT COUNT(DISTINCT claim) FROM feedback")
            stats["total_checks"] = cur.fetchone()[0]
            conn.close()
    except Exception:
        pass

    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Anchor 仪表盘")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    # 预先加载行业知识库
    try:
        from kb_loader import load_industry_kb
        loaded, total = load_industry_kb()
        print(f"📚 行业知识库: {loaded}/{total} 条")
    except Exception:
        pass

    server = HTTPServer((args.host, args.port), DashboardHandler)
    print(f"📊 仪表盘: http://localhost:{args.port}")
    print(f"   API:   http://localhost:{args.port}/api/stats")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 关闭")


if __name__ == "__main__":
    main()
