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
    # 旧库迁移：补 url / source 列
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(news_items)")}
    for col in ("url", "source"):
        if col not in cols:
            conn.execute(f"ALTER TABLE news_items ADD COLUMN {col} TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_status (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tier TEXT,
            url TEXT,
            last_fetched TEXT,
            last_ok TEXT,
            last_error TEXT,
            error_count INTEGER DEFAULT 0,
            last_kept INTEGER DEFAULT 0
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
        if sec.get("accent") == "hot":
            continue  # 热门是其他板块的副本，避免搜索结果重复
        sec_label = sec.get("label", "")
        for item in sec.get("items", []):
            conn.execute(
                "INSERT INTO news_items (date, title, detail, score, section, url, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (date_str, item.get("title", ""), item.get("detail", ""), item.get("score", 0), sec_label,
                 item.get("url", ""), item.get("source", ""))
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
        "SELECT date, title, detail, score, section, url, source FROM news_items "
        "WHERE title LIKE ? OR detail LIKE ? ORDER BY date DESC, score DESC LIMIT ?",
        (f"%{query}%", f"%{query}%", limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_source_status(statuses: list):
    """记录每个信源本次采集结果；连续失败累加 error_count，成功清零。"""
    init_db()
    conn = _get_db()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for s in statuses:
        conn.execute("""
            INSERT INTO source_status (id, name, tier, url, last_fetched, last_ok, last_error, error_count, last_kept)
            VALUES (:id, :name, :tier, :url, :now, CASE WHEN :ok THEN :now END, :error, CASE WHEN :ok THEN 0 ELSE 1 END, :kept)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name, tier = excluded.tier, url = excluded.url,
                last_fetched = excluded.last_fetched,
                last_ok = COALESCE(excluded.last_ok, source_status.last_ok),
                last_error = excluded.last_error,
                error_count = CASE WHEN :ok THEN 0 ELSE source_status.error_count + 1 END,
                last_kept = excluded.last_kept
        """, {**s, "now": now, "ok": 1 if s["ok"] else 0})
    conn.commit()
    conn.close()


def list_source_status() -> list:
    init_db()
    conn = _get_db()
    rows = conn.execute("SELECT * FROM source_status ORDER BY tier, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]
