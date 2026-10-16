#!/usr/bin/python3
"""
历史记录模块 — 用 SQLite 存储每日新闻快照，支持历史查询。

每次 produce_news.py 运行时，将当前 news.json 存入数据库。
server.py 读取时优先从数据库取，支持按日期查询历史。
"""

import sqlite3
import json
import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "output" / "history.db"


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表。"""
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_news (
            date TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL,
            total_items INTEGER DEFAULT 0,
            section_count INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT,
            score INTEGER DEFAULT 0,
            section TEXT,
            FOREIGN KEY (date) REFERENCES daily_news(date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_items_date ON news_items(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_items_score ON news_items(score DESC)")
    conn.commit()
    conn.close()


def save_snapshot(data: dict):
    """保存当日新闻快照到数据库。"""
    init_db()
    conn = _get_db()
    date_str = data.get("date", datetime.date.today().isoformat())
    sections = data.get("sections", [])
    total_items = sum(len(s.get("items", [])) for s in sections)

    # 删除旧记录（如果有）
    conn.execute("DELETE FROM daily_news WHERE date = ?", (date_str,))
    conn.execute("DELETE FROM news_items WHERE date = ?", (date_str,))

    # 保存完整 JSON
    conn.execute(
        "INSERT INTO daily_news (date, data, created_at, total_items, section_count) VALUES (?, ?, ?, ?, ?)",
        (date_str, json.dumps(data, ensure_ascii=False), datetime.datetime.now().isoformat(), total_items, len(sections))
    )

    # 保存条目索引（用于搜索）
    for sec in sections:
        sec_label = sec.get("label", "")
        for item in sec.get("items", []):
            conn.execute(
                "INSERT INTO news_items (date, title, detail, score, section) VALUES (?, ?, ?, ?, ?)",
                (date_str, item.get("title", ""), item.get("detail", ""), item.get("score", 0), sec_label)
            )

    conn.commit()
    conn.close()
    print(f"  [历史] 已保存 {date_str}: {total_items} 条, {len(sections)} 个板块")


def load_snapshot(date_str: str) -> Optional[dict]:
    """从数据库加载指定日期的新闻。"""
    init_db()
    conn = _get_db()
    row = conn.execute("SELECT data FROM daily_news WHERE date = ?", (date_str,)).fetchone()
    conn.close()
    if row:
        return json.loads(row["data"])
    return None


def load_latest() -> Optional[dict]:
    """加载最新的新闻快照。"""
    init_db()
    conn = _get_db()
    row = conn.execute("SELECT data FROM daily_news ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return json.loads(row["data"])
    return None


def list_dates(limit: int = 30) -> list:
    """列出可用日期。"""
    init_db()
    conn = _get_db()
    rows = conn.execute(
        "SELECT date, total_items, section_count FROM daily_news ORDER BY date DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{"date": r["date"], "total_items": r["total_items"], "sections": r["section_count"]} for r in rows]


def search_items(query: str, limit: int = 20) -> list:
    """搜索历史条目。"""
    init_db()
    conn = _get_db()
    rows = conn.execute(
        "SELECT date, title, detail, score, section FROM news_items WHERE title LIKE ? ORDER BY score DESC LIMIT ?",
        (f"%{query}%", limit)
    ).fetchall()
    conn.close()
    return [{"date": r["date"], "title": r["title"], "detail": r["detail"], "score": r["score"], "section": r["section"]} for r in rows]
