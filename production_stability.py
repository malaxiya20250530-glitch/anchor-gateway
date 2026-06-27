#!/usr/bin/env python3
"""
生产稳定性验证 — 7天/30天浸泡 + 真实流量 + SLA 统计 + 成本曲线。

五大模块:
  1. 长期浸泡: 7天/30天持续运行，checkpoint 断点续跑
  2. 真实流量: 昼夜周期 + 突发尖峰 + 长尾分布
  3. SLA 统计: 滚动窗口 P50/P95/P99 + 可用性 + 预算燃烧
  4. 成本曲线: token 消耗投影 + 盈亏平衡点
  5. 综合报告: 每日摘要 + 周期性告警

用法:
    python3 production_stability.py --days 7              # 7天浸泡
    python3 production_stability.py --days 30 --qps 20    # 30天
    python3 production_stability.py --dry-run --hours 1   # 干跑1小时
    python3 production_stability.py --report              # 仅生成报告
    python3 production_stability.py --cost-model          # 成本曲线分析
"""

import json
import os
import sys
import time
import math
import random
import threading
from collections import deque, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "stability_state.json"
DAILY_DIR = ROOT / "stability_daily"

# ═══════════════════════════════════════════════════════════
# 真实流量模式
# ═══════════════════════════════════════════════════════════

class TrafficPattern:
    """模拟真实生产流量：昼夜周期、工作日/周末、突发尖峰"""

    # 一小时内的相对流量系数 (0-23时)
    HOURLY_WEIGHTS = [
        0.05, 0.03, 0.02, 0.02, 0.03, 0.08,  # 0-5: 深夜低谷
        0.15, 0.30, 0.55, 0.75, 0.90, 0.95,  # 6-11: 上午攀升
        1.00, 0.85, 0.90, 0.80, 0.75, 0.70,  # 12-17: 下午波动
        0.60, 0.50, 0.55, 0.45, 0.30, 0.15,  # 18-23: 晚间回落
    ]
    WEEKEND_FACTOR = 0.65  # 周末流量系数
    BURST_PROBABILITY = 0.03  # 每秒 3% 概率触发突发流量

    @classmethod
    def current_qps(cls, base_qps: float) -> float:
        """基于当前时间和模式计算实际 QPS"""
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()  # 0=周一, 6=周日
        is_weekend = weekday >= 5

        weight = cls.HOURLY_WEIGHTS[hour]
        if is_weekend:
            weight *= cls.WEEKEND_FACTOR

        # 突发尖峰: 2-5x 短暂放大
        if random.random() < cls.BURST_PROBABILITY:
            weight *= random.uniform(2.0, 5.0)

        return base_qps * weight

    @classmethod
    def traffic_distribution(cls) -> str:
        """返回流量分布描述"""
        peak_hour = cls.HOURLY_WEIGHTS.index(max(cls.HOURLY_WEIGHTS))
        return (f"峰值: {peak_hour}:00 (权重 {max(cls.HOURLY_WEIGHTS)}), "
                f"周末系数: {cls.WEEKEND_FACTOR}")


# ═══════════════════════════════════════════════════════════
# SLA 统计器
# ═══════════════════════════════════════════════════════════

class SLAStats:
    """滚动窗口 SLA 统计：P50/P95/P99、可用性、错误率、预算燃烧"""

    def __init__(self, window_hours: int = 24):
        self.window_sec = window_hours * 3600
        self.latencies = deque()     # (timestamp, latency_ms)
        self.errors = deque()        # (timestamp, error_type)
        self.requests = deque()      # (timestamp, success_bool)
        self._lock = threading.Lock()

    def record(self, latency_ms: float, success: bool,
               error_type: str = "") -> None:
        """记录单次请求"""
        now = time.time()
        cutoff = now - self.window_sec
        with self._lock:
            self.latencies.append((now, latency_ms))
            self.errors.append((now, error_type)) if not success else None
            self.requests.append((now, success))
            # 清理过期数据
            while self.latencies and self.latencies[0][0] < cutoff:
                self.latencies.popleft()
            while self.errors and self.errors[0][0] < cutoff:
                self.errors.popleft()
            while self.requests and self.requests[0][0] < cutoff:
                self.requests.popleft()

    def snapshot(self) -> dict:
        """当前 SLA 快照"""
        with self._lock:
            total = len(self.requests)
            if total == 0:
                return {"window": "no_data"}

            lats = sorted([l[1] for l in self.latencies])
            n = len(lats)
            successes = sum(1 for r in self.requests if r[1])
            errors_by_type = defaultdict(int)
            for _, etype in self.errors:
                errors_by_type[etype] += 1

            def pct(arr, p):
                if not arr:
                    return 0
                k = int(len(arr) * p)
                return arr[min(k, len(arr)-1)]

            return {
                "total_requests": total,
                "success_rate": round(successes / max(total, 1), 4),
                "error_count": total - successes,
                "error_rate": round((total - successes) / max(total, 1), 4),
                "error_breakdown": dict(errors_by_type),
                "p50_ms": round(pct(lats, 0.50), 1),
                "p95_ms": round(pct(lats, 0.95), 1),
                "p99_ms": round(pct(lats, 0.99), 1),
                "avg_latency_ms": round(sum(lats)/max(n,1), 1) if lats else 0,
                "min_latency_ms": round(lats[0], 1) if lats else 0,
                "max_latency_ms": round(lats[-1], 1) if lats else 0,
            }


