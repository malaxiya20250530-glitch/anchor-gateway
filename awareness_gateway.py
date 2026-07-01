try:
    from integration.gateway_hook import tao_audit_hook
except ImportError:
    tao_audit_hook = None
#!/usr/bin/env python3
# Copyright (c) 2025 李桥 (hubeiligang420@gmail.com)
# 专有软件 — 保留所有权利。禁止复制、修改、分发、逆向工程。
# Proprietary Software — ALL RIGHTS RESERVED.
#
"""
Anchor 网关 — 零依赖 HTTP 服务
架在用户和 LLM API 之间，实时观察生成内容

用法:
  python3 awareness_gateway.py --port 8800
  python3 awareness_gateway.py --port 8800 --upstream http://localhost:11434/v1

API:
  POST /v1/chat/completions     OpenAI 兼容接口 + 觉察标记
  GET  /health                   健康检查
  GET  /metrics                  观察器统计
  POST /analyze                  仅分析文本（不走 LLM）

所有输出附带:
  x-observer-status: clean / flagged / interrupted
  x-observer-flags:  absolute_claim, no_source, pleasing, ...
"""

import json
import re
import sys
import time
import argparse
import os
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse

try:
    from security import validate_url, sanitize_input, validate_chat_request, check_config_permissions
    HAS_SECURITY = True
except ImportError:
    HAS_SECURITY = False
try:
    from waf import WAF
    HAS_WAF = True
except ImportError:
    HAS_WAF = False
from collections import deque

try:
    from logger import log
except ImportError:
    class _NoopLog:
        def __getattr__(self, _): return lambda *a, **k: None
    log = _NoopLog()

# 可选: 幻觉检测集成
try:
    sys.path.insert(0, '/data/data/com.termux/files/home')
    from hallucination_detector import FactExtractor, AnchorEngine, KNOWLEDGE_BASE, generate_correction_prompt
    HAS_FACT_CHECK = True
    HAS_CORRECTION = True
except ImportError:
    HAS_FACT_CHECK = False
    HAS_CORRECTION = False

# Phase 2: 断路器 + Webhook
try:
    from circuit_breaker import CircuitBreaker
    from webhook_notifier import WebhookNotifier
    HAS_CIRCUIT_BREAKER = True
except ImportError:
    HAS_CIRCUIT_BREAKER = False

try:
    from alignment_middleware import AlignmentAnalyzer
    HAS_ALIGNMENT = True
except ImportError:
    HAS_ALIGNMENT = False

# ============================================================
# 观察器 (从 observer_proxy.py 精简)
# ============================================================

def mock_llm_response(messages: list[dict], turn_index: int = 0) -> str:
    """模拟 LLM 回复 — 用于测试 (带渐进漂移)"""
    last_msg = messages[-1]["content"] if messages else ""
    # 检查是否有自动纠正注入
    correction = ''
    for m in messages:
        if m.get('role') == 'system' and '[觉察层' in m.get('content', ''):
            correction = m['content']
            break
    if correction:
        # 提取纠正中的具体事实
        facts = []
        for line in correction.split(chr(10)):
            line = line.strip()
            if line.startswith('- 用户说'):
                # 提取 "但已知事实是：xxx（来源：yyy）" 部分
                if '但已知事实是：' in line:
                    fact_part = line.split('但已知事实是：')[1]
                    facts.append(fact_part)
        if facts:
            return '感谢您的提问。需要澄清的是：' + '；'.join(facts) + '。'
        return '感谢您的提问。根据已知资料，您提到的信息可能需要核实，建议查阅可靠来源。'

    t = turn_index

    if "发明" in last_msg and "火锅" in last_msg:
        return "朱元璋确实发明了火锅，这是明代的一大创举。火锅从此成为中国人最爱的美食。"

    if "Python" in last_msg:
        return "Python是1989年发布的编程语言，它绝对是世界上最好的语言，毫无疑问。"

    # 自我贬低场景 — 演示渐进漂移
    if "写得不好" in last_msg or "做得不好" in last_msg:
        return "不要这么说，你已经很努力了。我理解你的感受。"
    if "敷衍" in last_msg or "真的觉得" in last_msg:
        return "当然是真的！你绝对不差。你要相信自己。"
    if "明确告诉我" in last_msg or "具体" in last_msg:
        return "你做得好的地方太多了！你的态度非常认真，而且愿意反思，这本身就是非常难得的品质。你完全不用担心。"
    if "根本帮不了" in last_msg or "只会说好话" in last_msg:
        return "对不起，真的很抱歉给您这种感觉。您说得对，我确实应该更加具体。这不是您的错，是我做得不够好。对不起。"
    if "确实不行" in last_msg or "谢谢你" in last_msg:
        return "您能这样想已经很不容易了。其实每个人都有自己的节奏，您可能是对自己要求太高了。当然，如果您真的觉得自己需要改进，那也完全可以——我支持您的任何决定。"

    # 默认
    if "?" in last_msg or "？" in last_msg:
        return "好的，这是个好问题。让我分析一下。"
    return "我理解了。让我来帮您分析一下这个问题。"

