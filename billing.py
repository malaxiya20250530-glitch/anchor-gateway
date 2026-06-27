#!/usr/bin/env python3
"""
API 计费模块 — API Key 管理 + 按量计费 + 套餐分级
纯 Python 标准库，JSON 文件持久化
"""

import json, os, time, hashlib, secrets, threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

BILLING_DB = Path(__file__).parent / "billing.json"
_lock = threading.Lock()


# ============ 套餐定义 ============
@dataclass
class Plan:
    name: str
    monthly_quota: int       # 月免费 token 数，0=无限
    rate_limit_rps: float    # 每秒请求数
    price_monthly: float     # 月费 (CNY)

PLANS = {
    "free":       Plan("免费版",   10_000,   2.0,  0),
    "basic":      Plan("基础版",  100_000,   5.0,  29),
    "pro":        Plan("专业版",  1_000_000, 20.0, 199),
    "enterprise": Plan("企业版",  0,         50.0, 999),
}


# ============ 账户模型 ============
@dataclass
class Account:
    api_key: str
    name: str
    plan: str = "free"
    tokens_used: int = 0
    requests: int = 0
    created_at: float = field(default_factory=time.time)
    last_reset: float = field(default_factory=time.time)
    active: bool = True

    def remaining(self) -> int:
        quota = PLANS[self.plan].monthly_quota
        if quota == 0:
            return 999_999_999
        return max(0, quota - self.tokens_used)

    def monthly_reset(self):
        now = time.time()
        if now - self.last_reset > 30 * 86400:
            self.tokens_used = 0
            self.last_reset = now


# ============ 计费引擎 ============
class BillingEngine:
    def __init__(self, db_path: Path = BILLING_DB):
        self.db_path = db_path
        self.accounts: dict = {}
        self._load()

    def _load(self):
        if self.db_path.exists():
            try:
                with open(self.db_path) as f:
                    raw = json.load(f)
                self.accounts = {k: Account(**v) for k, v in raw.items()}
            except Exception:
                self.accounts = {}

    def _save(self):
        with _lock:
            tmp = self.db_path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump({k: asdict(v) for k, v in self.accounts.items()},
                          f, ensure_ascii=False, indent=2)
            tmp.replace(self.db_path)

    # ---- API Key 管理 ----

    def create_key(self, name: str, plan: str = "free") -> str:
        """生成新的 API Key，返回 key 字符串"""
        with _lock:
            raw = secrets.token_hex(16)
            prefix = {"free": "sk-f", "basic": "sk-b", "pro": "sk-p",
                      "enterprise": "sk-e"}.get(plan, "sk-x")
            api_key = f"{prefix}{raw}"
            self.accounts[api_key] = Account(api_key=api_key, name=name, plan=plan)
            self._save()
            return api_key

    def validate(self, api_key: str) -> Optional[Account]:
        """验证 API Key，返回账户或 None"""
        acc = self.accounts.get(api_key)
        if not acc or not acc.active:
            return None
        acc.monthly_reset()
        return acc

    def revoke(self, api_key: str):
        """吊销 API Key"""
        with _lock:
            if api_key in self.accounts:
                self.accounts[api_key].active = False
                self._save()

    # ---- 用量计费 ----

    def charge(self, api_key: str, tokens: int) -> dict:
        """
        扣费并返回计费结果 (TM-016: 完整加锁防止 TOCTOU 竞态)
        返回: {"allowed": bool, "remaining": int, "plan": str, "rate_limit": float}
        """
        with _lock:
            acc = self.validate(api_key)
            if not acc:
                return {"allowed": False, "reason": "invalid_key",
                        "remaining": 0, "plan": "none", "rate_limit": 0}

            # TM-003: 拒绝负数/零 tokens 防止计费绕过
            if tokens <= 0:
                return {"allowed": False, "reason": "invalid_tokens",
                        "remaining": acc.remaining(), "plan": acc.plan,
                        "rate_limit": PLANS[acc.plan].rate_limit_rps}

            remaining = acc.remaining()
            if tokens > remaining:
                return {"allowed": False, "reason": "quota_exceeded",
                        "remaining": remaining, "plan": acc.plan,
                        "rate_limit": PLANS[acc.plan].rate_limit_rps}

            acc.tokens_used += tokens
            acc.requests += 1
            self._save()

            return {"allowed": True, "reason": "ok",
                    "remaining": acc.remaining(),
                    "plan": acc.plan,
                    "rate_limit": PLANS[acc.plan].rate_limit_rps,
                    "tokens_used": acc.tokens_used,
                    "requests": acc.requests}

    # ---- 统计 ----

    @property
    def stats(self) -> dict:
        total = len(self.accounts)
        active = sum(1 for a in self.accounts.values() if a.active)
        by_plan = {}
        revenue = 0.0
        for a in self.accounts.values():
            by_plan[a.plan] = by_plan.get(a.plan, 0) + 1
            revenue += PLANS[a.plan].price_monthly
        return {
            "total_accounts": total,
            "active_accounts": active,
            "by_plan": by_plan,
            "mrr_estimate": revenue,
        }


