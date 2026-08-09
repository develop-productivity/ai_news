#!/usr/bin/python3
"""
AI 日报 API 服务
=================
提供 /api/news (JSON) 和 /api/cards (HTML) 两个接口，
供 zero-to-tech 等前端项目请求最新日报内容。

用法:
  python3 server.py                  # 默认 0.0.0.0:8001
  python3 server.py --port 8002      # 指定端口
  python3 server.py --date latest   # 使用本地已有最新数据
"""

import json
import glob
import argparse
from pathlib import Path
from datetime import date

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output"

app = FastAPI(title="AI Daily News API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def find_latest_date():
    """在 output/ 中找最新日期的 news.json"""
    candidates = sorted(OUTPUT_DIR.glob("*_news.json"), reverse=True)
    if not candidates:
        return None
    fn = candidates[0].stem  # e.g., "2026-06-13_news"
    return fn.replace("_news", "")


def load_news(date_str=None):
    """加载指定日期（或最新）的 news.json"""
    ds = date_str or find_latest_date()
    if not ds:
        return None
    path = OUTPUT_DIR / f"{ds}_news.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_cards(date_str=None):
    """加载指定日期（或最新）的 cards.html"""
    ds = date_str or find_latest_date()
    if not ds:
        return None
    path = OUTPUT_DIR / f"{ds}_card.html"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


@app.get("/api/v1/ai_news/news")
def get_news(date: str = Query(default=None, description="日期 YYYY-MM-DD，不填则返回最新")):
    """返回结构化日报 JSON"""
    data = load_news(date)
    if not data:
        return JSONResponse(
            {"error": "no data", "hint": "请先运行 ai_news_aggregator.py → produce_news.py"},
            status_code=404,
        )
    return data


@app.get("/api/v1/ai_news/cards")
def get_cards(date: str = Query(default=None, description="日期 YYYY-MM-DD")):
    """返回渲染好的 HTML 卡片"""
    html = load_cards(date)
    if not html:
        return HTMLResponse(
            "<p style='padding:2rem;color:#888'>暂无卡片数据，请先运行 generate_html.py</p>",
            status_code=404,
        )
    return HTMLResponse(html)


@app.get("/api/v1/ai_news/dates")
def list_dates():
    """列出所有可用日期"""
    files = sorted(OUTPUT_DIR.glob("*_news.json"), reverse=True)
    dates = [f.stem.replace("_news", "") for f in files]
    return {"dates": dates, "latest": dates[0] if dates else None}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="AI Daily News API server")
    p.add_argument("--port", type=int, default=8001, help="Listen port")
    p.add_argument("--host", default="0.0.0.0", help="Listen host")
    args = p.parse_args()

    latest = find_latest_date()
    print("="*50)
    print(f"  📰 AI Daily News API")
    print(f"  📡 http://{args.host}:{args.port}")
    print(f"  📅 最新数据: {latest or '暂无，请先采集'}")
    print(f"  🔗 /api/v1/ai_news/news   — 结构化日报 JSON")
    print(f"  🔗 /api/v1/ai_news/cards  — 渲染好的 HTML 卡片")
    print(f"  🔗 /api/v1/ai_news/dates  — 可用日期列表")
    print("="*50)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
