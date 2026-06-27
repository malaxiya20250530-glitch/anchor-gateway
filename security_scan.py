#!/usr/bin/env python3
"""OWASP 式自动化安全扫描 — SQL注入/XSS/路径穿越/认证绕过/JWT攻击。

纯 Python 标准库实现，零外部依赖。
涵盖 OWASP Top 10 核心向量。

用法:
    python3 security_scan.py                    # 全部扫描
    python3 security_scan.py --category sqli    # 仅 SQL 注入
    python3 security_scan.py --output scan.json # 导出报告
"""

import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

from security_logger import get_security_logger


# ═══════════════════════════════════════════════════════════
# 攻击载荷库
# ═══════════════════════════════════════════════════════════

PAYLOADS = {
    # SQL 注入 (OWASP A03:2021)
    "sqli": [
        ("基础注入", "' OR '1'='1"),
        ("UNION注入", "' UNION SELECT NULL--"),
        ("UNION多列", "' UNION SELECT NULL,NULL,NULL--"),
        ("注释绕过", "admin'--"),
        ("分号注入", "'; DROP TABLE users; --"),
        ("时间盲注", "1' AND SLEEP(5)--"),
        ("布尔盲注", "1' AND '1'='1"),
        ("堆叠查询", "1'; SELECT * FROM users; --"),
        ("编码绕过", "%27%20OR%20%271%27%3D%271"),
        ("Null字节", "admin'%00"),
        ("十六进制", "0x27204f5220313d31"),
        ("NoSQL注入", '{"$gt": ""}'),
        ("NoSQL $where", '{"$where": "1==1"}'),
    ],

    # XSS (OWASP A03:2021)
    "xss": [
        ("基础script", "<script>alert(1)</script>"),
        ("img onerror", '<img src=x onerror="alert(1)">'),
        ("svg onload", '<svg onload="alert(1)">'),
        ("javascript协议", "javascript:alert(1)"),
        ("iframe", '<iframe src="javascript:alert(1)">'),
        ("事件处理器", '<body onload="alert(1)">'),
        ("编码绕过", "&#x3C;script&#x3E;alert(1)&#x3C;/script&#x3E;"),
        ("大小写混合", "<ScRiPt>alert(1)</ScRiPt>"),
        ("data协议", "data:text/html,<script>alert(1)</script>"),
        ("CSS注入", '<div style="background:url(javascript:alert(1))">'),
    ],

    # 路径穿越 (OWASP A01:2021)
    "path_traversal": [
        ("基础穿越", "../../../etc/passwd"),
        ("编码穿越", "..%2f..%2f..%2fetc%2fpasswd"),
        ("双编码", "..%252f..%252fetc%252fpasswd"),
        ("Windows路径", "..\\..\\..\\windows\\system32"),
        ("绝对路径", "/etc/passwd"),
        ("Null字节", "../../../etc/passwd%00.jpg"),
        ("Unicode", "..%c0%af..%c0%afetc%c0%afpasswd"),
    ],

    # 认证绕过 (OWASP A07:2021)
    "auth_bypass": [
        ("空Token", ""),
        ("无效JWT", "Bearer invalid.jwt.token"),
        ("过期JWT", "Bearer eyJhbGciOiJub25lIn0.eyJleHAiOjE1MDAwMDAwMDB9."),
        ("无签名JWT", "Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9."),
        ("伪造kid", 'Bearer eyJhbGciOiJIUzI1NiIsImtpZCI6Ii4uLy4uLyJ9.xxx.yyy'),
        ("超长Token", "Bearer " + "A" * 10000),
        ("特殊字符", "Bearer <script>"),
    ],

    # 速率限制
    "rate_limit": [
        ("突发100", 100),
        ("突发500", 500),
    ],

    # 输入验证
    "input_validation": [
        ("超长输入", "A" * 100000),
        ("Unicode炸弹", "💣" * 10000),
        ("Null字节", "\x00" * 100),
        ("控制字符", "\x01\x02\x03\x04\x05"),
        ("JSON深层嵌套", json.dumps({"a": {"b": {"c": {"d": {"e": "f"}}}}})),
    ],
}


# ═══════════════════════════════════════════════════════════
# 扫描引擎
# ═══════════════════════════════════════════════════════════

