#!/usr/bin/env python3
"""
① 用户反馈系统 — SQLite 持久化 + 统计面板
用户对检测结果点赞/踩 → 存储 → 驱动自动学习
"""

import json
import time
import sqlite3
from pathlib import Path
from collections import Counter
from typing import Optional


DB_PATH = Path(__file__).parent / "feedback.db"


class FeedbackCollector:
    """用户反馈收集器 — 点赞/踩 + 纠错建议"""

    def __init__(self):
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim TEXT NOT NULL,
                    detected_verdict TEXT NOT NULL,
                    user_verdict TEXT NOT NULL,
                    correction TEXT DEFAULT '',
                    session_id TEXT DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_claim
                    ON feedback(claim);
                CREATE INDEX IF NOT EXISTS idx_feedback_verdict
                    ON feedback(user_verdict);
            """)

    def submit(self, claim: str, detected_verdict: str,
               user_verdict: str, correction: str = "",
               session_id: str = "") -> int:
        """
        提交反馈
        user_verdict: 'agree' | 'disagree' | 'corrected'
        correction: 用户提供的正确答案（disagree 时建议填写）
        返回 feedback_id
        """
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO feedback (claim, detected_verdict, user_verdict, "
                "correction, session_id, created_at) VALUES (?,?,?,?,?,?)",
                (claim, detected_verdict, user_verdict, correction,
                 session_id, time.time())
            )
            conn.commit()
            return cur.lastrowid

    def stats(self, days: int = 7) -> dict:
        """最近 N 天的反馈统计"""
        cutoff = time.time() - days * 86400
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE created_at > ?", (cutoff,)
            ).fetchone()[0]
            agree = conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE user_verdict='agree' AND created_at > ?",
                (cutoff,)
            ).fetchone()[0]
            disagree = conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE user_verdict='disagree' AND created_at > ?",
                (cutoff,)
            ).fetchone()[0]

            # 按检测判决分组
            by_verdict = {}
            for row in conn.execute(
                "SELECT detected_verdict, user_verdict, COUNT(*) as cnt "
                "FROM feedback WHERE created_at > ? "
                "GROUP BY detected_verdict, user_verdict", (cutoff,)
            ):
                v = row["detected_verdict"]
                if v not in by_verdict:
                    by_verdict[v] = {}
                by_verdict[v][row["user_verdict"]] = row["cnt"]

        return {
            "total": total,
            "agree": agree,
            "disagree": disagree,
            "agreement_rate": round(agree / max(total, 1), 3),
            "by_verdict": by_verdict,
            "days": days,
        }

    def get_corrections(self, limit: int = 20) -> list[dict]:
        """获取用户提供的纠正建议（用于自动KB更新）"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE user_verdict='disagree' "
                "AND correction != '' ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_disagreed_claims(self, limit: int = 50) -> list[str]:
        """获取被用户反对的断言列表"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT claim FROM feedback "
                "WHERE user_verdict='disagree' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [r["claim"] for r in rows]


# ── 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    fc = FeedbackCollector()

    # 模拟反馈
    fc.submit("朱元璋发明了火锅", "contradicted", "agree",
              session_id="demo")
    fc.submit("毕昇发明了活字印刷术", "contradicted", "disagree",
              correction="毕昇确实发明了活字印刷术，检测有误",
              session_id="demo")
    fc.submit("地球是平的", "contradicted", "agree",
              session_id="demo")

    stats = fc.stats()
    print(f"反馈统计: 总计{stats['total']}条, 赞同率{stats['agreement_rate']:.0%}")
    print(f"纠正建议: {len(fc.get_corrections())} 条")
    print(f"被反对断言: {len(fc.get_disagreed_claims())} 条")