# ============ 计费中间件（集成到 awareness_gateway） ============

class BillingMiddleware:
    """HTTP 中间件：拦截请求 → 验证 Key → 计费 → 注入响应头"""

    def __init__(self, engine: BillingEngine = None):
        self.engine = engine or BillingEngine()

    def process_request(self, headers: dict, estimated_tokens: int = 0) -> dict:
        """
        处理请求前调用
        返回: {"status": "ok"|"blocked", "account": Account|None, "headers": dict}
        """
        auth = headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            api_key = auth[7:]
        elif auth.startswith("sk-"):
            api_key = auth
        else:
            return {"status": "blocked", "reason": "missing_key",
                    "account": None,
                    "headers": {"X-Billing-Reason": "missing_api_key"}}

        charge = self.engine.charge(api_key, estimated_tokens)
        if not charge["allowed"]:
            return {"status": "blocked", "reason": charge["reason"],
                    "account": None,
                    "headers": {
                        "X-Billing-Reason": charge["reason"],
                        "X-RateLimit-Limit": str(charge["rate_limit"]),
                        "X-Billing-Plan": charge["plan"],
                    }}

        return {"status": "ok", "reason": "ok",
                "account": self.engine.validate(api_key),
                "headers": {
                    "X-Billing-Plan": charge["plan"],
                    "X-Billing-Remaining": str(charge["remaining"]),
                    "X-RateLimit-Limit": str(charge["rate_limit"]),
                }}

    def process_response(self, api_key: str, actual_tokens: int):
        """响应后补充计费（校准实际 token 数）"""
        if api_key:
            self.engine.charge(api_key, max(0, actual_tokens - self._estimated.get(api_key, 0)))


# ============ CLI 管理工具 ============

def main():
    import sys
    engine = BillingEngine()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "create":
        name = sys.argv[2] if len(sys.argv) > 2 else "default"
        plan = sys.argv[3] if len(sys.argv) > 3 else "free"
        key = engine.create_key(name, plan)
        print(f"✅ 已创建 {plan} 账户: {name}")
        print(f"   API Key: {key}")

    elif cmd == "revoke":
        key = sys.argv[2]
        engine.revoke(key)
        print(f"✅ 已吊销: {key[:12]}...")

    elif cmd == "list":
        print(f"{'Key':<20} {'名称':<15} {'套餐':<10} {'用量':<10} {'状态'}")
        print("-" * 70)
        for k, a in sorted(engine.accounts.items(), key=lambda x: -x[1].created_at):
            status = "✅" if a.active else "⛔"
            print(f"{k[:18]:<20} {a.name:<15} {a.plan:<10} {a.tokens_used:<10} {status}")

    elif cmd == "stats":
        s = engine.stats
        print("📊 计费统计")
        print(f"   总账户: {s['total_accounts']}")
        print(f"   活跃: {s['active_accounts']}")
        print(f"   分布: {s['by_plan']}")
        print(f"   MRR 预估: ¥{s['mrr_estimate']:.0f}/月")

    else:
        print("用法: python3 billing.py [create|revoke|list|stats]")


if __name__ == "__main__":
    main()