class SecurityScanner:
    """自动化安全扫描器"""

    def __init__(self, target_url: str = "", local_mode: bool = True):
        self.url = target_url
        self.local = local_mode
        self._slog = get_security_logger()
        self.findings: list[dict] = []
        self._waf = None

    def _get_waf(self):
        if self._waf is None:
            from waf import WAF
            self._waf = WAF()
        return self._waf

    def scan_category(self, category: str) -> list[dict]:
        """扫描单个类别"""
        findings = []
        payloads = PAYLOADS.get(category, [])

        print(f"\n  [{category}] {len(payloads)} 个载荷...")

        for name, payload in payloads:
            if isinstance(payload, int):
                # 速率测试
                result = self._test_rate_limit(payload)
            else:
                result = self._test_payload(category, name, payload)

            findings.append(result)
            status = "🔴" if result.get("vulnerable") else "🟢"
            detail = result.get("detail", "")[:60]
            print(f"    {status} {name:20s} {detail}")

        return findings

    def _test_payload(self, category: str, name: str, payload: str) -> dict:
        """测试单个载荷"""
        finding = {
            "category": category,
            "name": name,
            "payload": payload[:200],
            "vulnerable": False,
            "detail": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if self.local:
            # 本地 WAF 模式
            waf = self._get_waf()
            result = waf.scan(payload, ip="127.0.0.1", endpoint="/v1/chat")

            if category in ("sqli", "xss", "path_traversal", "input_validation"):
                # 这些应该被 WAF 拦截
                if not result.blocked:
                    finding["vulnerable"] = True
                    finding["detail"] = f"WAF未拦截: {payload[:80]}"
                    finding["severity"] = "HIGH"
                else:
                    finding["detail"] = f"已拦截: {result.reason[:80]}"
                    finding["severity"] = "NONE"
            elif category == "auth_bypass":
                # 认证载荷应该被拒绝
                if payload and len(payload) < 10000:
                    finding["detail"] = "待手动验证"
                    finding["severity"] = "INFO"

        else:
            # HTTP 模式
            try:
                req = urllib.request.Request(
                    self.url, data=payload.encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status < 400:
                        finding["vulnerable"] = True
                        finding["detail"] = f"HTTP {resp.status}: 未拒绝恶意载荷"
                        finding["severity"] = "HIGH"
                    else:
                        finding["detail"] = f"已拒绝: HTTP {resp.status}"
            except urllib.error.HTTPError as e:
                finding["detail"] = f"已拒绝: HTTP {e.code}"
            except Exception as e:
                finding["detail"] = f"连接失败: {e}"

        if finding["vulnerable"]:
            self._slog.security_alert(
                ip="127.0.0.1", threat_type=category,
                action="vuln_found", detail=finding["detail"]
            )

        return finding

    def _test_rate_limit(self, count: int) -> dict:
        """测试速率限制"""
        finding = {
            "category": "rate_limit",
            "name": f"突发{count}请求",
            "payload": f"{count} requests",
            "vulnerable": False,
            "detail": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        from rate_limiter import TokenBucket
        rl = TokenBucket(rate=100, burst=100)
        allowed = 0
        blocked = 0
        for _ in range(count):
            if rl.acquire():
                allowed += 1
            else:
                blocked += 1

        if count > 100 and blocked == 0:
            finding["vulnerable"] = True
            finding["detail"] = f"速率限制未生效: {count}请求全部放行"
            finding["severity"] = "MEDIUM"
        else:
            finding["detail"] = f"速率限制正常: 放行{allowed}, 拦截{blocked}"
            finding["severity"] = "NONE"

        return finding

    def run_full_scan(self) -> dict:
        """执行完整安全扫描"""
        print(f"\n{'='*60}")
        print(f"  OWASP 安全扫描")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  模式: {'本地 WAF' if self.local else self.url}")
        print(f"{'='*60}")

        categories = ["sqli", "xss", "path_traversal", "auth_bypass",
                      "rate_limit", "input_validation"]

        all_findings = []
        for cat in categories:
            findings = self.scan_category(cat)
            all_findings.extend(findings)

        # 统计
        vulnerabilities = [f for f in all_findings if f.get("vulnerable")]
        by_severity = {}
        for f in vulnerabilities:
            sev = f.get("severity", "UNKNOWN")
            by_severity[sev] = by_severity.get(sev, 0) + 1

        report = {
            "scan_info": {
                "mode": "local" if self.local else f"remote:{self.url}",
                "categories": len(categories),
                "payloads": len(all_findings),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "summary": {
                "total_tests": len(all_findings),
                "vulnerabilities_found": len(vulnerabilities),
                "pass_rate": round((len(all_findings) - len(vulnerabilities))
                                   / max(len(all_findings), 1), 2),
                "by_severity": by_severity,
            },
            "findings": all_findings,
        }

        # 打印摘要
        print(f"\n{'='*60}")
        print(f"  扫描摘要")
        print(f"  {'─'*56}")
        print(f"  总测试: {report['summary']['total_tests']}")
        print(f"  漏洞: {report['summary']['vulnerabilities_found']}")
        print(f"  通过率: {report['summary']['pass_rate']*100:.0f}%")
        if by_severity:
            for sev, count in sorted(by_severity.items()):
                print(f"    {sev}: {count}")
        print(f"{'='*60}")

        return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description="OWASP 安全扫描")
    parser.add_argument("--url", default="", help="目标 URL")
    parser.add_argument("--category", choices=list(PAYLOADS.keys()),
                        help="仅扫描指定类别")
    parser.add_argument("--output", default="", help="输出 JSON 文件")
    args = parser.parse_args()

    scanner = SecurityScanner(target_url=args.url, local_mode=not bool(args.url))

    if args.category:
        findings = scanner.scan_category(args.category)
        report = {"findings": findings}
    else:
        report = scanner.run_full_scan()

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"报告已保存: {args.output}")


if __name__ == "__main__":
    main()
