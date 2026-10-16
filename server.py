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
import datetime
import hashlib
from pathlib import Path

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

def _base_context(request: Request) -> dict:
    return {"base": request.state.base}


templates = Jinja2Templates(directory=str(TEMPLATE_DIR), context_processors=[_base_context])


@app.middleware("http")
async def mount_prefix(request: Request, call_next):
    """反向代理挂在子路径下（如 /news/）时，nginx 传 X-Forwarded-Prefix，页面内链接据此加前缀。
    直接访问或挂在独立域名下时前缀为空。"""
    prefix = request.headers.get("x-forwarded-prefix", "").strip().rstrip("/")
    request.state.base = prefix if prefix.startswith("/") else ""
    return await call_next(request)


def _parse_time(value):
    if not value:
        return None
    try:
        t = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def ago(value):
    """ISO 时间 → “3 小时前”。"""
    t = _parse_time(value)
    if not t:
        return ""
    secs = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
    if secs < 3600:
        return f"{max(1, int(secs // 60))} 分钟前"
    if secs < 86400:
        return f"{int(secs // 3600)} 小时前"
    if secs < 86400 * 30:
        return f"{int(secs // 86400)} 天前"
    return t.strftime("%Y-%m-%d")


def safe_url(value):
    """只放行 http(s) 链接，防止 javascript: 之类注入。"""
    v = (value or "").strip()
    return v if v.startswith(("http://", "https://")) else ""


templates.env.filters["ago"] = ago
templates.env.filters["safe_url"] = safe_url


def normalize(data):
    """给旧快照补齐 id 等字段，保证前端可以按 id 打开详情。"""
    if not data:
        return data
    for sec in data.get("sections", []):
        for item in sec.get("items", []):
            if not item.get("id"):
                key = (item.get("url") or item.get("title_original") or item.get("title") or "").strip().lower()
                item["id"] = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
            item["url"] = safe_url(item.get("url"))
            item.setdefault("source", "")
    return data


def build_payload(data):
    """页面内嵌给前端详情弹窗用的数据：{items: {id: item}, sections: {...}}。"""
    items, sections = {}, {}
    for sec in (data or {}).get("sections", []):
        if sec.get("accent") == "hot":
            continue
        key = sec.get("key") or sec.get("label")
        ids = []
        for item in sec.get("items", []):
            entry = dict(item)
            entry["section"] = sec.get("label", "")
            entry["accent"] = sec.get("accent", "")
            entry["published_ago"] = ago(item.get("published_at"))
            items[item["id"]] = entry
            ids.append(item["id"])
        sections[key] = {"label": sec.get("label", ""), "icon": sec.get("icon", ""),
                         "accent": sec.get("accent", ""), "ids": ids}
    # 热门条目若在原板块被裁掉，也要能打开
    for sec in (data or {}).get("sections", []):
        if sec.get("accent") == "hot":
            for item in sec.get("items", []):
                if item["id"] not in items:
                    entry = dict(item)
                    entry["section"] = item.get("source_section", "")
                    entry["published_ago"] = ago(item.get("published_at"))
                    items[item["id"]] = entry
    return {"items": items, "sections": sections}


def _legacy_news_path():
    candidates = sorted(OUTPUT_DIR.glob("*_news.json"), reverse=True)
    return candidates[0] if candidates else None


def load_news(date_str=None):
    return normalize(_load_news(date_str))


def _load_news(date_str=None):
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
        "payload": build_payload(data),
        "active": "home",
    })


@app.get("/hot", response_class=HTMLResponse)
def hot(request: Request):
    data = load_news()
    items = _collect_hot_items(data) if data else []
    return templates.TemplateResponse(request, "site/hot.html", {
        "items": items,
        "data": data,
        "payload": build_payload(data),
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
        "payload": build_payload(data),
        "active": "archive",
    })


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    data = load_news()
    try:
        from history import list_source_status
        sources = list_source_status()
    except Exception:
        sources = []
    return templates.TemplateResponse(request, "site/about.html", {
        "data": data,
        "sources": sources,
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


@app.get("/api/v1/ai_news/sources")
def get_sources():
    try:
        from history import list_source_status
        return {"sources": list_source_status()}
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
    print("  🔗 /api/v1/ai_news/news | hot | cards | dates | history | search | sources")
    print("=" * 50)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
