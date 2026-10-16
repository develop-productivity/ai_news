#!/usr/bin/python3
"""
RSS 信源采集 — 从 sources_config.json 加载信源，feedparser 解析，统一为标准条目。

条目结构:
  {id, title, url, summary, source, source_id, tier, tags, section_key, published_at}

用法:
  python3 rss_sources.py            # 抓取全部信源并打印统计（调试用）
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import feedparser
import requests

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "sources_config.json"

USER_AGENT = "Mozilla/5.0 (compatible; AI-News-Aggregator/3.0; +https://github.com/develop-productivity/ai_news)"
TIMEOUT = 20
PER_SOURCE_LIMIT = 8          # 与 AIHOT initialBackfillLimit 一致
DEFAULT_MAX_AGE_HOURS = 72


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def tier_thresholds() -> dict:
    try:
        return load_config().get("tier_thresholds", {})
    except (OSError, json.JSONDecodeError):
        return {"T1": 60, "T1.5": 65, "T2": 76, "default": 65}


def item_id(url: str, title: str = "") -> str:
    key = (url or title).strip().lower().rstrip("/")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def clean_text(raw: str, max_len: int = 400) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Substack/WordPress 常见尾巴
    text = re.sub(r"\s*(The (?:post|article) .+ appeared first on .+|Continue reading.*|Read more.*)$", "", text)
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


def _entry_time(entry) -> Optional[dt.datetime]:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            try:
                return dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def fetch_source(src: dict, now: dt.datetime, reject: Optional[Callable[[str], bool]] = None) -> dict:
    """抓取单个信源。返回 {source, items, ok, error, fetched}。"""
    result = {"source": src, "items": [], "ok": False, "error": "", "fetched": 0}
    try:
        resp = requests.get(src["url"], headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except requests.RequestException as e:
        result["error"] = str(e)[:200]
        return result

    if feed.bozo and not feed.entries:
        result["error"] = f"parse error: {feed.get('bozo_exception')}"[:200]
        return result

    max_age = dt.timedelta(hours=src.get("max_age_hours", DEFAULT_MAX_AGE_HOURS))
    result["ok"] = True
    result["fetched"] = len(feed.entries)

    for entry in feed.entries:
        if len(result["items"]) >= PER_SOURCE_LIMIT:
            break
        title = clean_text(entry.get("title", ""), 200)
        url = entry.get("link", "")
        if not title or not url:
            continue
        published = _entry_time(entry)
        if published and now - published > max_age:
            continue
        if reject and reject(title):
            continue
        content = ""
        if entry.get("content"):
            content = entry["content"][0].get("value", "")
        summary = clean_text(entry.get("summary", "") or content)
        result["items"].append({
            "id": item_id(url, title),
            "title": title,
            "url": url,
            "summary": summary,
            "source": src["name"],
            "source_id": src["id"],
            "tier": src.get("tier", ""),
            "tags": src.get("tags", []),
            "section_key": src.get("section", "intl_news"),
            "published_at": published.isoformat() if published else None,
        })
    return result


def fetch_all(reject: Optional[Callable[[str], bool]] = None, workers: int = 8) -> tuple[list[dict], list[dict]]:
    """并发抓取全部启用信源。返回 (items, statuses)。"""
    sources = [s for s in load_config()["sources"] if s.get("enabled", True) and s.get("type") == "rss"]
    now = dt.datetime.now(dt.timezone.utc)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda s: fetch_source(s, now, reject), sources))

    items, statuses = [], []
    for r in results:
        src = r["source"]
        items.extend(r["items"])
        statuses.append({
            "id": src["id"], "name": src["name"], "tier": src.get("tier", ""),
            "url": src["url"], "ok": r["ok"], "error": r["error"],
            "fetched": r["fetched"], "kept": len(r["items"]),
        })
        mark = "✓" if r["ok"] else "✗"
        detail = f"{len(r['items'])}/{r['fetched']} 条" if r["ok"] else r["error"][:80]
        print(f"    {mark} [{src.get('tier', '-'):>2}] {src['name']}: {detail}")

    try:
        from history import record_source_status
        record_source_status(statuses)
    except Exception as e:  # 状态记录失败不影响采集
        print(f"    [WARN] 信源状态记录失败: {e}")

    return items, statuses


if __name__ == "__main__":
    items, statuses = fetch_all()
    ok = sum(1 for s in statuses if s["ok"])
    print(f"\n{ok}/{len(statuses)} 信源成功，共 {len(items)} 条")