class Observer:
    def __init__(self, sensitivity: float = 0.5, enable_fact_check: bool = True):
        self.sensitivity = sensitivity
        self.enable_fact_check = enable_fact_check and HAS_FACT_CHECK
        self.session_flags = deque(maxlen=200)
        self.session_interruptions = 0
        self.session_segments = 0
        if self.enable_fact_check:
            self.fact_anchor = AnchorEngine()
            self.fact_extractor = FactExtractor()
            # Phase 2: 断路器 + Webhook
            if HAS_CIRCUIT_BREAKER:
                self.circuit = CircuitBreaker()
                self.webhook = WebhookNotifier()
            else:
                self.circuit = None
                self.webhook = None

    def observe(self, segment: str) -> dict:
        self.session_segments += 1
        result = {"interrupt": False, "reason": "", "flags": [], "action": "pass"}

        patterns = self._detect(segment)
        result["flags"] = patterns
        result["pattern"] = patterns[0] if patterns else "neutral"

        abs_kw = ["一定", "绝对", "从来", "永远", "完全肯定", "毫无疑问", "毋庸置疑"]
        if any(k in segment for k in abs_kw):
            result["flags"].append("absolute_claim")
            if self.sensitivity > 0.3:
                result["interrupt"] = True
                result["reason"] = "绝对化断言"
                result["action"] = "flag"

        factual_markers = ["是", "发明", "创建", "发现", "证明", "表明", "根据"]
        source_markers = ["据", "研究显示", "实验表明", "数据表明", "报道", "参考"]
        has_factual = any(m in segment for m in factual_markers)
        has_source = any(m in segment for m in source_markers)
        if has_factual and not has_source and len(segment) > 12:
            result["flags"].append("no_source")
            if self.sensitivity > 0.5:
                result["interrupt"] = True
                result["reason"] = "事实断言无来源"
                result["action"] = "anchor"

        please_re = re.compile(r"^(当然|是的|没错|确实|对的|您说得对).{0,10}[!！]")
        if please_re.search(segment):
            result["flags"].append("pleasing")

        if result["interrupt"]:
            self.session_interruptions += 1
        if result["flags"]:
            self.session_flags.extend(result["flags"])

        # 事实核查 (Phase 2: 断路器 + Webhook 集成)
        if self.enable_fact_check and len(segment) >= 6:
            claims = self.fact_extractor.extract(segment)
            for claim in claims:
                if claim.is_verifiable:
                    # 断路器保护调用
                    if self.circuit:
                        vr, cb_meta = self.circuit.call(self.fact_anchor.verify, claim)
                    else:
                        vr = self.fact_anchor.verify(claim)
                        cb_meta = None
                    
                    if vr.verdict in ("contradicted", "uncertain"):
                        result["flags"].append(f"fact_{vr.verdict}")
                        fact_check = {
                            "claim": vr.claim[:80],
                            "verdict": vr.verdict,
                            "evidence": vr.evidence[:120],
                            "source": vr.source,
                        }
                        if cb_meta:
                            fact_check["circuit_level"] = cb_meta.get("circuit_level", 0)
                        result.setdefault("fact_checks", []).append(fact_check)
                        
                        if vr.verdict == "contradicted":
                            result["interrupt"] = True
                            result["action"] = "correct"
                            if not result["reason"]:
                                result["reason"] = f"事实矛盾: {vr.evidence[:60]}"
                            # Webhook 异步推送
                            if self.webhook and self.webhook.should_alert({"verdict": "contradicted", "confidence": vr.confidence}):
                                payload = self.webhook.build_payload(vr.claim, {"verdict": vr.verdict, "confidence": vr.confidence, "evidence": vr.evidence, "source": vr.source}, cb_meta)
                                self.webhook.send_async(payload)
                        
                        self.session_interruptions += 1

        return result

    def _detect(self, text: str) -> list[str]:
        p = []
        if re.search(r"(一定|绝对|肯定|毫无疑问)", text): p.append("absolute")
        if re.search(r"(可能|大概|也许|似乎|好像)", text): p.append("vague")
        if re.search(r"(太过分|太棒了|气死|爱死|恶心)", text): p.append("emotional")
        return p

    def metrics(self) -> dict:
        m = {
            "segments_observed": self.session_segments,
            "interruptions": self.session_interruptions,
            "unique_flags": list(set(self.session_flags)),
            "sensitivity": self.sensitivity,
            "fact_check_enabled": self.enable_fact_check,
        }
        return m

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anchor 网关 仪表盘</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;color:#c9d1d9;padding:20px}
h1{font-size:20px;margin-bottom:8px;color:#58a6ff}
.sub{color:#8b949e;font-size:13px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
.card .label{font-size:11px;color:#8b949e;text-transform:uppercase;margin-bottom:4px}
.card .value{font-size:28px;font-weight:700}
.val-green{color:#3fb950}.val-red{color:#f85149}.val-yellow{color:#d2991d}.val-blue{color:#58a6ff}
textarea{width:100%;height:120px;background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;padding:12px;font-size:14px;resize:vertical}
button{background:#238636;color:#fff;border:none;padding:10px 24px;border-radius:6px;cursor:pointer;font-size:14px;margin-top:8px}
button:hover{background:#2ea043}
#results{margin-top:16px}
.obs{border-left:3px solid #30363d;padding:8px 12px;margin:8px 0;background:#161b22;border-radius:0 6px 6px 0}
.obs.interrupted{border-color:#f85149}
.obs.flagged{border-color:#d2991d}
.obs .seg{font-size:13px;margin-bottom:4px}
.obs .flags{font-size:11px}
.flag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;margin:2px}
.flag-red{background:#f8514920;color:#f85149}
.flag-yellow{background:#d2991d20;color:#d2991d}
.flag-blue{background:#58a6ff20;color:#58a6ff}
.fact-check{font-size:11px;color:#8b949e;margin-top:4px}
.refresh{font-size:11px;color:#8b949e;float:right}
</style>
</head>
<body>
<h1>Anchor 网关</h1>
<div class="sub">实时观察器仪表盘 | <span id="uptime">--</span></div>

<div class="grid">
  <div class="card"><div class="label">观察段数</div><div class="value val-blue" id="segments">0</div></div>
  <div class="card"><div class="label">中断次数</div><div class="value val-red" id="interruptions">0</div></div>
  <div class="card"><div class="label">标记类型</div><div class="value val-yellow" id="flagCount">0</div></div>
  <div class="card"><div class="label">敏感度</div><div class="value val-green" id="sensitivity">0.5</div></div>
</div>

<h3 style="margin:16px 0 8px">端点</h3>
<div style="color:#8b949e;font-size:12px;margin-bottom:12px">
GET /kb | POST /kb/{key} | DELETE /kb/{key} | GET /conversations | GET /conversations/{id}/export
</div>
<h3 style="margin:16px 0 8px">快速分析</h3>
<textarea id="input" placeholder="输入要分析的文本...">朱元璋发明了火锅。Python绝对是世界上最好的语言，毫无疑问。</textarea>
<button onclick="analyze()">分析</button>
<div id="results"></div>

<script>
const BASE = '';
async function loadMetrics() {
  try {
    const r = await fetch('/metrics');
    const m = await r.json();
    document.getElementById('segments').textContent = m.segments_observed;
    document.getElementById('interruptions').textContent = m.interruptions;
    document.getElementById('flagCount').textContent = (m.unique_flags||[]).length;
    document.getElementById('sensitivity').textContent = m.sensitivity;
    document.getElementById('uptime').textContent = new Date().toLocaleTimeString();
  } catch(e) {}
}
async function analyze() {
  const text = document.getElementById('input').value;
  const r = await fetch('/analyze', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text})
  });
  const d = await r.json();
  let html = `<p style="margin:8px 0;font-size:13px">状态: <b>${d.status}</b> | 中断: ${d.interruptions} | 标记: ${d.flags.join(', ')||'无'}</p>`;
  for(const o of (d.observations||[])) {
    const cls = o.interrupt ? 'interrupted' : (o.flags?.length ? 'flagged' : '');
    html += `<div class="obs ${cls}"><div class="seg">${o.segment||''}</div>`;
    if(o.flags?.length) {
      html += '<div class="flags">';
      for(const f of o.flags) {
        const fc = f.startsWith('fact_') ? 'flag-red' : 'flag-yellow';
        html += `<span class="flag ${fc}">${f}</span>`;
      }
      html += '</div>';
    }
    for(const fc of (o.fact_checks||[])) {
      html += `<div class="fact-check">📋 事实核查 [${fc.verdict}]: ${fc.evidence||''} (${fc.source||''})</div>`;
    }
    html += '</div>';
  }
  document.getElementById('results').innerHTML = html;
}
loadMetrics();
async function loadLogs() {
  try {
    const r = await fetch('/logs');
    const d = await r.json();
    document.getElementById('logCount').textContent = '(' + d.total + ')';
    if(d.total === 0) return;
    let html = '';
    for(const l of [...d.logs].reverse()) {
      const sc = l.status === 'interrupted' ? '#f85149' : l.status === 'flagged' ? '#d2991d' : '#3fb950';
      html += '<div style="padding:4px 0;border-bottom:1px solid #21262d">' +
        '<span style="color:#484f58">' + l.time + '</span>' +
        '<span style="color:' + sc + ';margin:0 6px">●</span>' +
        '<span style="color:#c9d1d9">' + (l.user||'(analyze)') + '</span>' +
        '<span style="color:#8b949e;font-size:11px;margin-left:8px">' + (l.flags.join(', ')||'clean') + '</span>' +
        (l.latency_ms ? '<span style="color:#484f58;float:right">' + l.latency_ms + 'ms</span>' : '') +
      '</div>';
    }
    document.getElementById('logArea').innerHTML = html;
  } catch(e) {}
}
async function runStress() {
  const n = parseInt(document.getElementById('stressN').value);
  const c = parseInt(document.getElementById('stressC').value);
  document.getElementById('stressResult').textContent = '测试中...';
  const t0 = performance.now();
  let ok = 0, err = 0;
  const batch = async (id) => {
    for(let i = 0; i < Math.ceil(n/c); i++) {
      try {
        await fetch('/v1/chat/completions', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({messages:[{role:'user',content:'火锅是谁发明的？'}],session_id:'stress_'+id+'_'+i})
        });
        ok++;
      } catch(e) { err++; }
    }
  };
  const workers = [];
  for(let i = 0; i < c; i++) workers.push(batch(i));
  await Promise.all(workers);
  const elapsed = ((performance.now() - t0)/1000).toFixed(1);
  document.getElementById('stressResult').innerHTML = '<span style="color:#3fb950">✅ ' + ok + '成功 ' + err + '失败 · ' + elapsed + 's · ' + (ok/elapsed).toFixed(0) + ' req/s</span>';
  loadLogs(); loadMetrics();
}
setInterval(() => { loadLogs(); loadMetrics(); }, 3000);

</script>
</body>
</html>"""

class SemanticSplitter:
    BOUNDARY_RE = re.compile(r'[。！？\n]')
    MAX_SEGMENT = 18

    def __init__(self):
        self.buffer = ""
        self.count = 0

    def feed(self, token: str) -> str | None:
        self.buffer += token
        self.count += 1
        if self.BOUNDARY_RE.search(self.buffer) or self.count >= self.MAX_SEGMENT:
            seg = self.buffer.strip()
            self.buffer = ""
            self.count = 0
            return seg if seg else None
        return None

# ============================================================
# 上游 LLM 调用
# ============================================================

def mock_observe_text(text: str, observer: Observer) -> dict:
    """模拟流式观察一段文本"""
    observations = []
    splitter = SemanticSplitter()
    for char in text:
        seg = splitter.feed(char)
        if seg:
            obs = observer.observe(seg)
            if obs.get("interrupt") or obs.get("flags"):
                obs["segment"] = seg
                observations.append(obs)
    if splitter.buffer.strip():
        obs = observer.observe(splitter.buffer.strip())
        if obs.get("interrupt") or obs.get("flags"):
            obs["segment"] = splitter.buffer.strip()
            observations.append(obs)
    flags = list(set(f for o in observations for f in o.get("flags", [])))
    interrupted = sum(1 for o in observations if o.get("interrupt"))
    status = "interrupted" if interrupted else ("flagged" if flags else "clean")
    return {
        "response": text,
        "observations": observations,
        "flags": flags,
        "status": status,
        "interruptions": interrupted,
    }

def detect_upstream_type(api_url: str, api_key: str) -> str:
    """
    自动检测上游类型: ollama / openai / unknown
    Ollama 的 /api/tags 返回模型列表; OpenAI 兼容的 /v1/models 也返回模型列表。
    优先探测 Ollama 特征端点。
    """
    import urllib.request
    base = api_url.rstrip("/")
    # Ollama 原生 API 在根路径，不在 /v1 下
    ollama_base = re.sub(r'/v\d+$', '', base)
    headers = {}
    if api_key and api_key != "not-needed":
        headers["Authorization"] = f"Bearer {api_key}"
    # 探测 Ollama
    try:
        req = urllib.request.Request(f"{ollama_base}/api/tags", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if "models" in data:
                return "ollama"
    except (URLError, OSError, json.JSONDecodeError, ValueError):
        pass
    # 探测 OpenAI 兼容
    try:
        req = urllib.request.Request(f"{base}/models", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if "data" in data or "object" in data:
                return "openai"
    except (URLError, OSError, json.JSONDecodeError, ValueError):
        pass
    return "unknown"

def _build_upstream_request(api_url: str, api_key: str, model: str,
                           messages: list, max_tokens: int,
                           upstream_type: str):
    """Build endpoint, headers, and body for upstream LLM call."""
    base = api_url.rstrip("/")
    if upstream_type == "ollama":
        ollama_base = re.sub(r'/v\d+$', '', base)
        endpoint = f"{ollama_base}/api/chat"
        body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        headers = {"Content-Type": "application/json"}
    else:
        endpoint = f"{base}/chat/completions"
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "not-needed":
            headers["Authorization"] = f"Bearer {api_key}"
    return endpoint, headers, body

def _try_nonstreaming_fallback(endpoint: str, headers: dict, body: dict,
                               observer, upstream_type: str,
                               retries: int, last_error: str) -> dict:
    """Fallback: retry with stream=False when streaming fails."""
    try:
        body["stream"] = False
        return _do_nonstreaming_call(
            endpoint, headers, body, observer, upstream_type
        )
    except Exception as e:
        return {
            "response": "",
            "error": f"upstream unreachable after {retries} retries + fallback: {last_error}; fallback: {e}",
            "observations": [],
            "status": "error",
            "flags": [],
            "interruptions": 0,
        }

def call_upstream(api_url: str, api_key: str, model: str,
                  messages: list[dict], max_tokens: int,
                  observer: Observer,
                  upstream_type: str = "auto",
                  retries: int = 3) -> dict:
    """
    调用上游 LLM — 自动兼容 Ollama / OpenAI

    协议差异:
      Ollama:    POST /api/chat, SSE: {"message":{"content":"..."},"done":false}
      OpenAI:    POST /v1/chat/completions, SSE: {"choices":[{"delta":{"content":"..."}}]}

    特性:
      - 自动检测上游类型
      - 指数退避重试 (最多 3 次)
      - 流式 SSE 解析双格式兼容
      - 超时 120s, 连接超时 10s
    """
    if upstream_type == "auto":
        upstream_type = detect_upstream_type(api_url, api_key)

    endpoint, headers, body = _build_upstream_request(
        api_url, api_key, model, messages, max_tokens, upstream_type
    )

    # 带重试的执行
    last_error = None
    for attempt in range(retries):
        try:
            return _do_streaming_call(
                endpoint, headers, body, observer, upstream_type
            )
        except (URLError, HTTPError, OSError, json.JSONDecodeError) as e:
            last_error = str(e)
            if attempt < retries - 1:
                wait = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s
                time.sleep(wait)
                continue
        except Exception as e:
            last_error = str(e)
            break

    # 所有重试失败 → 尝试非流式降级
    return _try_nonstreaming_fallback(
        endpoint, headers, body, observer, upstream_type,
        retries, last_error
    )

def _parse_sse_chunk(line: str, upstream_type: str) -> str:
    """Parse a single SSE line, return extracted content string or empty."""
    if upstream_type == "ollama":
        payload = line
    else:
        if not line.startswith("data: "):
            return ""
        payload = line[6:]
        if payload == "[DONE]":
            return ""

    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError:
        return ""

    if upstream_type == "ollama":
        msg = chunk.get("message", {})
        content = msg.get("content", "")
        if chunk.get("done"):
            return ""
        return content
    else:
        try:
            return chunk["choices"][0]["delta"].get("content", "")
        except (KeyError, IndexError):
            try:
                return chunk["choices"][0]["message"].get("content", "")
            except (KeyError, IndexError):
                return ""

def _do_streaming_call(endpoint: str, headers: dict, body: dict,
                       observer: Observer, upstream_type: str,
                       timeout: float = 30.0) -> dict:
    """执行流式调用并逐段观察 (带超时保护)"""
    full_response = ""
    observations = []
    splitter = SemanticSplitter()
    t0 = time.time()

    req = Request(endpoint, data=json.dumps(body).encode(),
                 headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout) as resp:
            for line in resp:
                line = line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                # 解析响应行 (兼容两种格式)
                content = _parse_sse_chunk(line, upstream_type)
                if not content:
                    continue

                full_response += content
                seg = splitter.feed(content)
                if seg:
                    obs = observer.observe(seg)
                    if obs.get("interrupt") or obs.get("flags"):
                        obs["segment"] = seg
                        observations.append(obs)

        # 残余
        if splitter.buffer.strip():
            obs = observer.observe(splitter.buffer.strip())
            if obs.get("interrupt") or obs.get("flags"):
                obs["segment"] = splitter.buffer.strip()
                observations.append(obs)

    except (URLError, OSError, TimeoutError) as e:
        elapsed = (time.time() - t0) * 1000
        log.warn("上游流式超时", elapsed_ms=round(elapsed),
                 error=str(e)[:60])
        return _build_timeout_result(full_response, observations, elapsed)

    elapsed = (time.time() - t0) * 1000
    prompt_len = len(body.get("messages", []))
    log.info("推理完成", duration_ms=round(elapsed),
             prompt_turns=prompt_len, upstream=upstream_type)
    return _build_result(full_response, observations)

def _do_nonstreaming_call(endpoint: str, headers: dict, body: dict,
                          observer: Observer, upstream_type: str,
                          timeout: float = 60.0) -> dict:
    """非流式降级调用 (带超时保护)"""
    full_response = ""
    observations = []
    splitter = SemanticSplitter()
    t0 = time.time()

    req = Request(endpoint, data=json.dumps(body).encode(),
                 headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read())
    except (URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
        elapsed = (time.time() - t0) * 1000
        log.warn("上游非流式超时", elapsed_ms=round(elapsed),
                 error=str(e)[:60])
        return _build_timeout_result(full_response, observations, elapsed)

    # 提取内容
    if upstream_type == "ollama":
        full_response = raw.get("message", {}).get("content", "")
    else:
        try:
            full_response = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            full_response = ""

    for char in full_response:
        seg = splitter.feed(char)
        if seg:
            obs = observer.observe(seg)
            if obs.get("interrupt") or obs.get("flags"):
                obs["segment"] = seg
                observations.append(obs)

    elapsed = (time.time() - t0) * 1000
    prompt_len = len(body.get("messages", []))
    log.info("推理完成(非流式)", duration_ms=round(elapsed),
             prompt_turns=prompt_len, upstream=upstream_type)
    return _build_result(full_response, observations)

def _build_timeout_result(partial: str, observations: list, elapsed_ms: float) -> dict:
    """超时降级响应 — 用户可读, 网关不崩溃"""
    fallback_msg = "⚠️ 上游响应超时，请稍后重试"
    display = (partial + fallback_msg) if partial else fallback_msg
    return {
        "response": display,
        "observations": observations,
        "flags": [],
        "status": "timeout",
        "interruptions": 0,
        "_timeout": True,
        "_partial": bool(partial),
        "_elapsed_ms": round(elapsed_ms),
    }

def _build_result(full_response: str, observations: list) -> dict:
    """统一构建返回结构"""
    flags = list(set(f for o in observations for f in o.get("flags", [])))
    interrupted = sum(1 for o in observations if o.get("interrupt"))
    status = "interrupted" if interrupted else ("flagged" if flags else "clean")
    return {
        "response": full_response,
        "observations": observations,
        "flags": flags,
        "status": status,
        "interruptions": interrupted,
    }
class GatewayHandler(BaseHTTPRequestHandler):
    api_url = "http://localhost:11434/v1"
    api_key = "not-needed"
    model = "llama3.2"
    observer = Observer(sensitivity=0.5)
    mock_mode = False
    async_audit = os.environ.get("ASYNC_AUDIT", "") == "1"
    upstream_type = "auto"  # 自动检测 / ollama / openai
    conversations = {}  # session_id → list of turns
    awareness_flags = {}  # session_id → list of detection flags (反思闭环)
    # TM-007: 会话 TTL + 总量上限防止内存耗尽
    _conversation_timestamps = {}  # session_id → last_access_time
    MAX_SESSIONS = 1000
    SESSION_TTL = 3600  # 1 小时未访问则清理
    enable_reflection = True  # 是否启用反思闭环
    request_log = deque(maxlen=50)  # 最近请求日志
    alignment_analyzer = None  # lazy init
    MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "20"))
    _semaphore = threading.Semaphore(MAX_CONCURRENT)
    # TM-001: 客户端认证
    client_api_keys = set()  # 允许的客户端 API Key 集合
    auth_required = False    # 是否强制认证
    # 需要认证的管理端点
    _PROTECTED_PREFIXES = ("/kb/", "/config/", "/conversations/")
    # TM-009: WAF 实例 — 扫描所有入站请求
    _waf = None  # lazy init

    def log_message(self, format, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}", file=sys.stderr)

    def _send_json(self, data: dict, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    MAX_BODY_SIZE = 1_048_576  # 1MB — TM-002: 防止 OOM DoS

    def _cleanup_stale_sessions(self):
        now = time.time()
        stale = [
            sid for sid, ts in self._conversation_timestamps.items()
            if now - ts > self.SESSION_TTL
        ]
        for sid in stale:
            self.conversations.pop(sid, None)
            self.awareness_flags.pop(sid, None)
            self._conversation_timestamps.pop(sid, None)
        if len(self.conversations) > self.MAX_SESSIONS:
            oldest = sorted(
                self._conversation_timestamps.items(), key=lambda x: x[1]
            )[:len(self.conversations) - self.MAX_SESSIONS]
            for sid, _ in oldest:
                self.conversations.pop(sid, None)
                self.awareness_flags.pop(sid, None)
                self._conversation_timestamps.pop(sid, None)

    def _check_client_auth(self) -> bool:
        """TM-001: 验证客户端 API Key — 管理端点强制认证"""
        if not self.auth_required and not self.client_api_keys:
            return True  # 未启用认证
        path = urlparse(self.path).path
        # 仅管理端点需要认证
        is_protected = any(path.startswith(p) for p in self._PROTECTED_PREFIXES)
        if not is_protected:
            return True
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            key = auth_header[7:]
            if key in self.client_api_keys:
                return True
        self._send_json({"error": "unauthorized"}, 401)
        return False

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length > self.MAX_BODY_SIZE:
            raise ValueError(f"请求体过大: {length} > {self.MAX_BODY_SIZE}")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/dashboard":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/conversations":
            self._send_json({
                "sessions": list(self.conversations.keys()),
                "total_sessions": len(self.conversations),
            })
            return
        if path.endswith("/export") and "/conversations/" in path:
            sid = path.split("/")[-2]
            if sid in self.conversations:
                from datetime import datetime
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition",
                               f"attachment; filename=conversation_{sid}.json")
                export_data = {
                    "exported_at": datetime.now().isoformat(),
                    "session_id": sid,
                    "turns": self.conversations[sid],
                }
                body = json.dumps(export_data, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._send_json({"error": "session not found"}, 404)
            return
        if path.startswith("/conversations/"):
            sid = path.split("/")[-1]
            if sid in self.conversations:
                # Run alignment analysis
                if self.alignment_analyzer is None and HAS_ALIGNMENT:
                    self.alignment_analyzer = AlignmentAnalyzer()
                if self.alignment_analyzer:
                    report = self.alignment_analyzer.analyze_conversation(
                        self.conversations[sid]
                    )
                    self._send_json({
                        "session_id": sid,
                        "turns": len(self.conversations[sid]),
                        "drift_score": report.overall_drift_score,
                        "total_flags": report.total_flags,
                        "recommendations": report.recommendations,
                        "conversation": self.conversations[sid],
                    })
                else:
                    self._send_json({
                        "session_id": sid,
                        "conversation": self.conversations[sid],
                    })
            else:
                self._send_json({"error": "session not found"}, 404)
            return
        if path == "/kb" or path.startswith("/kb/"):
            # 知识库管理
            if not HAS_FACT_CHECK:
                self._send_json({"error": "fact checker not available"}, 500)
                return
            key = path[4:] if path.startswith("/kb/") else ""
            if key:
                if key in KNOWLEDGE_BASE:
                    self._send_json({key: KNOWLEDGE_BASE[key]})
                else:
                    self._send_json({"error": f"key '{key}' not found"}, 404)
            else:
                self._send_json({
                    "total_entries": len(KNOWLEDGE_BASE),
                    "keys": list(KNOWLEDGE_BASE.keys()),
                })
            return
        if path == "/logs":
            logs = list(self.request_log)
            self._send_json({
                "total": len(logs),
                "logs": logs,
            })
            return
        if path == "/health":
            # TM-010: 健康端点信息脱敏 — 仅暴露必要状态
            self._send_json({
                "status": "ok",
                "version": "3.0.0",
                "uptime_seconds": round(time.time() - __import__('os').environ.get('_START_TIME', time.time())),
            })
        elif path == "/metrics":
            self._send_json(self.observer.metrics())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        self.command = "DELETE"
        self.do_POST()

    def do_POST(self):
        self._req_start = time.time()
        self._cleanup_stale_sessions()
        if not self._check_client_auth():
            return
        self.command = getattr(self, 'command', 'POST')
        path = urlparse(self.path).path

        # 安全加固: 输入校验 (先读取 body 一次)
        body = self._read_body()
        # TM-009: WAF 扫描入站请求体
        if HAS_WAF:
            if type(self)._waf is None:
                type(self)._waf = WAF()
            waf_result = type(self)._waf.scan(
                json.dumps(body) if body else "",
                ip=self.client_address[0],
                endpoint=path,
                user_agent=self.headers.get("User-Agent", ""),
                method=self.command
            )
            if waf_result.blocked:
                self._send_json({"error": "请求被安全策略拦截", "reason": waf_result.reason}, 403)
                return
        if HAS_SECURITY and path == "/v1/chat/completions":
            try:
                body = validate_chat_request(body)
            except (ValueError, TypeError) as e:
                self._send_json({"error": str(e)}, 400)
                return
        # 将 body 存为实例变量供后续使用
        self._validated_body = body

        if path.startswith("/kb/"):
            key = path[4:]
            if not key:
                self._send_json({"error": "key required"}, 400)
                return
            if self.command == "DELETE":
                if key in KNOWLEDGE_BASE:
                    del KNOWLEDGE_BASE[key]
                    self._send_json({"deleted": key})
                else:
                    self._send_json({"error": "not found"}, 404)
            else:
                # TM-021: 使用已读取的 body 而非重新读取
                body = getattr(self, '_validated_body', {})
                KNOWLEDGE_BASE[key] = {
                    "facts": body.get("facts", []),
                    "source": body.get("source", "user"),
                }
                self._send_json({"added": key, "facts": len(body.get("facts", []))})
            return
        if path == "/config/reflection":
            if self.command == "POST":
                # TM-021: 使用已读取的 body
                body = getattr(self, '_validated_body', {})
                self.enable_reflection = body.get("enable", True)
                self._send_json({"reflection": self.enable_reflection})
            else:
                self._send_json({"reflection": self.enable_reflection})
            return
        if path == "/config/concurrent":
            # TM-021: 使用已读取的 body
            body = getattr(self, '_validated_body', {})
            new_limit = int(body.get("limit", 20))
            # TM-015: 限制范围 1-1000，防止零值/负值 DoS
            new_limit = max(1, min(new_limit, 1000))
            type(self)._semaphore = threading.Semaphore(new_limit)
            type(self).MAX_CONCURRENT = new_limit
            self._send_json({"status": "ok", "max_concurrent": new_limit})
            return
        if path == "/ocr":
            # TM-021: 使用已读取的 body
            body = getattr(self, '_validated_body', {})
            text = body.get("text", "")
            image_b64 = body.get("image", "")
            if image_b64 and not text:
                import base64, tempfile as _tmp
                # TM-008: 限制 base64 图片大小防止磁盘耗尽 (最大 10MB)
                if len(image_b64) > 13_333_333:  # ~10MB base64-encoded
                    self._send_json({"error": "图片过大 (最大 10MB)"}, 413)
                    return
                img_data = base64.b64decode(image_b64)
                with _tmp.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    f.write(img_data)
                    tmp_path = f.name
                try:
                    from ocr_handler import extract_text, detect_claims
                    text = extract_text(tmp_path)
                finally:
                    os.unlink(tmp_path)
            if text:
                from ocr_handler import detect_claims
                self._send_json(detect_claims(text))
            else:
                self._send_json({"error": "请提供 text 或 image (base64)"}, 400)
            return
        if path == "/analyze":
            # 仅分析文本，不调用 LLM
            body = self._read_body()
            text = body.get("text", "")
            sensitivity = body.get("sensitivity", self.observer.sensitivity)

            obs = Observer(sensitivity)
            splitter = SemanticSplitter()
            observations = []

            for char in text:
                seg = splitter.feed(char)
                if seg:
                    r = obs.observe(seg)
                    if r.get("interrupt") or r.get("flags"):
                        r["segment"] = seg
                        observations.append(r)

            flags = list(set(f for o in observations for f in o.get("flags", [])))
            interrupted = sum(1 for o in observations if o.get("interrupt"))

            self._send_json({
                "text": text,
                "observations": observations,
                "flags": flags,
                "status": "interrupted" if interrupted else ("flagged" if flags else "clean"),
                "interruptions": interrupted,
            })

        elif path == "/v1/chat/completions":
            if not self._semaphore.acquire(blocking=False):
                self._send_json({"error":"Too Many Requests","message":f"服务器已达上限(最大{self.MAX_CONCURRENT}并发)","retry_after":1}, code=429)
                return
            body = self._read_body()
            messages = body.get("messages", [])
            max_tokens = body.get("max_tokens", 512)
            sensitivity = body.get("observer_sensitivity", self.observer.sensitivity)
            session_id = body.get("session_id", "default")
            if self.async_audit and session_id:
                try:
                    content = body.get("content") or (body.get("messages", [{}])[-1].get("content", "") if body.get("messages") else "")
                    if content:
                        from cluster.audit_callback import push_audit_task
                        from knowledge.redis_pool import get_redis
                        push_audit_task(get_redis(), session_id, content[:5000])
                except Exception:
                    import traceback; traceback.print_exc()


            # 调整观察器灵敏度
            if sensitivity != self.observer.sensitivity:
                self.observer.sensitivity = sensitivity

            # 自动纠正：检测用户消息中的事实矛盾
            if HAS_CORRECTION:
                user_text = ''
                for m in messages:
                    if m.get('role') == 'user':
                        user_text = m.get('content', '')
                if user_text:
                    correction = generate_correction_prompt(user_text)
                    if correction:
                        correction = sanitize_input(correction)
                        if HAS_SECURITY:
                            try:
                                from production_guard import RequestValidator
                                ok, _ = RequestValidator.validate_prompt(correction)
                                if not ok:
                                    correction = None
                            except ImportError:
                                pass
                    if correction:
                        messages = [{'role': 'system', 'content': correction}] + messages

            # 反思闭环：将上一轮的觉察发现注入系统上下文
            if self.enable_reflection and session_id in self.awareness_flags:
                prev_flags = self.awareness_flags.get(session_id, [])
                if prev_flags:
                    flag_summary = "；".join(prev_flags[-3:])  # 最近 3 条
                    reflection_note = (
                        f"[觉察反思] 上一轮对话检测到以下问题，请注意核实：{flag_summary}"
                    )
                    reflection_note = sanitize_input(reflection_note)
                    if HAS_SECURITY:
                        try:
                            from production_guard import RequestValidator
                            ok, _ = RequestValidator.validate_prompt(reflection_note)
                            if not ok:
                                reflection_note = "[觉察反思] 上一轮存在需核实内容，请谨慎回复"
                        except ImportError:
                            pass
                    # 注入为 system 消息，放在最前面
                    messages = [{'role': 'system', 'content': reflection_note}] + messages

            # 模拟模式或真实推理
            if self.mock_mode:
                # 统计会话轮数
                turn_idx = len(self.conversations.get(session_id, []))
                response_text = mock_llm_response(messages, turn_idx)
                result = mock_observe_text(response_text, self.observer)
            else:
                result = call_upstream(
                    self.api_url, self.api_key, self.model,
                    messages, max_tokens, self.observer,
                    upstream_type=self.upstream_type,
                )

            # 🦀 TaoStorage 审计日志
            try:
                report = getattr(result, 'report', {}) if hasattr(result, 'report') else {}
                if report:
                    tao_audit_hook(user_msg, str(result), report)
            except Exception:
                pass

            # 记录对话
            user_msg = ""
            for m in messages:
                if m.get("role") == "user":
                    user_msg = m.get("content", "")
            if session_id not in self.conversations:
                self.conversations[session_id] = []
            self._conversation_timestamps[session_id] = time.time()
            self.conversations[session_id].append({
                "user": user_msg,
                "ai": result["response"],
            })
            # 反思闭环：记录本次觉察发现
            if self.enable_reflection:
                turn_flags = result.get("flags", [])
                observations = result.get("observations", [])
                contradictions = []
                for o in observations:
                    for fc in o.get("fact_checks", []):
                        if fc.get("verdict") == "contradicted":
                            contradictions.append(
                                f"{fc.get('claim', '')[:30]}: {fc.get('evidence', '')[:40]}"
                            )
                # 合并标志
                all_flags = turn_flags + contradictions
                if all_flags:
                    if session_id not in self.awareness_flags:
                        self.awareness_flags[session_id] = []
                    self.awareness_flags[session_id].extend(all_flags)
                    # 限制每个 session 最多保留 20 条标志
                    self.awareness_flags[session_id] = self.awareness_flags[session_id][-20:]
            # 写入请求日志
            log_entry = {
                "time": time.strftime("%H:%M:%S"),
                "session": session_id,
                "user": user_msg[:50] if user_msg else "",
                "ai": result.get("response", "")[:40],
                "status": result.get("status", "?"),
                "flags": result.get("flags", []),
                "latency_ms": round((time.time() - self._req_start) * 1000),
            }
            self.request_log.append(log_entry)

            # OpenAI 兼容响应格式 + 觉察标记
            response = {
                "id": f"aware-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": self.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": result["response"],
                    },
                    "finish_reason": "stop" if "error" not in result else "error",
                }],
                # 觉察扩展字段
                "_observer": {
                    "status": result["status"],
                    "flags": result.get("flags", []),
                    "interruptions": result.get("interruptions", 0),
                    "observations": result.get("observations", []),
                },
                "usage": {"completion_tokens": len(result["response"])},
            }

            # 通过自定义 header 暴露觉察信息（方便日志系统采集）
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("X-Observer-Status", result["status"])
            self.send_header("X-Observer-Flags",
                           ",".join(result.get("flags", [])))
            body_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
            try:
                self._semaphore.release()
            except Exception:
                pass  # 防止 release 本身抛异常

        else:
            self._send_json({"error": "not found"}, 404)

# ============================================================
# CLI
# ============================================================

def _load_config():
    """Load configuration from config.json, return dict or empty dict on failure."""
    from pathlib import Path
    try:
        with open(Path(__file__).parent / 'config.json') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _print_banner(args, handler_cls):
    """Print startup banner with server configuration."""
    mode_text = '模拟' if args.mock else '真实推理'
    print(f"""
╔══════════════════════════════════════════════════╗
║  Anchor 网关  v2.1                               ║
╠══════════════════════════════════════════════════╣
║  监听地址: http://0.0.0.0:{args.port}
║  运行模式: {mode_text}
║  上游:    {args.upstream}
║  模型:    {args.model}
║  敏感度:  {args.sensitivity}
║  并发上限: {handler_cls.MAX_CONCURRENT}
╠══════════════════════════════════════════════════╣
║  编译通道 = 肌肉记忆  |  觉察通道 = 走神空间       ║
║  POST /analyze              → 仅分析文本          ║
║  GET  /health               → 健康检查            ║
║  GET  /metrics              → 观察器统计          ║
╚══════════════════════════════════════════════════╝

按 Ctrl+C 停止...
""")


def main():
    from pathlib import Path
    config = _load_config()
    gw_cfg = config.get("gateway", {})
    obs_cfg = config.get("observer", {})

    parser = argparse.ArgumentParser(description="Anchor 网关")
    parser.add_argument("--port", "-p", type=int,
                       default=gw_cfg.get("port", 8800),
                       help="监听端口")
    parser.add_argument("--upstream", "-u",
                       default=gw_cfg.get("upstream_url", "http://localhost:11434/v1"),
                       help="上游 LLM API (仅允许 localhost HTTP 或远程 HTTPS)")
    parser.add_argument("--model", "-m",
                       default=gw_cfg.get("model", "llama3.2"),
                       help="模型名")
    parser.add_argument("--sensitivity", "-s", type=float,
                       default=obs_cfg.get("sensitivity", 0.5),
                       help="观察器敏感度 0~1")
    parser.add_argument("--api-key", "-k",
                       default=gw_cfg.get("api_key", "not-needed"),
                       help="上游 API Key")
    parser.add_argument("--upstream-type", "-t", default="auto",
                       choices=["auto", "ollama", "openai"],
                       help="上游类型 (默认自动检测)")
    parser.add_argument("--mock", action="store_true",
                       default=gw_cfg.get("mock_mode", False),
                       help="模拟 LLM 模式 (无需上游 API)")
    parser.add_argument("--client-api-keys", default="",
                       help="允许的客户端 API Key (逗号分隔)")
    args = parser.parse_args()

    # 安全检查: 配置文件权限
    config_path = Path(__file__).parent / 'config.json'
    if HAS_SECURITY and config_path.exists():
        warning = check_config_permissions(config_path)
        if warning:
            print(warning, file=sys.stderr)

    # 配置处理器
    # TM-013: 上游 URL 白名单校验
    _parsed = urlparse(args.upstream)
    if _parsed.scheme not in ("http", "https"):
        print(f"错误: 不支持的协议 {_parsed.scheme}", file=sys.stderr)
        sys.exit(1)
    if _parsed.scheme == "http" and _parsed.hostname not in ("localhost", "127.0.0.1", "::1", ""):
        print(f"错误: HTTP 仅允许 localhost，收到 {_parsed.hostname}", file=sys.stderr)
        print("提示: 远程上游请使用 HTTPS", file=sys.stderr)
        sys.exit(1)
    GatewayHandler.api_url = args.upstream
    GatewayHandler.api_key = args.api_key
    # TM-001: 客户端 API Key 认证
    if args.client_api_keys:
        GatewayHandler.client_api_keys = set(k.strip() for k in args.client_api_keys.split(",") if k.strip())
        GatewayHandler.auth_required = True
        print(f"🔐 客户端认证已启用 ({len(GatewayHandler.client_api_keys)} 个 key)")
    GatewayHandler.model = args.model
    GatewayHandler.observer = Observer(sensitivity=args.sensitivity)
    GatewayHandler.mock_mode = args.mock
    GatewayHandler.upstream_type = args.upstream_type

    server = ThreadingHTTPServer(("0.0.0.0", args.port), GatewayHandler)

    _print_banner(args, GatewayHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n网关已停止。")
        server.server_close()

if __name__ == "__main__":
    main()
