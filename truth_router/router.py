#!/usr/bin/env python3
"""
Truth Router MVP — 三层路由架构

  User Query
      │
      ▼
  Truth Router
      │
      ├── Memory Loader (context_builder)
      │       ├── project/
      │       ├── user/
      │       └── session/latest.md
      │
      ├── Retrieval (retrieval)
      │       ├── kb_core.json (实体匹配)
      │       └── fact_store.db (事实检索)
      │
      ├── Fact Check (fact_check)
      │       └── hallucination_detector.AnchorEngine
      │
      ├── Scoring (scoring)
      │       └── truth_score = retrieval*0.4 + citation*0.3 + consistency*0.3
      │
      └── Response

用法:
  python3 -m truth_router.router "朱元璋发明了火锅"
  python3 -m truth_router.router --json "朱元璋发明了火锅"
"""
import json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from truth_router.context_builder import build_context, context_summary
from truth_router.retrieval import retrieve
from truth_router.fact_check import check_claim
from truth_router.scoring import compute_truth_score


def route(query: str, verbose: bool = False) -> dict:
    """Truth Router 主路由

    参数:
        query: 用户查询文本
        verbose: 是否打印过程日志
    返回:
        完整路由结果字典
    """
    t0 = time.time()

    # 1. 加载上下文
    if verbose:
        print(f"[Router] 1/4 加载上下文...")
    ctx = build_context()
    ctx_summary = context_summary(ctx)

    # 2. 检索
    if verbose:
        print(f"[Router] 2/4 检索知识库...")
    retrieval_result = retrieve(query)

    # 3. 事实校验
    if verbose:
        print(f"[Router] 3/4 事实校验 ({len(retrieval_result['facts'])} 条)...")
    fact_check_result = check_claim(query, retrieval_result["facts"])

    # 4. 评分
    if verbose:
        print(f"[Router] 4/4 评分...")
    score_result = compute_truth_score(retrieval_result, fact_check_result)

    elapsed = round(time.time() - t0, 3)

    return {
        "query": query,
        "context_summary": ctx_summary,
        "verdict": score_result["verdict"],
        "truth_score": score_result["truth_score"],
        "scores": {
            "retrieval": score_result["retrieval"],
            "citation": score_result["citation"],
            "consistency": score_result["consistency"],
        },
        "entities": retrieval_result["entities"],
        "facts_checked": len(fact_check_result["checks"]),
        "checks": fact_check_result["checks"],
        "elapsed_ms": round(elapsed * 1000),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python3 -m truth_router.router <查询文本> [--json]")
        print('示例: python3 -m truth_router.router "朱元璋发明了火锅"')
        sys.exit(1)

    args = sys.argv[1:]
    json_mode = "--json" in args
    verbose = "--verbose" in args
    query = " ".join(a for a in args if not a.startswith("--"))

    if not query:
        print("❌ 请提供查询文本")
        sys.exit(1)

    result = route(query, verbose=verbose)

    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f"  🔍 查询: {result['query']}")
        print(f"  🧠 上下文: {result['context_summary']}")
        print(f"  📦 实体: {result['entities'] or '(未识别)'}")
        print(f"  📋 校验: {result['facts_checked']} 条事实")
        print(f"{'='*50}")
        print(f"  📊 可信度: {result['truth_score']}")
        print(f"     ├ 检索分: {result['scores']['retrieval']}")
        print(f"     ├ 引用分: {result['scores']['citation']}")
        print(f"     └ 一致分: {result['scores']['consistency']}")
        print(f"  ⚖️  判决: {result['verdict']}")
        print(f"  ⏱️  耗时: {result['elapsed_ms']}ms")
        if result["checks"]:
            print(f"\n  校验明细:")
            for c in result["checks"]:
                print(f"    [{c['verdict']}] {c['fact'][:60]}")


if __name__ == "__main__":
    main()
