"""滚动产物路径：每次运行覆盖同一组文件，不按日期堆积。"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output"

RAW_MD_NAME = "ai_news.md"
RAW_ITEMS_NAME = "raw_items.json"
REFINED_MD_NAME = "refined.md"
NEWS_JSON_NAME = "news.json"
CARD_HTML_NAME = "card.html"

RAW_MD_PATH = OUTPUT_DIR / RAW_MD_NAME
RAW_ITEMS_PATH = OUTPUT_DIR / RAW_ITEMS_NAME
REFINED_MD_PATH = OUTPUT_DIR / REFINED_MD_NAME
NEWS_JSON_PATH = OUTPUT_DIR / NEWS_JSON_NAME
CARD_HTML_PATH = OUTPUT_DIR / CARD_HTML_NAME

# 历史按日期命名的产物，运行后清理
_DATED_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_(ai_news|refined|news|card)\.(md|json|html)$"
)


def ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def cleanup_dated_artifacts() -> list[str]:
    """删除 output/ 与项目根下的日期前缀产物，只保留滚动文件。"""
    removed = []
    for base in (OUTPUT_DIR, SCRIPT_DIR):
        if not base.exists():
            continue
        for p in base.iterdir():
            if not p.is_file():
                continue
            if _DATED_NAME_RE.match(p.name):
                try:
                    p.unlink()
                    removed.append(str(p))
                except OSError:
                    pass
    return removed
