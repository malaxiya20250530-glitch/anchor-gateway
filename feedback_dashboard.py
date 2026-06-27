#!/usr/bin/env python3
"""
feedback_dashboard.py — 自进化知识库仪表盘（纯标准库）
启动: python3 feedback_dashboard.py --port 8900
"""

import json
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

import feedback_store as fs
from logger import log

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>自进化知识库 — 反馈仪表盘</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,system-ui,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:16px 24px;position:sticky;top:0;z-index:10}
.header h1{font-size:20px;color:#58a6ff}
.stats{display:flex;gap:16px;margin-top:10px}
.stat{padding:4px 12px;border-radius:6px;font-size:13px}
.stat.pending{background:#d2992210;color:#d29922}
.stat.applied{background:#3fb95010;color:#3fb950}
.stat.rejected{background:#f8514910;color:#f85149}
.stat.total{background:#8b949e20;color:#8b949e}
.container{max-width:900px;margin:24px auto;padding:0 16px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:12px}
.card-header{display:flex;justify-content:space-between;align-items:start;margin-bottom:10px}
.verdict{font-size:12px;padding:2px 8px;border-radius:4px;font-weight:600}
.verdict.contradicted{background:#f8514920;color:#f85149}
.verdict.verified{background:#3fb95020;color:#3fb950}
.verdict.uncertain{background:#d2992220;color:#d29922}
.claim{font-size:16px;color:#f0f6fc;margin-bottom:8px}
.fact{font-size:13px;color:#8b949e;margin-bottom:8px}
.meta{font-size:12px;color:#484f58;display:flex;gap:12px}
.actions{margin-top:10px;display:flex;gap:8px}
.btn{padding:6px 14px;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-weight:500}
.btn-approve{background:#238636;color:#fff}
.btn-approve:hover{background:#2ea043}
.btn-reject{background:#da363320;color:#f85149;border:1px solid #f8514920}
.btn-reject:hover{background:#da363330}
.empty{text-align:center;padding:60px 20px;color:#484f58}
.empty h2{font-size:18px;margin-bottom:8px}
.refresh{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:6px 14px;border-radius:6px;cursor:pointer}
.page-nav{display:flex;gap:8px;justify-content:center;margin:20px 0}
.page-btn{background:#21262d;color:#58a6ff;border:1px solid #30363d;padding:6px 12px;border-radius:6px;cursor:pointer}
.page-btn.active{background:#1f6feb;color:#fff;border-color:#1f6feb}
.correction-input{width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;color:#c9d1d9;font-size:13px;margin-top:8px;display:none}
.correction-input.show{display:block}
.btn-rematch{background:#1f6feb20;color:#58a6ff;border:1px solid #1f6feb30}
.btn-rematch:hover{background:#1f6feb30}
.rematch-box{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px}
</style>
</head>
<body>
<div class="header">
  <h1>🧠 自进化知识库 — 反馈仪表盘</h1>
  <div class="stats">
    <span class="stat total">总计: {total}</span>
    <span class="stat pending">待复核: {pending}</span>
    <span class="stat applied">已应用: {applied}</span>
    <span class="stat rejected">已驳回: {rejected}</span>
  </div>
</div>
<div class="container">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
    <span style="font-size:14px;color:#8b949e">共 {pending} 条待复核记录</span>
    <button class="refresh" onclick="location.reload()">🔄 刷新</button>
  </div>
  {cards}
  {page_nav}
</div>
<script>
function approve(id){
  fetch('/api/approve',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:id,correction:''})
  }).then(r=>r.json()).then(d=>{if(d.ok)location.reload()})
}
function reject(id){
  fetch('/api/reject',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:id})
  }).then(r=>r.json()).then(d=>{if(d.ok)location.reload()})
}
function toggleRematch(id){
  var box=document.getElementById('rematch-'+id);
  box.style.display=box.style.display==='none'?'block':'none';
}
function rematch(id){
  var key=document.getElementById('kb-select-'+id).value;
  fetch('/api/rematch',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:id,rematch_key:key})
  }).then(r=>r.json()).then(d=>{if(d.ok)location.reload()})
}
</script>
</body>
</html>"""


def build_card(record: dict) -> str:
    vid = record["id"]
    v = record["verdict"]
    v_label = {"contradicted": "🔴 矛盾", "verified": "🟢 验证", "uncertain": "🟡 不确定"}.get(v, v)
    claim = record["claim"].replace("<", "&lt;").replace(">", "&gt;")
    fact = record["fact"].replace("<", "&lt;").replace(">", "&gt;")
    evidence = record.get("evidence", "")[:100]
    source = record.get("source", "")
    ts = record.get("created_at", 0)
    t_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts))) if ts else ""

    # 生成KB键下拉选项
    from hallucination_detector import KNOWLEDGE_BASE
    kb_opts = "".join(f'<option value="{k}">{k}</option>' for k in sorted(KNOWLEDGE_BASE.keys()))

    return f"""<div class="card">
  <div class="card-header">
    <span class="verdict {v}">{v_label}</span>
    <span style="font-size:11px;color:#484f58">置信度: {record['confidence']:.0%}</span>
  </div>
  <div class="claim">💬 {claim}</div>
  <div class="fact">📋 {fact}</div>
  <div class="meta">
    <span>📚 {source}</span>
    <span>🕐 {t_str}</span>
    <span>#{vid}</span>
  </div>
  <div class="actions">
    <button class="btn btn-approve" onclick="approve({vid})">✅ 确认无误</button>
    <button class="btn btn-reject" onclick="reject({vid})">❌ 驳回</button>
    <button class="btn btn-rematch" onclick="toggleRematch({vid})">🔧 重新匹配</button>
  </div>
  <div id="rematch-{vid}" class="rematch-box" style="display:none;margin-top:10px">
    <select id="kb-select-{vid}" style="background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:6px;width:100%;margin-bottom:6px">
      {kb_opts}
    </select>
    <button class="btn btn-approve" onclick="rematch({vid})">✅ 确认匹配</button>
    <button class="btn btn-reject" onclick="toggleRematch({vid})" style="margin-left:6px">取消</button>
  </div>
</div>"""



UNCERTAIN_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>不确定样本 · 主动学习</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:20px}
h1{color:#58a6ff;margin-bottom:8px}
.sub{color:#8b949e;font-size:14px;margin-bottom:20px}
.stats{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}
.stat{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px;min-width:100px}
.stat .num{font-size:24px;font-weight:bold;color:#58a6ff}
.stat .label{font-size:12px;color:#8b949e}
.sample{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:12px}
.sample .claim{font-size:15px;color:#e6edf3;margin-bottom:10px;word-break:break-all}
.sample .meta{font-size:12px;color:#8b949e;margin-bottom:12px}
.btn{display:inline-block;padding:6px 14px;border-radius:6px;border:1px solid #30363d;cursor:pointer;font-size:13px;margin-right:8px;background:#21262d;color:#c9d1d9}
.btn:hover{background:#30363d}
.btn-correct{color:#3fb950;border-color:#3fb950}
.btn-wrong{color:#f85149;border-color:#f85149}
.btn-ignore{color:#8b949e}
.btn:disabled{opacity:0.4;cursor:default}
.fact-input{display:none;margin-top:10px}
.fact-input textarea{width:100%;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:8px;font-size:13px;resize:vertical;min-height:60px}
.fact-input .btn-submit{margin-top:8px;background:#238636;color:#fff;border-color:#238636}
.toast{position:fixed;bottom:20px;right:20px;background:#238636;color:#fff;padding:12px 20px;border-radius:8px;display:none;z-index:999}
.nav{margin-bottom:20px}.nav a{color:#58a6ff;text-decoration:none;margin-right:16px}
.empty{text-align:center;padding:40px;color:#8b949e}
</style>
</head>
<body>
<h1>🔍 不确定样本池</h1>
<p class="sub">检测器无法确定的断言 — 你的标注会直接进化知识库</p>
<div class="nav"><a href="/feedback">← 反馈复核</a><a href="/uncertain">不确定样本</a></div>
<div class="stats" id="stats"></div>
<div id="samples"></div>
<div class="toast" id="toast"></div>
<script>
async function load(){let r=await fetch("/api/uncertain/list");let d=await r.json();
document.getElementById("stats").innerHTML=
  `<div class="stat"><div class="num">${d.total}</div><div class="label">总数</div></div>
   <div class="stat"><div class="num">${d.pending}</div><div class="label">待标注</div></div>
   <div class="stat"><div class="num">${d.labeled}</div><div class="label">已标注</div></div>`;
let h="";
if(!d.samples||d.samples.length===0)h='<div class="empty"><h2>🎉 没有待标注样本</h2><p>所有不确定样本已处理完毕</p></div>';
else for(let s of d.samples)h+=`<div class="sample" id="s-${s.id}">
  <div class="claim">💬 ${s.claim.replace(/</g,"&lt;")}</div>
  <div class="meta">置信度: ${(s.confidence*100).toFixed(0)}% | ${s.context||""} | ${s.created_at||""}</div>
  <button class="btn btn-correct" onclick="label(${s.id},'correct')">✅ 检测正确</button>
  <button class="btn btn-wrong" onclick="showFact(${s.id})">❌ 检测错误</button>
  <button class="btn btn-ignore" onclick="label(${s.id},'ignore')">⏭️ 忽略</button>
  <div class="fact-input" id="fact-${s.id}">
    <textarea id="ta-${s.id}" placeholder="请输入正确的事实..."></textarea>
    <button class="btn btn-submit" onclick="submitFact(${s.id})">✅ 提交并加入知识库</button>
  </div></div>`;
document.getElementById("samples").innerHTML=h}

function showFact(id){document.getElementById("fact-"+id).style.display="block"}
async function label(id,type){await fetch("/api/uncertain/label",{method:"POST",body:JSON.stringify({id,label:type})});toast("已标注");document.getElementById("s-"+id).remove()}
async function submitFact(id){let fact=document.getElementById("ta-"+id).value;if(!fact)return;await fetch("/api/uncertain/label",{method:"POST",body:JSON.stringify({id,label:"wrong",correct_fact:fact})});toast("已加入知识库 ✨");document.getElementById("s-"+id).remove()}
function toast(msg){let t=document.getElementById("toast");t.textContent=msg;t.style.display="block";setTimeout(()=>t.style.display="none",2000)}
load()
</script>
</body></html>"""

class FeedbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/feedback":
            self._serve_page()
        elif path == "/uncertain":
            self._html(UNCERTAIN_TEMPLATE)
        elif path == "/api/uncertain/list":
            self._serve_uncertain_list()
        elif path == "/api/stats":
            self._json(fs.get_stats())
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/approve":
            rid = body.get("id")
            if rid:
                # 写入反馈库
                fs.apply_correction(rid, body.get("correction", ""))
                # 同时写入用户知识库
                self._kb_apply(rid)
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "missing id"})
        elif path == "/api/reject":
            rid = body.get("id")
            if rid:
                fs.reject_record(rid)
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "missing id"})
        elif path == "/api/rematch":
            rid = body.get("id")
            rematch_key = body.get("rematch_key")
            if rid and rematch_key:
                fs.set_rematch(rid, rematch_key)
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "missing id or rematch_key"})
        elif path == "/api/uncertain/label":
            self._handle_uncertain_label(body)
        else:
            self.send_error(404)


    def _kb_apply(self, record_id: int) -> None:
        """将已确认记录写入 kb_user.json"""
        try:
            import json as _json
            import sqlite3 as _sqlite
            from hallucination_detector import KNOWLEDGE_BASE as _KB

            conn = _sqlite.connect(str(fs.DB_PATH))
            conn.row_factory = _sqlite.Row
            row = conn.execute("SELECT * FROM feedback WHERE id = ?", (record_id,)).fetchone()
            conn.close()
            if not row:
                return
            record = dict(row)
            claim = record["claim"]
            fact = record["fact"]
            verdict = record["verdict"]
            source = record.get("source", "反馈记录")

            # 从 claim 提取关键词作 KB 键
            words = [w for w in claim if '一' <= w <= '鿿' or w.isalpha()]
            # 简单启发式：取前几个汉字/字母
            import re
            matches = re.findall(r'[一-鿿A-Za-z]{2,}', claim)
            key = matches[0] if matches else claim[:6]

            if verdict == "contradicted":
                new_fact = f"{claim}与已知事实矛盾——{fact}"
            elif verdict == "verified":
                new_fact = f"{claim}——经核实：{fact}"
            else:
                new_fact = f"{claim}——相关：{fact}"

            # 读写 kb_user.json
            kb_path = fs.DB_PATH.parent / "kb_user.json"
            with open(kb_path) as f:
                user_kb = _json.load(f)
            if key not in user_kb:
                user_kb[key] = {"facts": [], "source": source}
            if new_fact not in user_kb[key]["facts"]:
                user_kb[key]["facts"].append(new_fact)
            # 去重：不在已有事实中
            if key in _KB:
                existing = set(_KB[key]["facts"])
                user_kb[key]["facts"] = [f for f in user_kb[key]["facts"] if f not in existing]
            with open(kb_path, "w") as f:
                _json.dump(user_kb, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("KB 写入失败: %s", e)
    def _serve_page(self):
        qs = parse_qs(urlparse(self.path).query)
        page = int(qs.get("page", [1])[0])
        per_page = 15
        records = fs.get_pending(page, per_page)
        total_pending = fs.get_pending_count()
        total_pages = max(1, (total_pending + per_page - 1) // per_page)
        stats = fs.get_stats()

        cards = "".join(build_card(r) for r in records) if records else \
            '<div class="empty"><h2>🎉 没有待复核记录</h2><p>所有反馈已处理完毕</p></div>'

        page_nav = ""
        if total_pages > 1:
            page_btns = []
            for p in range(1, total_pages + 1):
                cls = "page-btn active" if p == page else "page-btn"
                page_btns.append(f'<a class="{cls}" href="/feedback?page={p}">{p}</a>')
            page_nav = f'<div class="page-nav">{"".join(page_btns)}</div>'

        html = (TEMPLATE
            .replace("{total}", str(stats["total"]))
            .replace("{pending}", str(stats["pending"]))
            .replace("{applied}", str(stats["applied"]))
            .replace("{rejected}", str(stats["rejected"]))
            .replace("{cards}", cards)
            .replace("{page_nav}", page_nav))
        self._html(html)

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # 静默日志



    def _serve_uncertain_list(self):
        """返回未处理的不确定样本列表"""
        import sqlite3, time
        conn = sqlite3.connect(str(fs.DB_PATH))
        conn.row_factory = sqlite3.Row
        samples = conn.execute(
            "SELECT id, claim, verdict, confidence, context, created_at, processed FROM uncertain_samples WHERE processed=0 ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as cnt FROM uncertain_samples").fetchone()["cnt"]
        pending = conn.execute("SELECT COUNT(*) as cnt FROM uncertain_samples WHERE processed=0").fetchone()["cnt"]
        labeled = total - pending
        conn.close()
        result = {
            "total": total,
            "pending": pending,
            "labeled": labeled,
            "samples": [{
                "id": s["id"],
                "claim": s["claim"],
                "verdict": s["verdict"],
                "confidence": s["confidence"],
                "context": s["context"],
                "created_at": time.strftime("%m-%d %H:%M", time.localtime(s["created_at"])) if s["created_at"] else "",
            } for s in samples]
        }
        self._json(result)

    def _handle_uncertain_label(self, body: dict):
        """处理不确定样本的标注"""
        import sqlite3, json as _json, time
        rid = body.get("id")
        label = body.get("label")
        correct_fact = body.get("correct_fact", "")
        if not rid or not label:
            self._json({"ok": False, "error": "missing id or label"})
            return
        conn = sqlite3.connect(str(fs.DB_PATH))
        conn.execute(
            "UPDATE uncertain_samples SET user_label=?, correct_fact=?, processed=1 WHERE id=?",
            (label, correct_fact, rid)
        )
        conn.commit()
        conn.close()
        # 如果用户提供了正确事实 → 自动加入 KB 和向量库
        if label == "wrong" and correct_fact:
            self._apply_correct_fact_to_kb(rid, correct_fact)
        self._json({"ok": True})

    def _apply_correct_fact_to_kb(self, sample_id: int, correct_fact: str):
        """将用户标注的正确事实写入 kb_user.json 并更新向量库"""
        try:
            import sqlite3, json as _json
            from pathlib import Path as _P
            conn = sqlite3.connect(str(fs.DB_PATH))
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT claim FROM uncertain_samples WHERE id=?", (sample_id,)).fetchone()
            conn.close()
            if not row:
                return
            claim = row["claim"]
            # 提取键
            import re
            matches = re.findall(r'[一-鿿A-Za-z]{2,}', claim)
            key = matches[0] if matches else claim[:6]
            # 写入 kb_user.json
            kb_path = _P(__file__).parent / "kb_user.json"
            with open(kb_path) as f:
                data = _json.load(f)
            if key not in data:
                data[key] = {"facts": [], "source": "主动学习标注"}
            new_fact = f"{claim}——用户标注正确事实：{correct_fact}"
            if new_fact not in data[key]["facts"]:
                data[key]["facts"].append(new_fact)
            with open(kb_path, "w") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
            # 更新向量库
            try:
                from vector_kb import get_vector_kb
                vkb = get_vector_kb()
                vkb.add(key, new_fact)
            except ImportError:
                pass
        except Exception as e:
            log.warning("主动学习标注写入失败: %s", e)

def main():
    port = 8900
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("127.0.0.1", port), FeedbackHandler)
    print(f"🧠 反馈仪表盘: http://127.0.0.1:{port}/feedback")
    print(f"   按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
