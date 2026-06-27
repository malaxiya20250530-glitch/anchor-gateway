#!/usr/bin/env python3
"""缓存命中率统计工具 — 从 Codex SSE 日志提取 usage 数据"""
import sqlite3, os, json, re, sys

LOGS_DB = os.path.expanduser("~/.codex/logs_2.sqlite")


def extract_usage(body: str):
    """从 SSE 日志中提取 usage JSON"""
    for pat in [
        r'"usage":\s*(\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})',
        r'"usage":\s*(\{[^}]*"input_tokens"[^}]*\})',
    ]:
        m = re.search(pat, body)
        if m:
            usage_str = m.group(1)
            if not usage_str.endswith("}"):
                usage_str += "}"
            try:
                return json.loads(usage_str)
            except json.JSONDecodeError:
                continue
    return None


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    conn = sqlite3.connect(LOGS_DB)

    total_events = conn.execute(
        """SELECT COUNT(*) FROM logs
           WHERE target = 'codex_api::sse::responses'
           AND feedback_log_body LIKE '%response.completed%'"""
    ).fetchone()[0]

    query = """SELECT feedback_log_body FROM logs
               WHERE target = 'codex_api::sse::responses'
               AND feedback_log_body LIKE '%response.completed%'
               ORDER BY id DESC"""
    if limit > 0:
        query += f" LIMIT {limit}"

    rows = conn.execute(query).fetchall()

    total_input = 0
    total_cached = 0
    total_output = 0
    count = 0
    cached_count = 0

    for r in rows:
        usage = extract_usage(str(r[0]))
        if not usage:
            continue
        i = usage.get("input_tokens", 0)
        c = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        o = usage.get("output_tokens", 0)
        if i > 0:
            total_input += i
            total_cached += c
            total_output += o
            count += 1
            if c > 0:
                cached_count += 1

    conn.close()

    if count == 0:
        print("⚠️ 未找到 usage 数据")
        return

    rate = total_cached / total_input * 100 if total_input > 0 else 0

    print(f"📊 缓存命中率统计")
    print(f"{'─' * 40}")
    print(f"  日志中事件总数:  {total_events}")
    print(f"  成功解析:        {count} 次")
    print(f"{'─' * 40}")
    print(f"  输入 tokens:     {total_input:>12,}")
    print(f"  缓存命中:        {total_cached:>12,}")
    print(f"  输出 tokens:     {total_output:>12,}")
    print(f"{'─' * 40}")
    print(f"  🎯 缓存命中率:   {rate:.1f}%")
    print(f"     命中轮次:     {cached_count}/{count}")
    print(f"  💰 实际计费输入: {total_input - total_cached:,}")


if __name__ == "__main__":
    main()
