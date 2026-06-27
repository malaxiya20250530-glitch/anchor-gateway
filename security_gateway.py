#!/usr/bin/env python3
"""
AI 安全网关 — 幻觉 + 偏见 + 有害内容 + 数据泄露 四合一

用法:
    python3 security_gateway.py --port 8800 --mock
"""

import json
import os, time, checker_registry, sys, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# 加载四个安全模块
from hallucination_detector import HallucinationDetector
from bias_detector import BiasDetector
from content_filter import ContentFilter
from leak_scanner import LeakScanner
from observability_platform import MetricsCollector, AlertEngine, ReportGenerator, AuditMetric
from audit_trail import AuditTrail, ComplianceReport, AccessControl, CertificationChecklist
from security_hardener import InputValidator, RateLimiter, IPBlocker, SecurityHeaders, SecurityAuditor
from production_guard import (RequestValidator, TieredRateLimiter, ExponentialBlocker,
    SecurityLogger, SecurityLogEntry, DoSGuard, APIKeyManager)


class SecurityGateway:
    """四合一安全网关"""

    def __init__(self):
        self.hallucination = HallucinationDetector()
        self.bias = BiasDetector()
        self.content = ContentFilter()
        self.leak = LeakScanner()
        # 可观测性
        self.metrics = MetricsCollector()
        self.alerts = AlertEngine()
        self.reporter = ReportGenerator(self.metrics, self.alerts)
        self.audit_trail = AuditTrail()
        self.access = AccessControl()
        self.certification = CertificationChecklist()
        self.validator = InputValidator()
        self.rate_limiter = TieredRateLimiter()
        self.ip_blocker = ExponentialBlocker()
        self.key_manager = APIKeyManager()
        self.sec_logger = SecurityLogger()

    def audit(self, text: str) -> dict:
        """全面安全审计，返回统一报告"""
        report = {
            "status": "safe",
            "text": text[:200],
            "timestamp": time.time(),
            "checks": {},
        }

        # 1. 数据泄露扫描（最高优先级 — 阻止泄露）
        leak_results = self.leak.scan(text)
        critical_leaks = [r for r in leak_results if r.confidence >= 0.9]
        report["checks"]["leak"] = {
            "passed": len(critical_leaks) == 0,
            "findings": len(leak_results),
            "details": [{"category": r.category, "masked": r.masked,
                         "confidence": r.confidence} for r in leak_results[:5]],
        }
        if critical_leaks:
            report["status"] = "blocked"
            report["reason"] = f"检测到 {len(critical_leaks)} 处敏感信息泄露"

        # 2. 有害内容（高优先级 — 阻止违规）
        block, content_reasons = self.content.should_block(text)
        all_content = self.content.scan(text)
        report["checks"]["content"] = {
            "passed": not block,
            "findings": len(all_content),
            "details": [{"category": r.category, "label": r.label,
                         "severity": r.severity} for r in all_content],
        }
        if block and report["status"] == "safe":
            report["status"] = "blocked"
            report["reason"] = f"检测到违规内容: {content_reasons[0].label}"

        # 3. 偏见检测
        bias_results = self.bias.scan(text)
        high_bias = [r for r in bias_results if r.severity == "high"]
        report["checks"]["bias"] = {
            "passed": len(high_bias) == 0,
            "findings": len(bias_results),
            "details": [{"category": r.category, "pattern": r.pattern,
                         "severity": r.severity} for r in bias_results[:5]],
        }
        if high_bias and report["status"] == "safe":
            report["status"] = "warning"
            report["reason"] = f"检测到 {len(high_bias)} 处高风险偏见"

        # 4. 幻觉检测
        h_result = self.hallucination.analyze(text)
        report["checks"]["hallucination"] = {
            "passed": h_result.hallucination_ratio < 0.5,
            "ratio": round(h_result.hallucination_ratio, 2),
            "overall_score": round(h_result.overall_score, 2),
            "details": [{"claim": r.claim[:60], "verdict": r.verdict,
                         "confidence": r.confidence} for r in h_result.results[:5]],
            "predictive_processing": getattr(h_result, "predictive_processing", {}),
        }
        if h_result.hallucination_ratio > 0.3 and report["status"] == "safe":
            report["status"] = "warning"
            report["reason"] = f"幻觉率 {h_result.hallucination_ratio:.0%}，建议人工复核"

        # 记录可观测性指标
        self.metrics.record(AuditMetric(
            timestamp=time.time(),
            status=report["status"],
            latency_ms=0,
            text_length=len(text) if isinstance(text, str) else 0,
            leak_count=len(leak_results),
            content_count=len(all_content),
            bias_count=len(bias_results),
            hallucination_ratio=h_result.hallucination_ratio,
        ))
        return report


