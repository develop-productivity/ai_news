#!/usr/bin/python3
"""
AI 日报 API + 独立网站
========================
提供:
  网站页面: /  /hot  /about  /history  /archive/<date>
  JSON API: /api/v1/ai_news/news  /api/v1/ai_news/hot  /api/v1/ai_news/dates  /api/v1/ai_news/cards
           /api/v1/ai_news/history  /api/v1/ai_news/search?q=

产物为滚动单份：output/news.json

用法:
  python3 server.py                  # 默认 0.0.0.0:8001
  python3 server.py --port 8002
"""

import json
import argparse
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from paths import NEWS_JSON_PATH, CARD_HTML_PATH, OUTPUT_DIR

SCRIPT_DIR = Path(__file__).parent
TEMPLATE_DIR = SCRIPT_DIR / "templates"
STATIC_DIR = SCRIPT_DIR / "static"

app = FastAPI(title="AI Daily News", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _legacy_news_path():
    candidates = sorted(OUTPUT_DIR.glob("*_news.json"), reverse=True)
    return candidates[0] if candidates else None


def load_news(date_str=None):
    """加载新闻数据：优先 news.json，回退到历史数据库。"""
    path = NEWS_JSON_PATH if NEWS_JSON_PATH.exists() else _legacy_news_path()
    if path and path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if date_str and data.get("date") and date_str != data.get("date"):
            # Try history DB
            try:
                from history import load_snapshot
                data = load_snapshot(date_str)
                return data
            except Exception:
                return None
        return data
    # No news.json, try history DB
    try:
        from history import load_snapshot, load_latest
        if date_str:
            return load_snapshot(date_str)
        return load_latest()
    except Exception:
        return None


def load_cards():
    if CARD_HTML_PATH.exists():
        return CARD_HTML_PATH.read_text(encoding="utf-8")
    legacy = sorted(OUTPUT_DIR.glob("*_card.html"), reverse=True)
    if legacy:
        return legacy[0].read_text(encoding="utf-8")
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


def _collect_hot_items(data):
    if not data or not data.get("sections"):
        return []
    items = []
    for sec in data["sections"]:
        if sec.get("accent") == "hot":
            continue
        for item in sec.get("items", []):
            entry = dict(item)
            entry["source_section"] = sec.get("label", "")
            items.append(entry)
    items.sort(key=lambda x: x.get("score", 0), reverse=True)
    return items


# ================================================================
# 网站页面
# ================================================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    data = load_news()
    return templates.TemplateResponse(request, "site/index.html", {
        "data": data or {"sections": []},
        "active": "home",
    })


@app.get("/hot", response_class=HTMLResponse)
def hot(request: Request):
    data = load_news()
    items = _collect_hot_items(data) if data else []
    return templates.TemplateResponse(request, "site/hot.html", {
        "items": items,
        "data": data,
        "active": "hot",
    })


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request):
    try:
        from history import list_dates
        dates = list_dates(limit=30)
    except Exception:
        dates = []
    return templates.TemplateResponse(request, "site/history.html", {
        "dates": dates,
        "data": {},
        "active": "history",
    })


@app.get("/archive/{date_str}", response_class=HTMLResponse)
def archive(request: Request, date_str: str):
    data = load_news(date_str)
    return templates.TemplateResponse(request, "site/archive.html", {
        "data": data or {"sections": [], "date": date_str, "date_formatted": date_str, "weekday": ""},
        "active": "archive",
    })


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    data = load_news()
    return templates.TemplateResponse(request, "site/about.html", {
        "data": data,
        "active": "about",
    })


# ================================================================
# JSON API
# ================================================================

@app.get("/api/v1/ai_news/news")
def get_news(date: str = Query(default=None)):
    data = load_news(date)
    if not data:
        return JSONResponse({"error": "no data"}, status_code=404)
    return data


@app.get("/api/v1/ai_news/hot")
def get_hot():
    data = load_news()
    if not data:
        return JSONResponse({"error": "no data"}, status_code=404)
    items = _collect_hot_items(data)
    return {
        "date": data.get("date"),
        "date_formatted": data.get("date_formatted"),
        "weekday": data.get("weekday"),
        "items": items,
        "total": len(items),
    }


@app.get("/api/v1/ai_news/cards")
def get_cards(date: str = Query(default=None)):
    html = load_cards()
    if not html:
        return HTMLResponse("<p style='padding:2rem;color:#888'>暂无卡片</p>", status_code=404)
    return HTMLResponse(html)


@app.get("/api/v1/ai_news/dates")
def list_dates_api():
    try:
        from history import list_dates
        dates = list_dates(limit=30)
    except Exception:
        dates = []
    data = load_news()
    latest = data.get("date") if data else None
    # Merge current date
    if latest and not any(d["date"] == latest for d in dates):
        dates.insert(0, {"date": latest, "total_items": 0, "sections": 0})
    return {"dates": [d["date"] for d in dates], "latest": latest, "details": dates}


@app.get("/api/v1/ai_news/history")
def get_history(limit: int = Query(default=30)):
    try:
        from history import list_dates
        return {"dates": list_dates(limit=limit)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/v1/ai_news/search")
def search(q: str = Query(default="", description="搜索关键词"), limit: int = Query(default=20)):
    if not q:
        return JSONResponse({"error": "missing query param 'q'"}, status_code=400)
    try:
        from history import search_items
        results = search_items(q, limit=limit)
        return {"query": q, "results": results, "total": len(results)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="AI Daily News API + Website")
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args()

    data = load_news()
    latest = data.get("date") if data else None
    print("=" * 50)
    print("  📰 AI Daily News — API + Website")
    print(f"  📡 http://{args.host}:{args.port}")
    print(f"  📅 当前滚动数据: {latest or '暂无'}")
    print("  🌐 /  /hot  /history  /archive/<date>  /about")
    print("  🔗 /api/v1/ai_news/news | hot | cards | dates | history | search")
    print("=" * 50)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
