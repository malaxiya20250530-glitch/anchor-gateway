#!/usr/bin/env python3
"""Cloudflare WAF 集成 — IP 列表同步 / 防火墙规则 / 速率限制。

通过 Cloudflare API 管理:
  - IP 访问列表（允许/阻止）
  - WAF 自定义规则
  - 速率限制规则
  - 防火墙事件查询

用法:
    from cloudflare_waf import CloudflareWAF

    cf = CloudflareWAF(zone_id="xxx", api_token="xxx")

    # 封禁 IP
    cf.block_ip("1.2.3.4", note="SQL 注入攻击")

    # 同步本机 WAF 拦截的 IP 到 Cloudflare
    cf.sync_blocked_ips(["1.2.3.4", "5.6.7.8"])

    # 创建速率限制规则
    cf.create_rate_limit("/v1/chat", threshold=100, period=60)
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional

from secrets_backend import get_secret
from security_logger import get_security_logger


class CloudflareWAF:
    """Cloudflare API 客户端 — WAF / IP 列表 / 规则管理"""

    def __init__(self, zone_id: str = "", api_token: str = "",
                 email: str = "", api_key: str = ""):
        self._zone = zone_id or get_secret("CLOUDFLARE_ZONE_ID") or ""
        self._token = api_token or get_secret("CLOUDFLARE_API_TOKEN") or ""
        self._email = email or get_secret("CLOUDFLARE_EMAIL") or ""
        self._api_key = api_key or get_secret("CLOUDFLARE_API_KEY") or ""
        self._base = "https://api.cloudflare.com/client/v4"
        self._slog = get_security_logger()

    def _headers(self) -> dict:
        if self._token:
            return {"Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json"}
        return {"X-Auth-Email": self._email,
                "X-Auth-Key": self._api_key,
                "Content-Type": "application/json"}

    def _request(self, method: str, path: str, body: dict = None) -> dict:
        """发送 API 请求"""
        url = f"{self._base}/{path.lstrip('/')}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(),
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()[:500]
            self._slog.error(event="cloudflare_api_error",
                             message=f"{method} {path}: {e.code} {error_body}")
            return {"success": False, "errors": [{"message": str(e)}]}

    # ── IP 访问列表 ─────────────────────────────

    def list_ip_rules(self, list_type: str = "block") -> list[dict]:
        """列出 IP 访问规则。

        list_type: "block" / "allow" / "challenge"
        """
        path = f"zones/{self._zone}/firewall/access_rules/rules"
        params = f"?mode={list_type}&per_page=100"
        resp = self._request("GET", path + params)
        return resp.get("result", [])

    def block_ip(self, ip: str, note: str = "") -> dict:
        """封禁 IP"""
        body = {
            "mode": "block",
            "configuration": {"target": "ip", "value": ip},
            "notes": note or f"自动封禁 {time.strftime('%Y-%m-%d %H:%M:%S')}",
        }
        resp = self._request("POST", f"zones/{self._zone}/firewall/access_rules/rules", body)
        if resp.get("success"):
            self._slog.security_alert(ip=ip, threat_type="cloudflare_block",
                                      action="blocked", detail=note)
        return resp

    def unblock_ip(self, ip: str) -> dict:
        """解封 IP"""
        # 先查找规则 ID
        rules = self.list_ip_rules("block")
        for rule in rules:
            cfg = rule.get("configuration", {})
            if cfg.get("target") == "ip" and cfg.get("value") == ip:
                rule_id = rule["id"]
                resp = self._request("DELETE",
                                     f"zones/{self._zone}/firewall/access_rules/rules/{rule_id}")
                if resp.get("success"):
                    self._slog.audit(action="cloudflare_unblock", subject=ip)
                return resp
        return {"success": False, "errors": [{"message": f"未找到 IP {ip} 的封禁规则"}]}

    def sync_blocked_ips(self, ips: list[str], note: str = "") -> dict:
        """批量同步封禁 IP 到 Cloudflare（跳过已封禁的）"""
        existing = {r.get("configuration", {}).get("value")
                    for r in self.list_ip_rules("block")}
        results = {"blocked": [], "skipped": []}
        for ip in ips:
            if ip in existing:
                results["skipped"].append(ip)
            else:
                self.block_ip(ip, note=note)
                results["blocked"].append(ip)
                time.sleep(0.3)  # API 速率限制
        return results

    # ── WAF 规则包 ──────────────────────────────

    def list_waf_packages(self) -> list[dict]:
        """列出 WAF 规则包"""
        resp = self._request("GET", f"zones/{self._zone}/firewall/waf/packages")
        return resp.get("result", [])

    def get_waf_anomaly_score(self, package_id: str = "") -> dict:
        """获取 WAF 异常分数阈值设置"""
        if not package_id:
            packages = self.list_waf_packages()
            package_id = packages[0]["id"] if packages else ""
        if not package_id:
            return {"success": False}
        resp = self._request("GET",
                             f"zones/{self._zone}/firewall/waf/packages/{package_id}")
        result = resp.get("result", {})
        return {
            "sensitivity": result.get("sensitivity", "unknown"),
            "action_mode": result.get("action_mode", "unknown"),
        }

    def set_waf_mode(self, mode: str, package_id: str = "") -> dict:
        """设置 WAF 模式。

        mode: "on" (阻止) / "simulate" (模拟) / "off" (关闭)
        """
        if not package_id:
            packages = self.list_waf_packages()
            package_id = packages[0]["id"] if packages else ""
        if not package_id:
            return {"success": False, "errors": [{"message": "未找到 WAF 规则包"}]}
        return self._request("PATCH",
                             f"zones/{self._zone}/firewall/waf/packages/{package_id}",
                             {"action_mode": mode if mode in ("on", "simulate") else "simulate"})

    # ── 速率限制 ────────────────────────────────

    def create_rate_limit(self, path: str, threshold: int = 100,
                          period: int = 60, action: str = "block") -> dict:
        """创建速率限制规则。

        Args:
            path: 匹配的 URL 路径（如 "/v1/chat"）
            threshold: 周期内最大请求数
            period: 周期（秒），支持 10/60/120
            action: "block" / "challenge" / "js_challenge"
        """
        body = {
            "match": {"request": {"methods": ["POST"],
                                  "url": f"*{path}*"}},
            "threshold": threshold,
            "period": period,
            "action": {"mode": action,
                       "timeout": 60 if action == "block" else None},
        }
        resp = self._request("POST", f"zones/{self._zone}/rate_limits", body)
        if resp.get("success"):
            self._slog.audit(action="cloudflare_rate_limit", subject=path,
                             detail=f"threshold={threshold}/{period}s")
        return resp

    def list_rate_limits(self) -> list[dict]:
        """列出所有速率限制规则"""
        resp = self._request("GET", f"zones/{self._zone}/rate_limits")
        return resp.get("result", [])

    # ── 防火墙事件 ──────────────────────────────

    def get_firewall_events(self, limit: int = 50,
                            action: str = "", hours: int = 1) -> list[dict]:
        """查询最近的防火墙事件。

        Args:
            limit: 最大返回数
            action: 过滤动作（"block" / "challenge" / "log"）
            hours: 时间范围（小时）
        """
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                              time.gmtime(time.time() - hours * 3600))
        path = f"zones/{self._zone}/security/events?limit={limit}&since={since}"
        if action:
            path += f"&action={action}"
        resp = self._request("GET", path)
        return resp.get("result", [])

    def get_top_attacker_ips(self, hours: int = 24, limit: int = 10) -> list[dict]:
        """获取 Top N 攻击 IP"""
        events = self.get_firewall_events(limit=500, action="block", hours=hours)
        ip_counts = {}
        for ev in events:
            ip = ev.get("ip", "unknown")
            ip_counts[ip] = ip_counts.get(ip, 0) + 1
        return sorted(
            [{"ip": k, "count": v} for k, v in ip_counts.items()],
            key=lambda x: x["count"], reverse=True
        )[:limit]

    # ── 验证 ────────────────────────────────────

    def verify_token(self) -> dict:
        """验证 API Token 是否有效"""
        resp = self._request("GET", "user/tokens/verify")
        return resp