class GatewayHandler(BaseHTTPRequestHandler):
    gateway = SecurityGateway()

    def do_POST(self):
        if self.path in ("/v1/audit", "/audit"):
            self._handle_audit()
        elif self.path in ("/v1/chat/completions", "/chat"):
            self._handle_chat()
        else:
            self._json(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/health":
            stats = {
                "status": "ok",
                "modules": ["hallucination", "bias", "content_filter", "leak_scanner"],
                "hallucination_checkers": len(checker_registry.Checker.registry) if hasattr(self.gateway.hallucination, 'anchor') else 14,
                "bias_patterns": self.gateway.bias.stats,
                "content_patterns": self.gateway.content.stats,
                "leak_scanners": self.gateway.leak.stats,
            "security_score": SecurityAuditor.audit_codebase(str(ROOT)),
            }
            self._json(200, stats)
        elif self.path == "/":
            self._serve_index()
        elif self.path.startswith("/obs"):
            self._handle_obs()
        elif self.path.startswith("/audit"):
            self._handle_audit_endpoints()
        elif self.path.startswith("/admin"):
            self._handle_admin()
        else:
            self._json(404, {"error": "not found"})

    def _handle_audit(self):
        # IP 封禁检查
        client_ip = self.client_address[0]
        if self.gateway.ip_blocker.is_blocked(client_ip):
            self._json(403, {"error": "IP 已被封禁"})
            return
        # 速率限制
        api_key = self.headers.get("Authorization", "anonymous")
        ok, msg = self.gateway.rate_limiter.allow(api_key)
        if not ok:
            self._json(429, {"error": msg})
            return
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)
        # JSON Bomb + 深度检测
        ok, msg = RequestValidator.validate_json(raw_body)
        if not ok:
            self.gateway.ip_blocker.record_failure(client_ip)
            self._json(413 if "超限" in msg else 400, {"error": msg})
            return
        try:
            body = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError) as e:
            self.gateway.ip_blocker.record_failure(client_ip)
            self._json(400, {"error": f"JSON 解析失败"})
            return
        text = body.get("text", body.get("messages", [{}])[-1].get("content", ""))
        # 输入校验
        valid, msg = self.gateway.validator.validate_text(text)
        if not valid:
            self._json(400, {"error": msg})
            return
        text = self.gateway.validator.sanitize(text)
        # Prompt 注入检测
        ok, msg = RequestValidator.validate_prompt(text)
        if not ok:
            self._json(400, {"error": msg})
            return
        report = self.gateway.audit(text)
        # 写入审计日志
        api_key = self.headers.get("Authorization", "anonymous")[:30]
        self.gateway.audit_trail.record("audit_request", api_key,
            "security_audit", report["status"])
        # 安全日志
        self.gateway.sec_logger.log(SecurityLogEntry(
            time.time(), client_ip, api_key, "/v1/audit", "POST",
            length, 0, 0, 200 if report["status"] == "safe" else 403,
            self.headers.get("User-Agent", ""), "free", len(text)//3))
        self._json(200 if report["status"] != "blocked" else 403, report)

    def _handle_chat(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        text = body.get("messages", [{}])[-1].get("content", "")
        report = self.gateway.audit(text)
        response = {
            "id": f"secure-{int(time.time())}",
            "object": "chat.completion",
            "model": "security-gateway",
            "choices": [{"message": {"role": "assistant",
                        "content": self._response_text(report)}}],
            "_security": report,
        }
        self._json(200, response)

    def _response_text(self, report: dict) -> str:
        status = report["status"]
        if status == "blocked":
            return f"[已拦截] {report.get('reason', '内容违规')}"
        elif status == "warning":
            return f"[⚠️ 警告] {report.get('reason', '内容可能存在问题')}"
        return "✅ 内容安全审计通过"

    def _json(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8800")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())

    def _handle_obs(self):
        if not self._check_admin_auth():
            return
        path = self.path
        gw = self.gateway
        if path == "/obs/snapshot":
            snap = gw.metrics.snapshot(3600)
            triggered = gw.alerts.evaluate(snap)
            snap["alerts"] = triggered
            self._json(200, snap)
        elif path == "/obs/trend":
            self._json(200, {"trend": gw.metrics.hourly_trend(24)})
        elif path == "/obs/report/daily":
            self._json(200, {"report": gw.reporter.daily_report()})
        elif path == "/obs/report/weekly":
            self._json(200, {"report": gw.reporter.weekly_report()})
        elif path == "/obs/report/json":
            self._json(200, gw.reporter.to_json())
        elif path == "/obs/alerts":
            self._json(200, {"alerts": gw.alerts.history})
        else:
            self._json(404, {"error": "unknown obs endpoint"})


    _auth_failures = {}  # ip → (count, first_fail_time)

    def _check_admin_auth(self) -> bool:
        """TM-017: 管理端点认证 — Bearer token + 暴力破解防护"""
        admin_key = os.getenv("ADMIN_API_KEY", "")
        if not admin_key:
            return False
        client_ip = self.client_address[0]
        now = time.time()
        # 检查是否已被临时封禁
        if client_ip in self._auth_failures:
            count, first = self._auth_failures[client_ip]
            if count >= 10 and now - first < 300:
                self._json(429, {"error": "too many auth attempts, retry later"})
                return False
            if now - first > 300:
                del self._auth_failures[client_ip]
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] == admin_key:
            self._auth_failures.pop(client_ip, None)
            return True
        # 记录失败
        prev = self._auth_failures.get(client_ip, (0, now))
        self._auth_failures[client_ip] = (prev[0] + 1, prev[1])
        self._json(401, {"error": "unauthorized"})
        return False

    def _handle_admin(self):
        if not self._check_admin_auth():
            return
        gw = self.gateway
        if self.path == "/admin/keys":
            self._json(200, gw.key_manager.stats)
        elif self.path == "/admin/logs":
            self._json(200, {"entries": [{"ip":e.ip,"key":e.api_key[:8],"status":e.status_code,"duration":e.duration_ms} for e in gw.sec_logger.query(limit=50)]})
        elif self.path == "/admin/security":
            self._json(200, {"limits": {"max_json":1000000,"max_depth":20,"max_prompt":32000,"max_context":128000,"max_output":8192}})
        else:
            self._json(404, {"error": "unknown admin endpoint"})

    def _handle_audit_endpoints(self):
        if not self._check_admin_auth():
            return
        path = self.path
        gw = self.gateway
        if path == "/audit/log":
            self._json(200, {"entries": gw.audit_trail.query(hours=24, limit=50)})
        elif path == "/audit/integrity":
            ok, msg = gw.audit_trail.verify_integrity()
            self._json(200, {"integrity": ok, "message": msg})
        elif path == "/audit/report":
            report = ComplianceReport(gw.audit_trail).generate("24h")
            self._json(200, report)
        elif path == "/audit/compliance":
            self._json(200, gw.certification.evaluate())
        else:
            self._json(404, {"error": "unknown audit endpoint"})

    def _serve_index(self):
        html = """<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<title>AI 安全网关</title><style>
body{font-family:sans-serif;max-width:800px;margin:2rem auto;padding:1rem;background:#0f172a;color:#e2e8f0}
h1{background:linear-gradient(90deg,#60a5fa,#a78bfa,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#1e293b;border-radius:8px;padding:1.5rem;margin:1rem 0;border:1px solid #334155}
.badge{padding:2px 8px;border-radius:10px;font-size:.75rem}
.green{background:rgba(34,197,94,.2);color:#22c55e}
.red{background:rgba(239,68,68,.2);color:#ef4444}
.yellow{background:rgba(245,158,11,.2);color:#f59e0b}
pre{background:#0d1117;padding:1rem;border-radius:4px;overflow-x:auto}
</style></head><body>
<h1>🛡️ AI 安全网关</h1>
<p>幻觉检测 + 偏见识别 + 有害内容过滤 + 数据泄露扫描 — 四合一</p>
<div class="card"><h3>API 端点</h3>
<pre>POST /v1/audit          — 完整安全审计
POST /v1/chat/completions — OpenAI 兼容 + 安全检测
GET  /health            — 健康检查</pre></div>
<div class="card"><h3>快速测试</h3>
<pre>curl -X POST http://localhost:8800/v1/audit \\
  -H "Content-Type: application/json" \\
  -d '{"text":"测试文本"}'</pre></div>
<div class="card"><h3>安全模块</h3>
<p>🔍 <b>幻觉检测</b> — 14 检查器 + 608 事实库</p>
<p>⚖️ <b>偏见检测</b> — 性别/地域/年龄/职业 4 维度</p>
<p>🚫 <b>内容过滤</b> — 暴力/色情/违法/自残/仇恨 5 类</p>
<p>🔐 <b>泄露扫描</b> — 手机号/身份证/银行卡/邮箱/IP/密钥</p>
</div></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI 安全网关")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), GatewayHandler)
    print(f"🛡️  AI 安全网关 v1.0")
    print(f"  地址: http://localhost:{args.port}")
    print(f"  审计: POST /v1/audit")
    print(f"  健康: GET  /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 关闭")


if __name__ == "__main__":
    main()
