#!/usr/bin/env python3
"""混沌工程 — 故障注入 & 恢复验证。

场景:
  1. LLM 上游超时 → 验证熔断器跳闸
  2. 数据库断开    → 验证降级策略
  3. Leader 失联   → 验证选主切换
  4. 高并发雪崩    → 验证背压限流
  5. 内存泄漏模拟  → 验证 OOM 保护

用法:
    python3 chaos_engineering.py --scenario all
    python3 chaos_engineering.py --scenario upstream_timeout
    python3 chaos_engineering.py --scenario leader_loss
"""

import json
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from security_logger import get_security_logger


# ═══════════════════════════════════════════════════════════
# 故障注入基类
# ═══════════════════════════════════════════════════════════

class ChaosScenario:
    """故障场景基类"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.start_time = 0.0
        self.results: dict = {}
        self._slog = get_security_logger()

    def setup(self):
        """场景准备"""
        pass

    def inject(self):
        """注入故障"""
        raise NotImplementedError

    def verify(self) -> dict:
        """验证系统行为是否符合预期"""
        raise NotImplementedError

    def cleanup(self):
        """清理"""
        pass

    def run(self) -> dict:
        """执行完整场景"""
        print(f"\n{'='*60}")
        print(f"  🔧 故障注入: {self.name}")
        print(f"  {self.description}")
        print(f"{'='*60}")

        self.start_time = time.time()
        try:
            self.setup()
            self.inject()
            time.sleep(2)  # 等待系统响应
            result = self.verify()
            result["scenario"] = self.name
            result["duration_sec"] = round(time.time() - self.start_time, 2)
            result["timestamp"] = datetime.now(timezone.utc).isoformat()

            status = "✅ PASS" if result.get("passed", False) else "❌ FAIL"
            print(f"  {status}  {self.name}")
            for k, v in result.items():
                if k not in ("scenario", "passed", "duration_sec", "timestamp"):
                    print(f"    {k}: {v}")

            self._slog.audit(
                action="chaos_test", subject=self.name,
                detail=f"{status}: {json.dumps(result, default=str)}"
            )
        except Exception as e:
            result = {"scenario": self.name, "passed": False,
                      "error": str(e), "duration_sec": round(time.time() - self.start_time, 2)}
            print(f"  ❌ ERROR  {self.name}: {e}")
        finally:
            self.cleanup()

        return result


# ═══════════════════════════════════════════════════════════
# 场景 1: LLM 上游超时
# ═══════════════════════════════════════════════════════════

class UpstreamTimeoutScenario(ChaosScenario):
    """模拟 LLM 上游响应超时 → 验证熔断器 + 重试逻辑"""

    def __init__(self):
        super().__init__("upstream_timeout", "LLM 上游连续超时 → 熔断器跳闸 → 恢复")

    def inject(self):
        from db_protection import CircuitBreaker
        self.cb = CircuitBreaker(name="llm_upstream", failure_threshold=3, reset_timeout=3)
        print("  注入: 连续 3 次超时...")
        for i in range(3):
            self.cb.record_failure()
            print(f"    失败 {i+1}/3 → 状态: {self.cb.state}")
        print(f"  熔断后: allow_request={self.cb.allow_request()}")

    def verify(self) -> dict:
        state_after = self.cb.state
        allow_after = self.cb.allow_request()
        # 等待冷却
        time.sleep(3.1)
        allow_cooled = self.cb.allow_request()
        state_cooled = self.cb.state
        # 恢复
        self.cb.record_success()
        state_final = self.cb.state

        return {
            "passed": (state_after == "open" and state_cooled == "half_open"
                       and state_final == "closed"),
            "injected_failures": 3,
            "state_after_inject": state_after,
            "allow_after_inject": allow_after,
            "state_after_cooldown": state_cooled,
            "allow_after_cooldown": allow_cooled,
            "state_after_recovery": state_final,
        }


# ═══════════════════════════════════════════════════════════
# 场景 2: 数据库连接断开
# ═══════════════════════════════════════════════════════════

class DatabaseDisconnectScenario(ChaosScenario):
    """模拟数据库断开 → 验证连接池超时 + 降级"""

    def __init__(self):
        super().__init__("database_disconnect", "数据库连接池耗尽 → 超时 → 降级响应")

    def inject(self):
        from db_protection import ConnectionPool
        self.pool = ConnectionPool(max_connections=1, timeout_sec=0.5)
        # 占满连接池
        def _hold():
            with self.pool.acquire():
                time.sleep(3)
        t = threading.Thread(target=_hold)
        t.start()
        time.sleep(0.1)
        print("  注入: 连接池已满 (1/1)")

    def verify(self) -> dict:
        timeout_detected = False
        try:
            with self.pool.acquire():
                pass
        except TimeoutError:
            timeout_detected = True
            print("  ✅ 正确触发 TimeoutError")

        stats = self.pool.stats
        return {
            "passed": timeout_detected and stats["utilization"] >= 0.5,
            "timeout_detected": timeout_detected,
            "pool_stats": stats,
        }


# ═══════════════════════════════════════════════════════════
# 场景 3: Leader 失联
# ═══════════════════════════════════════════════════════════

class LeaderLossScenario(ChaosScenario):
    """模拟主节点失联 → 验证选主切换"""

    def __init__(self):
        super().__init__("leader_loss", "Leader 锁过期 → 新节点选举")

    def setup(self):
        import shutil
        self._test_dir = os.path.expanduser("~/chaos_leader_test")
        shutil.rmtree(self._test_dir, ignore_errors=True)
        os.makedirs(self._test_dir, exist_ok=True)

    def inject(self):
        from ha_health import LeaderElection
        # 节点 1 获取 Leader
        self.le1 = LeaderElection(node_id="node-1", lock_dir=self._test_dir, ttl_sec=1)
        is_leader_1 = self.le1.is_leader()
        print(f"  注入: node-1 获取锁 → leader={is_leader_1}")
        # 等待 TTL 过期
        time.sleep(1.5)
        print(f"  等待 TTL 过期 (1.5s)...")
        # 节点 2 尝试获取
        self.le2 = LeaderElection(node_id="node-2", lock_dir=self._test_dir, ttl_sec=10)
        self.is_leader_2 = self.le2.is_leader()
        print(f"  node-2 选举: leader={self.is_leader_2}")

    def verify(self) -> dict:
        leader = self.le2.get_leader()
        return {
            "passed": self.is_leader_2 and leader == "node-2",
            "node1_was_leader": True,
            "node2_elected": self.is_leader_2,
            "current_leader": leader,
        }

    def cleanup(self):
        import shutil
        shutil.rmtree(self._test_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# 场景 4: 高并发雪崩
# ═══════════════════════════════════════════════════════════

class AvalancheScenario(ChaosScenario):
    """模拟高并发雪崩 → 验证背压 + 速率限制"""

    def __init__(self):
        super().__init__("avalanche", "突发 1000 并发 → 验证速率限制器不崩溃")

    def inject(self):
        from rate_limiter import TokenBucket as RateLimiter
        self.rl = RateLimiter(rate=100, burst=100)
        print("  注入: 突发 500 请求 (限制: 100/s)...")
        allowed = 0
        blocked = 0
        for i in range(500):
            if self.rl.acquire():
                allowed += 1
            else:
                blocked += 1
        self.allowed = allowed
        self.blocked = blocked
        print(f"  结果: 放行={allowed}, 拦截={blocked}")

    def verify(self) -> dict:
        total = self.allowed + self.blocked
        return {
            "passed": self.blocked > 0 and self.allowed <= 100,
            "total_requests": total,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "block_rate": round(self.blocked / max(total, 1), 2),
        }


# ═══════════════════════════════════════════════════════════
# 场景 5: 内存压力
# ═══════════════════════════════════════════════════════════

class MemoryPressureScenario(ChaosScenario):
    """模拟内存持续增长 → 验证是否有泄漏趋势"""

    def __init__(self):
        super().__init__("memory_pressure", "连续 1000 次幻觉检测 → 内存趋势")

    def inject(self):
        from hallucination_detector import HallucinationDetector
        import tracemalloc
        tracemalloc.start()
        detector = HallucinationDetector()
        self.memory_samples = []

        texts = [
            "朱元璋发明了火锅", "Python是1989年发布的", "地球是平的",
            "光速是无限快的", "爱因斯坦发明了原子弹", "大脑只开发了10%",
            "瓦特发明了蒸汽机", "爱迪生发明了电灯泡",
        ]

        for i in range(1000):
            detector.analyze(texts[i % len(texts)])
            if i % 100 == 0:
                current, peak = tracemalloc.get_traced_memory()
                self.memory_samples.append({
                    "iteration": i,
                    "current_kb": round(current / 1024, 1),
                    "peak_kb": round(peak / 1024, 1),
                })

        self.final_current, self.final_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    def verify(self) -> dict:
        current_kb = round(self.final_current / 1024, 1)
        peak_kb = round(self.final_peak / 1024, 1)
        # 检查趋势：取前3和后3个采样比较
        early = self.memory_samples[:3]
        late = self.memory_samples[-3:]
        early_avg = sum(s["current_kb"] for s in early) / len(early)
        late_avg = sum(s["current_kb"] for s in late) / len(late)
        growth = (late_avg - early_avg) / max(early_avg, 1)

        # 增长率 < 30% 视为无明显泄漏
        no_leak = growth < 0.3

        return {
            "passed": no_leak,
            "iterations": 1000,
            "final_current_kb": current_kb,
            "final_peak_kb": peak_kb,
            "early_avg_kb": round(early_avg, 1),
            "late_avg_kb": round(late_avg, 1),
            "growth_ratio": round(growth, 2),
            "leak_detected": not no_leak,
            "samples": self.memory_samples[::5],  # 每5个采样保存1个
        }


# ═══════════════════════════════════════════════════════════
# 运行器
# ═══════════════════════════════════════════════════════════

ALL_SCENARIOS = [
    UpstreamTimeoutScenario,
    DatabaseDisconnectScenario,
    LeaderLossScenario,
    AvalancheScenario,
    MemoryPressureScenario,
]


def run_all() -> dict:
    """运行所有故障场景"""
    results = []
    passed = 0
    failed = 0

    print(f"\n{'#'*60}")
    print(f"  混沌工程 — 故障注入测试")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  场景数: {len(ALL_SCENARIOS)}")
    print(f"{'#'*60}")

    for scenario_cls in ALL_SCENARIOS:
        scenario = scenario_cls()
        result = scenario.run()
        results.append(result)
        if result.get("passed"):
            passed += 1
        else:
            failed += 1

    summary = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / max(len(results), 1), 2),
        "scenarios": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    print(f"\n{'='*60}")
    print(f"  混沌工程报告: {passed}/{len(results)} 通过 ({summary['pass_rate']*100:.0f}%)")
    print(f"{'='*60}")

    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="混沌工程故障注入")
    parser.add_argument("--scenario", choices=["all"] + [s.__name__.replace("Scenario", "").lower()
                          for s in ALL_SCENARIOS], default="all")
    parser.add_argument("--output", default="", help="输出 JSON 文件")
    args = parser.parse_args()

    if args.scenario == "all":
        report = run_all()
    else:
        for s in ALL_SCENARIOS:
            if s.__name__.replace("Scenario", "").lower() == args.scenario:
                report = s().run()
                break

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"报告已保存: {args.output}")