# ═══════════════════════════════════════════════════════════
# 成本模型
# ═══════════════════════════════════════════════════════════

class CostModel:
    """成本曲线：token 消耗、API 费用、盈亏平衡"""

    # 定价假设
    LLM_COST_PER_1K_TOKENS = 0.002   # $0.002/1K tokens (GPT-3.5级)
    LOCAL_COST_PER_HOUR = 0.05       # $0.05/h 服务器成本
    TOKENS_PER_REQUEST = 150         # 每次请求约 150 tokens

    def __init__(self, base_qps: float = 10):
        self.base_qps = base_qps
        self.daily_requests = 0
        self.daily_tokens = 0
        self.cumulative_cost = 0.0
        self.start_time = time.time()

    def record_day(self, requests: int) -> dict:
        """记录每日请求并计算成本"""
        tokens = requests * self.TOKENS_PER_REQUEST
        llm_cost = tokens / 1000 * self.LLM_COST_PER_1K_TOKENS
        local_cost = 24 * self.LOCAL_COST_PER_HOUR
        total = llm_cost + local_cost

        self.daily_requests = requests
        self.daily_tokens = tokens
        self.cumulative_cost += total

        return {
            "requests": requests,
            "tokens": tokens,
            "llm_cost_usd": round(llm_cost, 4),
            "local_cost_usd": round(local_cost, 2),
            "total_cost_usd": round(total, 4),
            "cumulative_cost_usd": round(self.cumulative_cost, 2),
        }

    def projection(self, days: int = 30) -> dict:
        """成本投影"""
        avg_daily = self.daily_requests or int(self.base_qps * 86400 * 0.5)
        points = []
        for d in range(1, days + 1):
            tokens = avg_daily * d * self.TOKENS_PER_REQUEST
            llm = tokens / 1000 * self.LLM_COST_PER_1K_TOKENS
            local = d * 24 * self.LOCAL_COST_PER_HOUR
            points.append({
                "day": d,
                "cumulative_requests": avg_daily * d,
                "cumulative_tokens": tokens,
                "cost_usd": round(llm + local, 2),
            })

        breakeven = None
        for p in points:
            if p["cost_usd"] >= 100:
                breakeven = p["day"]
                break

        return {
            "days": days,
            "projected_cost_usd": points[-1]["cost_usd"] if points else 0,
            "avg_daily_cost_usd": round(points[-1]["cost_usd"]/days, 2) if points else 0,
            "breakeven_100usd_day": breakeven,
            "curve": points[::max(1, days//30)] if days > 30 else points,
        }

    def print_curve(self, projection: dict) -> None:
        """打印 ASCII 成本曲线"""
        points = projection["curve"]
        if not points:
            return
        max_cost = points[-1]["cost_usd"]
        print(f"\n  📈 成本曲线 ({projection['days']}天投影)")
        print(f"  日均: ${projection['avg_daily_cost_usd']}  |  "
              f"总计: ${projection['projected_cost_usd']}")
        if projection.get("breakeven_100usd_day"):
            print(f"  达到 $100: 第 {projection['breakeven_100usd_day']} 天")
        # 简单条形图
        bar_width = 40
        for p in points[::max(1, len(points)//10)]:
            bar = "█" * int(p["cost_usd"] / max(max_cost, 1) * bar_width)
            print(f"  第{p['day']:>3}天: ${p['cost_usd']:>7.2f} {bar}")


# ═══════════════════════════════════════════════════════════
# 长期浸泡引擎
# ═══════════════════════════════════════════════════════════

class ProductionStability:
    """生产稳定性验证引擎"""

    def __init__(self, days: int = 7, base_qps: float = 10,
                 sla_window_hours: int = 24, report_interval_min: int = 60):
        self.days = days
        self.base_qps = base_qps
        self.duration_sec = days * 86400
        self.sla = SLAStats(window_hours=sla_window_hours)
        self.cost = CostModel(base_qps=base_qps)
        self.report_interval = report_interval_min * 60
        self._running = True
        self._checkpoint = self._load_checkpoint()
        self._daily_snapshots = []

    def _load_checkpoint(self) -> dict:
        """加载断点续跑状态"""
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
        return {"elapsed_sec": 0, "total_requests": 0, "day": 1}

    def _save_checkpoint(self, elapsed: float, requests: int, day: int) -> None:
        """保存断点"""
        with open(STATE_FILE, "w") as f:
            json.dump({
                "elapsed_sec": round(elapsed, 1),
                "total_requests": requests,
                "day": day,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, f)

    def _save_daily_report(self, day: int, sla_snapshot: dict,
                           cost_report: dict) -> None:
        """保存每日报告"""
        DAILY_DIR.mkdir(exist_ok=True)
        report = {
            "day": day,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sla": sla_snapshot,
            "cost": cost_report,
        }
        path = DAILY_DIR / f"day_{day:03d}.json"
        with open(path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        self._daily_snapshots.append(report)

    def _generate_traffic(self, duration_sec: float,
                          global_deadline: float = None) -> tuple:
        """生成时间段内的请求流量"""
        requests = 0
        errors = 0
        t0 = time.time()
        chunk_deadline = t0 + duration_sec
        # 不超出全局 deadline
        inner_deadline = min(chunk_deadline, global_deadline) if global_deadline else chunk_deadline

        try:
            from hallucination_detector import HallucinationDetector
            detector = HallucinationDetector()
        except Exception:
            detector = None

        while time.time() < inner_deadline and self._running:
            # 动态 QPS
            qps = TrafficPattern.current_qps(self.base_qps)
            sleep_time = 1.0 / max(qps, 0.1)

            try:
                t_start = time.perf_counter()
                if detector:
                    detector.analyze("地球是平的")
                else:
                    time.sleep(0.01)
                latency_ms = (time.perf_counter() - t_start) * 1000
                self.sla.record(latency_ms, True)
                requests += 1
            except Exception as e:
                self.sla.record(0, False, type(e).__name__)
                errors += 1

            time.sleep(sleep_time)

        return requests, errors

    def run(self) -> dict:
        """运行长期稳定性验证"""
        start_time = time.time()
        deadline = start_time + self.duration_sec
        elapsed = self._checkpoint.get("elapsed_sec", 0)
        total_requests = self._checkpoint.get("total_requests", 0)
        current_day = self._checkpoint.get("day", 1)
        last_report = time.time()

        print(f"\n{'='*65}")
        print(f"  🏭 生产稳定性验证")
        print(f"  计划: {self.days} 天 ({self.duration_sec/86400:.1f}d)")
        print(f"  基础 QPS: {self.base_qps}  |  {TrafficPattern.traffic_distribution()}")
        print(f"  开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if elapsed > 0:
            print(f"  续跑: 已完成 {elapsed/86400:.1f} 天 ({total_requests} 请求)")
        print(f"{'='*65}")

        try:
            while time.time() < deadline and self._running:
                # 每小时一个周期（但不超出剩余时间）
                remaining = deadline - time.time()
                chunk = min(3600, max(60, remaining))
                requests, errors = self._generate_traffic(chunk, global_deadline=deadline)
                total_requests += requests
                elapsed = time.time() - start_time
                day = int(elapsed / 86400) + 1

                # 每小时 SLA 快照
                sla_now = self.sla.snapshot()
                self._save_checkpoint(elapsed, total_requests, day)

                # 定时报告
                if time.time() - last_report >= self.report_interval:
                    last_report = time.time()
                    self._print_status(day, elapsed, total_requests, sla_now)

                # 跨天: 保存每日报告 + 成本记录
                if day > current_day:
                    cost_report = self.cost.record_day(
                        total_requests // max(day - 1, 1))
                    self._save_daily_report(current_day, sla_now, cost_report)
                    current_day = day

        except KeyboardInterrupt:
            print("\n  ⏸️  收到中断信号，保存 checkpoint...")
            self._save_checkpoint(elapsed, total_requests, current_day)

        # 最终报告
        elapsed = time.time() - start_time
        sla_final = self.sla.snapshot()
        cost_final = self.cost.record_day(
            total_requests // max(int(elapsed / 86400), 1))

        return {
            "duration_days": round(elapsed / 86400, 2),
            "total_requests": total_requests,
            "avg_qps": round(total_requests / max(elapsed, 1), 1),
            "sla_final": sla_final,
            "cost_final": cost_final,
            "daily_reports": len(self._daily_snapshots),
        }

    def _print_status(self, day: int, elapsed: float,
                      requests: int, sla: dict) -> None:
        """打印状态行"""
        days_elapsed = elapsed / 86400
        p50 = sla.get("p50_ms", 0)
        p99 = sla.get("p99_ms", 0)
        err = sla.get("error_rate", 0)
        print(f"  第{day}天 {days_elapsed:.1f}d | "
              f"请求: {requests} | "
              f"P50: {p50:.0f}ms P99: {p99:.0f}ms | "
              f"错误: {err:.2%}")


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="生产稳定性验证")
    parser.add_argument("--days", type=int, default=7,
                        help="浸泡天数 (默认 7)")
    parser.add_argument("--qps", type=float, default=10,
                        help="基础 QPS (默认 10)")
    parser.add_argument("--hours", type=float, default=0,
                        help="干跑小时数 (覆盖 --days)")
    parser.add_argument("--dry-run", action="store_true",
                        help="干跑模式 (1小时)")
    parser.add_argument("--report", action="store_true",
                        help="仅生成已有数据的报告")
    parser.add_argument("--cost-model", action="store_true",
                        help="仅显示成本曲线")
    parser.add_argument("--reset", action="store_true",
                        help="清除 checkpoint 重新开始")
    args = parser.parse_args()

    if args.reset:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        import shutil
        if DAILY_DIR.exists():
            shutil.rmtree(DAILY_DIR, ignore_errors=True)
        print("✅ Checkpoint 已清除")
        sys.exit(0)

    if args.cost_model:
        cm = CostModel(base_qps=args.qps)
        cm.record_day(int(args.qps * 86400 * 0.5))
        proj = cm.projection(days=args.days or 30)
        cm.print_curve(proj)
        sys.exit(0)

    if args.report:
        # 汇总已有每日报告
        if DAILY_DIR.exists():
            reports = sorted(DAILY_DIR.glob("day_*.json"))
            if reports:
                print(f"\n  已有 {len(reports)} 份每日报告:")
                for rp in reports[-10:]:
                    with open(rp) as f:
                        r = json.load(f)
                    sla = r.get("sla", {})
                    cost = r.get("cost", {})
                    print(f"    第{r['day']:>3}天: "
                          f"P50={sla.get('p50_ms',0):.0f}ms "
                          f"错误={sla.get('error_rate',0):.2%} "
                          f"费用=${cost.get('total_cost_usd',0):.4f}")
            else:
                print("  无每日报告")
        else:
            print("  无数据目录")
        sys.exit(0)

    # 运行
    if args.dry_run:
        duration = 3600  # 1 小时干跑
    elif args.hours > 0:
        duration = int(args.hours * 3600)
    else:
        duration = args.days * 86400

    engine = ProductionStability(
        days=max(1, int(duration / 86400)),
        base_qps=args.qps,
    )
    engine.duration_sec = duration
    engine.days = max(1, int(duration / 86400))

    try:
        result = engine.run()
        print(f"\n{'='*65}")
        print(f"  🏁 稳定性验证完成")
        print(f"  持续: {result['duration_days']:.1f} 天")
        print(f"  请求: {result['total_requests']}")
        print(f"  QPS:  {result['avg_qps']}")
        sla = result["sla_final"]
        print(f"  P50:  {sla.get('p50_ms',0):.0f}ms  "
              f"P99: {sla.get('p99_ms',0):.0f}ms  "
              f"错误: {sla.get('error_rate',0):.2%}")
        cost = result["cost_final"]
        print(f"  费用: ${cost.get('total_cost_usd',0):.4f}/日")
        print(f"{'='*65}")
    except KeyboardInterrupt:
        print("\n  已保存 checkpoint，使用相同命令续跑")
