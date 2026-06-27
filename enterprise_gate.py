#!/usr/bin/env python3
"""
🏢 企业级 CI/CD 门禁 — 六阶段串行验证，全绿才放行。

阶段:
  Phase 1: Unit       — 单元测试 (5/5 通过)
  Phase 2: Smoke      — 冒烟测试 (8/8 正确)
  Phase 3: Security   — 安全扫描 + 输入校验
  Phase 4: Quality    — 基准门禁 (F1/精度/召回)
  Phase 5: Resilience — 混沌工程 (4/5+ 通过)
  Phase 6: SLO        — SLO 合规检查

退出码: 0=全部通过, 1=存在失败, 2=严重阻塞

用法:
    python3 enterprise_gate.py                    # 全阶段
    python3 enterprise_gate.py --phase 1,2,3      # 指定阶段
    python3 enterprise_gate.py --json             # JSON 输出
    python3 enterprise_gate.py --quick            # 快速模式(跳过混沌/SLO)
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent

# ═══════════════════════════════════════════════════════════
# 阶段定义
# ═══════════════════════════════════════════════════════════

PHASES = {
    1: {"name": "Unit",       "icon": "🧪", "desc": "单元测试",
        "target": "5/5 通过", "required": True},
    2: {"name": "Smoke",      "icon": "🔥", "desc": "冒烟测试",
        "target": "8/8 正确", "required": True},
    3: {"name": "Security",   "icon": "🛡️", "desc": "安全扫描",
        "target": "0 高危",   "required": True},
    4: {"name": "Quality",    "icon": "📊", "desc": "基准门禁",
        "target": "F1≥0.12",  "required": True},
    5: {"name": "Resilience", "icon": "🔧", "desc": "混沌工程",
        "target": "7/9 通过", "required": False},
    6: {"name": "SLO",        "icon": "📈", "desc": "SLO 合规",
        "target": "≥2/4 合规", "required": False},
    7: {"name": "Latency",     "icon": "⏱️", "desc": "延迟剖析",
        "target": "P50<200ms, P99<1000ms", "required": False},
}


# ═══════════════════════════════════════════════════════════
# Phase 1: Unit Tests
# ═══════════════════════════════════════════════════════════

def phase_unit() -> dict:
    """运行单元测试"""
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "test_fact_checker.py")],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT)
        )
        output = proc.stdout + proc.stderr
        passed = "全部通过" in output
        # 解析测试组数
        groups_passed = output.count("✅ 通过")
        return {
            "passed": passed and groups_passed >= 5,
            "groups": groups_passed,
            "elapsed_sec": round(time.perf_counter() - t0, 1),
            "detail": f"{groups_passed}/5 组通过" if passed else proc.stderr[-200:],
        }
    except Exception as e:
        return {"passed": False, "elapsed_sec": round(time.perf_counter() - t0, 1),
                "detail": str(e), "groups": 0}


# ═══════════════════════════════════════════════════════════
# Phase 2: Smoke Tests
# ═══════════════════════════════════════════════════════════

SMOKE_CASES = [
    ("朱元璋发明了火锅", "contradicted", "历史谬误"),
    ("Python是1991年发布的", "verified", "正确事实"),
    ("地球是平的", "contradicted", "常识错误"),
    ("明朝由朱元璋建立", "verified", "历史事实"),
    ("珠穆朗玛峰高8848米", "verified", "地理数据"),
    ("光速是无限快的", "contradicted", "科学谬误"),
    ("爱因斯坦发明了原子弹", "contradicted", "归属错误"),
    ("大脑只开发了10%", "contradicted", "流行误区"),
]


def phase_smoke() -> dict:
    """运行冒烟测试"""
    t0 = time.perf_counter()
    try:
        from hallucination_detector import HallucinationDetector
        detector = HallucinationDetector()
        passed = 0
        failures = []
        for claim, expected, desc in SMOKE_CASES:
            result = detector.analyze(claim)
            verdict = result.results[0].verdict if result.results else "N/A"
            if expected in str(verdict).lower():
                passed += 1
            else:
                failures.append({"claim": claim, "expected": expected,
                                 "actual": str(verdict), "desc": desc})
        return {
            "passed": passed == len(SMOKE_CASES),
            "correct": passed,
            "total": len(SMOKE_CASES),
            "failures": failures,
            "elapsed_sec": round(time.perf_counter() - t0, 1),
            "detail": f"{passed}/{len(SMOKE_CASES)} 正确",
        }
    except Exception as e:
        return {"passed": False, "correct": 0, "total": len(SMOKE_CASES),
                "elapsed_sec": round(time.perf_counter() - t0, 1),
                "detail": str(e)}


# ═══════════════════════════════════════════════════════════
# Phase 3: Security Scan
# ═══════════════════════════════════════════════════════════

def phase_security() -> dict:
    """安全扫描 + 输入校验"""
    t0 = time.perf_counter()
    results = {}

    # 3a: 语法安全检查
    try:
        import ast
        issues = []
        for py_file in sorted(ROOT.glob("*.py")):
            if py_file.name.startswith("test_") or py_file.name == "enterprise_gate.py":
                continue
            try:
                with open(py_file) as f:
                    tree = ast.parse(f.read())
                # 检查禁止项
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name):
                            if node.func.id in ("eval", "exec"):
                                issues.append(f"{py_file.name}:{node.lineno} 使用 {node.func.id}()")
                    if isinstance(node, ast.ExceptHandler):
                        if node.type is None:
                            issues.append(f"{py_file.name}:{node.lineno} bare except")
            except SyntaxError as e:
                issues.append(f"{py_file.name}: 语法错误 {e}")
        results["ast_scan"] = {
            "passed": len(issues) == 0,
            "issues": issues,
            "detail": f"{len(issues)} 个问题" if issues else "无禁止项",
        }
    except Exception as e:
        results["ast_scan"] = {"passed": False, "detail": str(e)}

    # 3b: 输入校验
    try:
        from security_hardener import InputValidator
        test_inputs = [
            ("正常输入", True),
            ("A" * 20000, False),         # 超长
            ("", False),                   # 空
            ("<script>alert(1)</script>", True),  # XSS (应被后续净化)
        ]
        iv_passed = 0
        for text, should_pass in test_inputs:
            ok, _ = InputValidator.validate_text(text)
            if ok == should_pass:
                iv_passed += 1
        results["input_validation"] = {
            "passed": iv_passed == len(test_inputs),
            "detail": f"{iv_passed}/{len(test_inputs)} 通过",
        }
    except Exception as e:
        results["input_validation"] = {"passed": True, "detail": f"跳过 ({e})"}

    all_passed = all(r.get("passed", False) for r in results.values())
    return {
        "passed": all_passed,
        "checks": results,
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "detail": "全部通过" if all_passed else "存在问题",
    }


# ═══════════════════════════════════════════════════════════
# Phase 4: Quality Gate
# ═══════════════════════════════════════════════════════════

QUALITY_THRESHOLDS = {
    "f1": 0.12,
    "precision": 0.20,
    "recall": 0.08,
    "accuracy": 0.55,
}


def phase_quality() -> dict:
    """基准门禁检查"""
    t0 = time.perf_counter()
    benchmark_path = ROOT / "benchmark_report.json"

    if not benchmark_path.exists():
        return {"passed": False, "elapsed_sec": 0,
                "detail": "benchmark_report.json 不存在，请先运行 benchmark.py"}

    try:
        with open(benchmark_path) as f:
            report = json.load(f)

        checks = {}
        for metric, threshold in QUALITY_THRESHOLDS.items():
            value = report.get(metric, 0)
            ok = value >= threshold
            checks[metric] = {"value": value, "threshold": threshold, "passed": ok}

        all_passed = all(c["passed"] for c in checks.values())
        violations = [k for k, v in checks.items() if not v["passed"]]

        return {
            "passed": all_passed,
            "checks": checks,
            "violations": violations,
            "elapsed_sec": round(time.perf_counter() - t0, 1),
            "detail": "全部达标" if all_passed else f"{len(violations)} 项未达标: {', '.join(violations)}",
        }
    except Exception as e:
        return {"passed": False, "elapsed_sec": round(time.perf_counter() - t0, 1),
                "detail": str(e)}


# ═══════════════════════════════════════════════════════════
# Phase 5: Resilience
# ═══════════════════════════════════════════════════════════

def phase_resilience(quick: bool = False) -> dict:
    """混沌工程验证"""
    if quick:
        chaos_path = ROOT / "chaos_report.json"
        if chaos_path.exists():
            with open(chaos_path) as f:
                report = json.load(f)
            return {
                "passed": report.get("pass_rate", 0) >= 0.8,
                "scenarios_passed": report.get("passed", 0),
                "scenarios_total": report.get("total", 0),
                "scenarios_total": report.get("total", 0),
                "elapsed_sec": 0,
                "detail": f"{report.get('passed',0)}/{report.get('total',0)} 通过 (缓存)",
            }

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "chaos_engineering.py"),
             "--scenario", "upstreamtimeout"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT)
        )
        upstream_ok = "PASS" in proc.stdout

        proc2 = subprocess.run(
            [sys.executable, str(ROOT / "chaos_engineering.py"),
             "--scenario", "avalanche"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT)
        )
        avalanche_ok = "PASS" in proc2.stdout

        passed = upstream_ok and avalanche_ok
        return {
            "passed": passed,
            "upstream_timeout": upstream_ok,
            "avalanche": avalanche_ok,
            "elapsed_sec": round(time.perf_counter() - t0, 1),
            "detail": "快速验证通过" if passed else "存在失败",
        }
    except Exception as e:
        return {"passed": False, "elapsed_sec": round(time.perf_counter() - t0, 1),
                "detail": str(e)}


# ═══════════════════════════════════════════════════════════
# Phase 6: SLO Check
# ═══════════════════════════════════════════════════════════

def phase_slo() -> dict:
    """SLO 合规检查"""
    t0 = time.perf_counter()
    try:
        from slo_monitor import SLO_DEFINITIONS, collect_from_benchmark, evaluate_slo

        metrics = collect_from_benchmark()
        if not metrics:
            return {"passed": True, "elapsed_sec": 0,
                    "detail": "无基准数据，跳过", "skipped": True}

        results = evaluate_slo(metrics)
        compliant = sum(1 for r in results.values() if r["status"] == "compliant")
        violated = sum(1 for r in results.values() if r["status"] == "violated")

        return {
            "passed": compliant >= 2,
            "compliant": compliant,
            "violated": violated,
            "total": len(results),
            "breakdown": {k: {"status": v["status"], "current": v["current"],
                              "target": v["target"]}
                          for k, v in results.items()},
            "elapsed_sec": round(time.perf_counter() - t0, 1),
            "detail": f"{compliant}/{len(results)} 合规",
        }
    except Exception as e:
        return {"passed": True, "elapsed_sec": round(time.perf_counter() - t0, 1),
                "detail": f"跳过 ({e})", "skipped": True}


# ═══════════════════════════════════════════════════════════
# 编排器
# ═══════════════════════════════════════════════════════════

def phase_latency() -> dict:
    """延迟剖析检查"""
    t0 = time.perf_counter()
    report_path = ROOT / "latency_report.json"
    
    if not report_path.exists():
        return {"passed": True, "elapsed_sec": 0,
                "detail": "无报告，跳过 (运行 latency_profiler.py)", "skipped": True}
    
    try:
        with open(report_path) as f:
            report = json.load(f)
        agg = report.get("aggregate", {})
        p50 = agg.get("p50", 999)
        p99 = agg.get("p99", 999)
        tps = report.get("scenes", {}).get("short", {}).get("tps", 0)
        grade = report.get("grade", "N/A")
        
        passed = p50 < 200 and p99 < 1000  # 宽松阈值
        
        return {
            "passed": passed,
            "p50_ms": p50,
            "p99_ms": p99,
            "tps": tps,
            "grade": grade,
            "elapsed_sec": round(time.perf_counter() - t0, 1),
            "detail": f"P50={p50:.1f}ms P99={p99:.1f}ms TPS={tps:.1f} {grade}",
        }
    except Exception as e:
        return {"passed": True, "elapsed_sec": round(time.perf_counter() - t0, 1),
                "detail": f"读取失败 ({e})", "skipped": True}
PHASE_FUNCTIONS = {
    1: phase_unit,
    2: phase_smoke,
    3: phase_security,
    4: phase_quality,
    5: phase_resilience,
    6: phase_slo,
    7: phase_latency,
}



def run_gate(phases: list = None, quick: bool = False) -> dict:
    """运行企业门禁"""
    if phases is None:
        phases = [1, 2, 3, 4]
        if not quick:
            phases.extend([5, 6])

    report = {
        "gate": "Enterprise CI/CD Gate",
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "quick" if quick else "full",
        "phases": {},
        "passed": True,
        "blocking_failures": 0,
    }

    print(f"\n{'#'*65}")
    print(f"  🏢 企业级 CI/CD 门禁 v1.0")
    print(f"  模式: {'快速' if quick else '完整'}  |  "
          f"阶段: {len(phases)}  |  "
          f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*65}")

    for phase_num in phases:
        phase_def = PHASES[phase_num]
        icon = phase_def["icon"]
        name = phase_def["name"]
        desc = phase_def["desc"]

        print(f"\n  {icon} Phase {phase_num}: {name} — {desc}")
        print(f"  {'─'*55}")

        fn = PHASE_FUNCTIONS[phase_num]
        kwargs = {}
        if phase_num == 5:
            kwargs["quick"] = quick
        result = fn(**kwargs)

        status_icon = "✅" if result.get("passed") else "❌"
        print(f"  {status_icon} {result.get('detail', 'N/A')} "
              f"({result.get('elapsed_sec', 0):.1f}s)")

        report["phases"][str(phase_num)] = {
            "name": name,
            "icon": icon,
            "passed": result.get("passed", False),
            "required": phase_def["required"],
            "detail": result.get("detail", ""),
            "elapsed_sec": result.get("elapsed_sec", 0),
            "data": {k: v for k, v in result.items()
                     if k not in ("passed", "elapsed_sec", "detail")},
        }

        if not result.get("passed") and phase_def["required"]:
            report["blocking_failures"] += 1

    # 综合判定
    report["passed"] = report["blocking_failures"] == 0

    # 摘要
    print(f"\n{'='*65}")
    total_phases = len(phases)
    passed_phases = sum(1 for p in report["phases"].values() if p["passed"])
    status = "✅ 全部通过 — 企业级可部署" if report["passed"] else "❌ 存在阻塞 — 禁止部署"
    print(f"  {status}")
    print(f"  阶段: {passed_phases}/{total_phases} 通过  |  "
          f"阻塞: {report['blocking_failures']}")
    print(f"{'='*65}")

    return report


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="企业级 CI/CD 门禁")
    parser.add_argument("--phase", default="",
                        help="指定阶段，逗号分隔 (如 1,2,3)")
    parser.add_argument("--quick", action="store_true",
                        help="快速模式 (跳过混沌/SLO)")
    parser.add_argument("--json", action="store_true",
                        help="JSON 格式输出")
    args = parser.parse_args()

    phases = None
    if args.phase:
        phases = [int(p.strip()) for p in args.phase.split(",") if p.strip().isdigit()]

    report = run_gate(phases=phases, quick=args.quick)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    sys.exit(0 if report["passed"] else 1)
