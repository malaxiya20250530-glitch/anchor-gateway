#!/usr/bin/env python3
"""
WAL 日志 — JSON 追加式审计日志
每次检测写入一行 JSON，追加不覆盖，天然 WAL 语义
"""

import json, os, time, threading
from pathlib import Path

WAL_PATH = Path(__file__).parent / "audit_log.jsonl"
_lock = threading.Lock()


def log_detection(query: str, verdict: str, confidence: float,
                  evidence: str = "", source: str = "",
                  checker_hits: list = None, extra: dict = None) -> dict:
    """记录一次幻觉检测到 WAL 日志"""
    entry = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "query": query[:500],
        "verdict": verdict,
        "confidence": round(confidence, 4),
        "evidence": evidence[:300],
        "source": source,
    }
    if checker_hits:
        entry["checkers"] = checker_hits
    if extra:
        entry["extra"] = extra

    # 安全加固: 脱敏敏感字段
    try:
        from security import sanitize_log
        entry = sanitize_log(entry)
    except ImportError:
        pass

    with _lock:
        with open(WAL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def tail_log(n: int = 20) -> list[dict]:
    """读取最近 n 条日志"""
    if not WAL_PATH.exists():
        return []
    entries = []
    with open(WAL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries[-n:]


def stats() -> dict:
    """WAL 统计摘要"""
    if not WAL_PATH.exists():
        return {"total": 0}
    total = 0
    verdicts = {}
    conf_sum = 0.0
    with open(WAL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            total += 1
            v = e.get("verdict", "?")
            verdicts[v] = verdicts.get(v, 0) + 1
            conf_sum += e.get("confidence", 0)
    return {
        "total": total,
        "verdicts": verdicts,
        "avg_confidence": round(conf_sum / max(total, 1), 4),
        "path": str(WAL_PATH),
    }


def rotate(max_mb: int = 10):
    """日志轮转：超过 max_mb 时归档"""
    if not WAL_PATH.exists():
        return
    size_mb = WAL_PATH.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        archive = WAL_PATH.with_suffix(f".{int(time.time())}.jsonl.bak")
        WAL_PATH.rename(archive)


# ============================================================
# 集成到检测器 — 修改 hallucination_detector.py 时加入
# ============================================================
def integrate_with_detector(claim: str, result) -> dict:
    """在 verify() 后调用此函数记录日志"""
    checker_hits = []
    if hasattr(result, 'checker_hits'):
        checker_hits = result.checker_hits

    return log_detection(
        query=claim,
        verdict=result.verdict if hasattr(result, 'verdict') else str(result),
        confidence=result.confidence if hasattr(result, 'confidence') else 0.5,
        evidence=result.evidence if hasattr(result, 'evidence') else "",
        source=result.source if hasattr(result, 'source') else "",
        checker_hits=checker_hits,
    )


if __name__ == "__main__":
    # 自测
    log_detection("朱元璋发明了火锅", "contradicted", 0.88, "朱元璋是明朝开国皇帝", "明史")
    log_detection("毕昇发明了活字印刷术", "verified", 0.90, "毕昇于北宋发明活字印刷", "印刷史")
    log_detection("地球是平的", "contradicted", 0.95, "地球是近似球体", "科学")

    print(f"最近 3 条:")
    for e in tail_log(3):
        print(f"  [{e['iso']}] {e['verdict']:>14} c={e['confidence']:.0%} | {e['query'][:40]}")

    print(f"\n统计: {json.dumps(stats(), ensure_ascii=False, indent=2)}")
