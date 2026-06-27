#!/usr/bin/env python3
"""企业级验证编排器 — 一键运行全部测试生成完整报告。

执行顺序:
  1. 单元测试 (30s)          → 回归保护
  2. 安全扫描 (10s)          → WAF / 认证 / 速率限制
  3. 混沌工程 (15s)          → 熔断 / 选主 / 连接池
  4. 压测 (30s)              → QPS / P95 / 错误率
  5. 浸泡测试 (按需, 默认跳过) → 长时间稳定性

输出:
  validate_report.json  — 完整验证报告
  终端摘要

用法:
  python3 validate_all.py                # 快速验证 (~2min)
  python3 validate_all.py --full         # 完整验证 (~1h 含浸泡)
  python3 validate_all.py --soak 3600    # 包含 1h 浸泡测试
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════
# 测试步骤
# ═══════════════════════════════════════════════════════════

def run_step(name: str, cmd: list[str], timeout: int = 120) -> dict:
    """执行单个测试步骤"""
    print(f"\n{'─'*60}")
    print(f"  [{name}] 开始...")
    print(f"{'─'*60}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=os.path.dirname(__file__) or "."
        )
        elapsed = time.time() - start
        passed = result.returncode == 0

        # 提取关键输出
        output_lines = result.stdout.split("\n") + result.stderr.split("\n")
        key_lines = [l for l in output_lines if any(
            marker in l for marker in ["✅", "❌", "通过", "失败", "pass", "FAIL",
                                        "PASS", "QPS", "p95", "p99", "错误率",
                                        "通过率", "漏洞", "注入", "增长率"]
        )]

        return {
            "step": name,
            "passed": passed,
            "duration_sec": round(elapsed, 1),
            "exit_code": result.returncode,
            "key_output": key_lines[:20],
        }
    except subprocess.TimeoutExpired:
        return {"step": name, "passed": False, "duration_sec": timeout,
                "error": "超时"}
    except Exception as e:
        return {"step": name, "passed": False, "duration_sec": time.time() - start,
                "error": str(e)}


def validate_all(full: bool = False, soak_sec: int = 0):
    """执行完整验证流程"""
    print(f"\n{'#'*60}")
    print(f"  企业级验证 — Enterprise Proven 认证")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  模式: {'完整验证' if full or soak_sec else '快速验证'}")
    print(f"{'#'*60}")

    steps = []
    total_start = time.time()

    # ── 步骤 1: 单元测试 ──
    result = run_step("单元测试",
                      [sys.executable, "-W", "ignore", "test_fact_checker.py"])
    steps.append(result)

    # ── 步骤 2: 安全扫描 ──
    result = run_step("安全扫描(WAF/Auth/RateLimit)",
                      [sys.executable, "-W", "ignore", "security_scan.py",
                       "--output", "/data/data/com.termux/files/home/security_scan.json"])
    steps.append(result)

    # ── 步骤 3: 混沌工程 ──
    result = run_step("混沌工程(熔断/选主/连接池)",
                      [sys.executable, "-W", "ignore", "chaos_engineering.py",
                       "--scenario", "all", "--output", "/data/data/com.termux/files/home/chaos_report.json"])
    steps.append(result)

    # ── 步骤 4: 压测 ──
    result = run_step("压测(100QPS/60s)",
                      [sys.executable, "-W", "ignore", "enterprise_stress.py",
                       "--local", "hallucination", "--qps", "100",
                       "--duration", "30", "--output", "/data/data/com.termux/files/home/stress_report.json"],
                      timeout=90)
    steps.append(result)

    # ── 步骤 5: 浸泡测试 (可选) ──
    if full or soak_sec > 0:
        duration = soak_sec if soak_sec > 0 else 3600
        hours = duration / 3600
        result = run_step(f"浸泡测试({hours:.0f}h)",
                          [sys.executable, "-W", "ignore", "soak_test.py",
                           "--duration", str(duration), "--qps", "20",
                           "--output", "/data/data/com.termux/files/home/soak_report.json"],
                          timeout=duration + 60)
        steps.append(result)

    # ── 生成报告 ──
    total_elapsed = time.time() - total_start
    passed = sum(1 for s in steps if s.get("passed"))
    report = {
        "validator": "Enterprise Proven",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_duration_sec": round(total_elapsed, 1),
        "summary": {
            "total_steps": len(steps),
            "passed": passed,
            "failed": len(steps) - passed,
            "pass_rate": round(passed / max(len(steps), 1), 2),
        },
        "steps": steps,
    }

    # 收集子报告
    for path, key in [("/data/data/com.termux/files/home/security_scan.json", "security_scan"),
                      ("/data/data/com.termux/files/home/chaos_report.json", "chaos"),
                      ("/data/data/com.termux/files/home/stress_report.json", "stress"),
                      ("/data/data/com.termux/files/home/soak_report.json", "soak")]:
        try:
            with open(path) as f:
                report[key] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    # 保存
    report_path = "validate_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    # ── 终端摘要 ──
    print(f"\n{'='*60}")
    print(f"  🏆 验证完成")
    print(f"{'='*60}")
    print(f"  步骤: {passed}/{len(steps)} 通过")
    print(f"  耗时: {total_elapsed:.0f}s")
    print(f"  报告: {report_path}")
    print(f"{'='*60}")

    for s in steps:
        icon = "✅" if s.get("passed") else "❌"
        print(f"  {icon} {s['step']:30s} ({s.get('duration_sec', 0):.0f}s)")

    # 等级评定
    pass_rate = report["summary"]["pass_rate"]
    if pass_rate >= 1.0:
        grade = "🟢 Enterprise Proven"
    elif pass_rate >= 0.8:
        grade = "🟡 Enterprise Ready"
    else:
        grade = "🔴 Needs Work"
    print(f"\n  等级: {grade}")

    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="企业级一键验证")
    parser.add_argument("--full", action="store_true", help="完整验证 (含1h浸泡)")
    parser.add_argument("--soak", type=int, default=0, help="浸泡测试秒数")
    parser.add_argument("--quick", action="store_true", help="仅快速验证")
    args = parser.parse_args()

    validate_all(full=args.full, soak_sec=args.soak)
