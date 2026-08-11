#!/usr/bin/python3
"""
AI 日报 API 服务
=================
提供 /api/v1/ai_news/news (JSON) 和 /api/v1/ai_news/cards (HTML)，
供 zero-to-tech 等前端项目请求最新日报内容。

产物为滚动单份：output/news.json · output/card.html

用法:
  python3 server.py                  # 默认 0.0.0.0:8001
  python3 server.py --port 8002      # 指定端口
"""

import json
import argparse
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from paths import NEWS_JSON_PATH, CARD_HTML_PATH, OUTPUT_DIR

SCRIPT_DIR = Path(__file__).parent

app = FastAPI(title="AI Daily News API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _legacy_news_path():
    """兼容旧版 {date}_news.json（仅迁移期）。"""
    candidates = sorted(OUTPUT_DIR.glob("*_news.json"), reverse=True)
    return candidates[0] if candidates else None


def load_news(date_str=None):
    """加载滚动 news.json；可选 date 仅作校验。"""
    path = NEWS_JSON_PATH if NEWS_JSON_PATH.exists() else _legacy_news_path()
    if not path or not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if date_str and data.get("date") and date_str != data.get("date"):
        return None
    return data


def load_cards():
    """加载滚动 card.html；若无文件则用 news.json 即时渲染。"""
    if CARD_HTML_PATH.exists():
        return CARD_HTML_PATH.read_text(encoding="utf-8")
    legacy = sorted(OUTPUT_DIR.glob("*_card.html"), reverse=True)
    if legacy:
        return legacy[0].read_text(encoding="utf-8")

    # pull 后通常只有 news.json：即时从 JSON 渲染，避免空白
    data = load_news()
    if not data:
        return None
    try:
        from generate_html import html_from_news_json
        html = html_from_news_json(data)
        return html or None
    except Exception as e:
        print(f"[WARN] cards render from news.json failed: {e}")
        return None


@app.get("/api/v1/ai_news/news")
def get_news(date: str = Query(default=None, description="可选：校验日期 YYYY-MM-DD，不填返回当前滚动版")):
    """返回结构化日报 JSON（滚动单份）。"""
    data = load_news(date)
    if not data:
        return JSONResponse(
            {"error": "no data", "hint": "请先运行 ai_news_aggregator.py → produce_news.py"},
            status_code=404,
        )
    return data


@app.get("/api/v1/ai_news/cards")
def get_cards(date: str = Query(default=None, description="已忽略；始终返回当前滚动版")):
    """返回渲染好的 HTML 卡片（滚动单份）。"""
    html = load_cards()
    if not html:
        return HTMLResponse(
            "<p style='padding:2rem;color:#888'>暂无卡片数据，请先运行 generate_html.py</p>",
            status_code=404,
        )
    return HTMLResponse(html)


@app.get("/api/v1/ai_news/dates")
def list_dates():
    """滚动模式下仅一份；返回当前日期。"""
    data = load_news()
    if not data:
        return {"dates": [], "latest": None}
    d = data.get("date")
    return {"dates": [d] if d else [], "latest": d}


@app.get("/", response_class=HTMLResponse)
def index():
    """根路径直接返回 HTML 卡片，方便浏览器预览。"""
    html = load_cards()
    if not html:
        return HTMLResponse(
            "<p style='padding:2rem;color:#888'>暂无数据，请先运行 produce_news.py</p>",
            status_code=404,
        )
    return HTMLResponse(html)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="AI Daily News API server")
    p.add_argument("--port", type=int, default=8001, help="Listen port")
    p.add_argument("--host", default="0.0.0.0", help="Listen host")
    args = p.parse_args()

    data = load_news()
    latest = data.get("date") if data else None
    print("=" * 50)
    print("  📰 AI Daily News API")
    print(f"  📡 http://{args.host}:{args.port}")
    print(f"  📅 当前滚动数据: {latest or '暂无，请先采集'}")
    print(f"  📁 {NEWS_JSON_PATH}")
    print("  🔗 /api/v1/ai_news/news   — 结构化日报 JSON")
    print("  🔗 /api/v1/ai_news/cards  — 渲染好的 HTML 卡片")
    print("  🔗 /api/v1/ai_news/dates  — 当前日期")
    print("  🔗 /                    — 浏览器预览（HTML 卡片）")
    print("=" * 50)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
