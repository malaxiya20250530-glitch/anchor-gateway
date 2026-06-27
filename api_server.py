#!/usr/bin/env python3
"""
Anchor API 服务 — POST /verify 事实核查

用法:
  python3 api_server.py                     # 默认端口 8801
  python3 api_server.py --port 8900         # 自定义端口
  python3 api_server.py --no-metrics        # 禁用指标收集

接口:
  POST /verify        单条验证
  POST /verify/batch  批量验证
  GET  /health        健康检查
  GET  /metrics       可观测性指标
"""

import json, sys, time, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from hallucination_detector import HallucinationDetector
from checker_registry import Checker
import checker_classes


# ── 指标收集器 ──────────────────────────
class MetricsCollector:
    """线程安全的指标收集器 (单进程模式无需锁)"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time = time.time()
        self.total_requests = 0
        self.verify_count = 0
        self.batch_count = 0
        self.total_latency_ms = 0.0
        self.kb_hits = 0
        self.checker_hits = {}
        self.verdict_counts = {"contradicted": 0, "verified": 0, "uncertain": 0, "unverifiable": 0}
        self.errors = 0

    def record(self, verdict: str, latency_ms: float, vote_details: dict, kb_used: bool):
        self.total_requests += 1
        self.total_latency_ms += latency_ms
        self.verdict_counts[verdict] = self.verdict_counts.get(verdict, 0) + 1
        if kb_used:
            self.kb_hits += 1
        for vote in vote_details.get("votes", []):
            name = vote["checker"]
            if name not in self.checker_hits:
                self.checker_hits[name] = 0
            self.checker_hits[name] += 1

    def snapshot(self) -> dict:
        uptime = time.time() - self.start_time
        total = max(self.total_requests, 1)
        return {
            "uptime_seconds": round(uptime, 1),
            "total_requests": self.total_requests,
            "verify_calls": self.verify_count,
            "batch_calls": self.batch_count,
            "avg_latency_ms": round(self.total_latency_ms / total, 1),
            "kb_hit_rate": round(self.kb_hits / total, 3),
            "verdict_distribution": self.verdict_counts,
            "checker_usage": self.checker_hits,
            "errors": self.errors,
        }


# ── API 处理器 ──────────────────────────
detector = HallucinationDetector()
metrics = MetricsCollector()


class VerifyHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def log_message(self, format, *args):
        """简洁日志"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, indent=2)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8800")
        self.send_header("Content-Length", str(len(body.encode())))
        self.end_headers()
        self.wfile.write(body.encode())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/verify":
            self._handle_verify()
        elif path == "/verify/batch":
            self._handle_batch()
        else:
            self._send_json({"error": "not found"}, 404)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self._send_json({
                "status": "healthy",
                "checker_count": len(Checker.registry),
                "kb_entries": len(__import__('hallucination_detector').KNOWLEDGE_BASE),
            })
        elif path == "/metrics":
            self._send_json(metrics.snapshot())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        """CORS 预检"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8800")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle_verify(self):
        try:
            body = self._read_body()
            text = body.get("text", "")
            if not text:
                self._send_json({"error": "缺少 text 字段"}, 400)
                return

            metrics.verify_count += 1
            t0 = time.time()
            report = detector.analyze(text)
            elapsed = (time.time() - t0) * 1000

            # 提取投票明细
            vote_details = {"votes": [], "hallucination_score": 0.0}
            kb_used = False
            overall_verdict = "unverifiable"
            overall_confidence = 0.0
            if report.results:
                # 取第一个有意义的裁决
                for r in report.results:
                    if r.verdict != "unverifiable":
                        overall_verdict = r.verdict
                        overall_confidence = r.confidence
                        kb_used = r.anchor_type == "knowledge_base"
                        # 获取投票明细
                        details = detector.anchor.get_vote_details()
                        if details.get("votes"):
                            vote_details = details
                        break

            metrics.record(overall_verdict, elapsed, vote_details, kb_used)

            response = {
                "text": text,
                "verdict": overall_verdict,
                "confidence": overall_confidence,
                "hallucination_score": vote_details.get("hallucination_score", 0.0),
                "hallucination_ratio": report.hallucination_ratio,
                "overall_score": report.overall_score,
                "claims": [],
                "warnings": report.warnings,
                "vote_details": vote_details,
            }

            for r in report.results:
                response["claims"].append({
                    "text": r.claim,
                    "verdict": r.verdict,
                    "confidence": r.confidence,
                    "evidence": r.evidence[:200] if r.evidence else "",
                    "source": r.source,
                    "anchor_type": r.anchor_type,
                })

            self._send_json(response)

        except json.JSONDecodeError:
            self._send_json({"error": "无效的 JSON"}, 400)
        except Exception as e:
            metrics.errors += 1
            self._send_json({"error": "内部服务错误"}, 500)

    def _handle_batch(self):
        try:
            body = self._read_body()
            texts = body.get("texts", [])
            if not texts or not isinstance(texts, list):
                self._send_json({"error": "缺少 texts 数组"}, 400)
                return
            if len(texts) > 50:
                texts = texts[:50]  # 硬限制

            metrics.batch_count += 1
            results = []
            for text in texts[:50]:  # 限制批量50条
                t0 = time.time()
                result = detector.check(text)
                elapsed = (time.time() - t0) * 1000
                results.append({
                    "text": text,
                    "verdict": result.overall_verdict,
                    "confidence": result.overall_confidence,
                    "latency_ms": round(elapsed, 1),
                })

            self._send_json({"results": results, "count": len(results)})

        except json.JSONDecodeError:
            self._send_json({"error": "无效的 JSON"}, 400)
        except Exception as e:
            metrics.errors += 1
            self._send_json({"error": "内部服务错误"}, 500)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Anchor API 服务")
    parser.add_argument("--port", type=int, default=8801, help="监听端口")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--no-metrics", action="store_true", help="禁用指标收集")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), VerifyHandler)
    print(f"""
╔══════════════════════════════════════╗
║  Anchor API 服务 v1.0              ║
╠══════════════════════════════════════╣
║  地址: http://{args.host}:{args.port}          ║
║  检查器: {len(Checker.registry)} 个                       ║
║  KB: {len(__import__('hallucination_detector').KNOWLEDGE_BASE)} 条目                    ║
╠══════════════════════════════════════╣
║  POST /verify        单条验证        ║
║  POST /verify/batch  批量验证        ║
║  GET  /health        健康检查        ║
║  GET  /metrics       可观测性指标    ║
╚══════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹  服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
