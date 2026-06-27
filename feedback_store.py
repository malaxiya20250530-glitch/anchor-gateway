"""
feedback_store.py — 自进化反馈库（SQLite）
提供反馈记录的增删改查，供 hallucination_detector 和仪表盘共用。
"""

import sqlite3
import json
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

DB_PATH = Path(__file__).parent / "feedback.db"


@dataclass
class FeedbackRecord:
    claim: str
    fact: str
    verdict: str          # "contradicted" | "verified" | "uncertain"
    confidence: float
    evidence: str
    source: str
    user_correction: Optional[str] = None
    rematch_key: Optional[str] = None
    applied: int = 0      # 0=待复核, 1=已应用, -1=已驳回
    id: Optional[int] = None
    created_at: Optional[float] = None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库表（幂等）"""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim TEXT NOT NULL,
                fact TEXT NOT NULL,
                verdict TEXT NOT NULL DEFAULT 'uncertain',
                confidence REAL NOT NULL DEFAULT 0.5,
                evidence TEXT DEFAULT '',
                source TEXT DEFAULT '',
                user_correction TEXT,
                rematch_key TEXT,
                applied INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_claim
            ON feedback(claim)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_applied
            ON feedback(applied)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS uncertain_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim TEXT NOT NULL,
                verdict TEXT DEFAULT 'uncertain',
                confidence REAL,
                context TEXT,
                user_label TEXT,
                correct_fact TEXT,
                created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
                processed INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_uncertain_processed
            ON uncertain_samples(processed)
        """)


















        conn.commit()


def find_applied_correction(claim: str, fact: str) -> Optional[dict]:
    """优先查询：查找已应用的纠正记录"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM feedback WHERE claim = ? AND fact = ? AND applied = 1 ORDER BY id DESC LIMIT 1",
            (claim, fact)
        ).fetchone()
    if row:
        return dict(row)
    return None


def find_similar(claim: str, fact: str) -> Optional[dict]:
    """宽松查询：找相似记录（已应用或待复核）"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM feedback WHERE claim = ? AND fact = ? AND applied >= 0 ORDER BY id DESC LIMIT 1",
            (claim, fact)
        ).fetchone()
    if row:
        return dict(row)
    return None


def insert_record(record: FeedbackRecord) -> int:
    """插入反馈记录，返回 id"""
    d = asdict(record)
    d.pop("id", None)
    if d.get("created_at") is None:
        d["created_at"] = time.time()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO feedback (claim, fact, verdict, confidence, evidence, source, user_correction, rematch_key, applied, created_at)
               VALUES (:claim, :fact, :verdict, :confidence, :evidence, :source, :user_correction, :rematch_key, :applied, :created_at)""",
            d
        )
        conn.commit()
        return cur.lastrowid


def apply_correction(record_id: int, correction: str) -> None:
    """人工确认某条记录"""
    with _connect() as conn:
        conn.execute(
            "UPDATE feedback SET user_correction = ?, applied = 1 WHERE id = ?",
            (correction, record_id)
        )
        conn.commit()


def set_rematch(record_id: int, correct_key: str) -> None:
    """重新指定正确的KB匹配键"""
    with _connect() as conn:
        conn.execute(
            "UPDATE feedback SET rematch_key = ?, applied = 1 WHERE id = ?",
            (correct_key, record_id)
        )
        conn.commit()


def find_rematch(claim: str) -> Optional[str]:
    """查找该断言的重新匹配记录，返回正确KB键"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT rematch_key FROM feedback WHERE claim = ? AND rematch_key IS NOT NULL AND applied = 1 ORDER BY id DESC LIMIT 1",
            (claim,)
        ).fetchone()
    if row:
        return row["rematch_key"]
    return None


def reject_record(record_id: int) -> None:
    """驳回某条记录"""
    with _connect() as conn:
        conn.execute(
            "UPDATE feedback SET applied = -1 WHERE id = ?",
            (record_id,)
        )
        conn.commit()


def get_pending(page: int = 1, per_page: int = 20) -> list[dict]:
    """获取待复核记录（分页）"""
    offset = (page - 1) * per_page
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM feedback WHERE applied = 0 ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending_count() -> int:
    """待复核记录总数"""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM feedback WHERE applied = 0").fetchone()
    return row["cnt"]


def get_stats() -> dict:
    """统计概览"""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM feedback").fetchone()["cnt"]
        pending = conn.execute("SELECT COUNT(*) as cnt FROM feedback WHERE applied = 0").fetchone()["cnt"]
        applied = conn.execute("SELECT COUNT(*) as cnt FROM feedback WHERE applied = 1").fetchone()["cnt"]
        rejected = conn.execute("SELECT COUNT(*) as cnt FROM feedback WHERE applied = -1").fetchone()["cnt"]
    return {"total": total, "pending": pending, "applied": applied, "rejected": rejected}


# 初始化
init_db()
