"""
Generate HTML news cards for screenshot/video production.

优先读 output/news.json（部署 pull 后即可渲染）；
若无 json，再回退 refined.md / ai_news.md。

Output: output/card.html（滚动覆盖）

Usage:
    python generate_html.py                           # 优先 news.json
    python generate_html.py path/to/news.json         # 指定 json/md
"""

import re
import sys
import json
from pathlib import Path
from datetime import date
from typing import Optional

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    print("[ERROR] Jinja2 not installed. Run: pip install jinja2")
    sys.exit(1)

from paths import (
    REFINED_MD_PATH,
    CARD_HTML_PATH,
    RAW_MD_PATH,
    NEWS_JSON_PATH,
    OUTPUT_DIR as PROD_DIR,
    cleanup_dated_artifacts,
)

ICON_TO_SYMBOL = {
    "star": "★",
    "diamond": "◇",
    "building": "◆",
    "globe": "●",
    "message-circle": "○",
}

# ─── Constants ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
TEMPLATE_DIR = SCRIPT_DIR / "templates"

TEMPLATE_NAME = "news_cards.html"
today_str = date.today().isoformat

# Section header → card config mapping
SECTION_MAP = [
    ("github", {
        "label": "GitHub Trending",
        "icon": "★",
        "accent": "github",
    }),
    ("hugging", {  # matches "HuggingFace" / "hugging Face"
        "label": "HF Daily Papers",
        "icon": "◇",
        "accent": "paper",
    }),
    ("论文精选", {  # today's papers
        "label": "今日论文精选",
        "icon": "◇",
        "accent": "paper",
    }),
    ("arxiv", {
        "label": "ArXiv Papers",
        "icon": "◇",
        "accent": "paper",
    }),
    ("搜索", {
        "label": "Search & Rec Papers",
        "icon": "◇",
        "accent": "paper",
    }),
    ("国际大模型公司", {
        "label": "国际公司动态",
        "icon": "◆",
        "accent": "company",
    }),
    ("国内大模型公司", {
        "label": "国内公司动态",
        "icon": "◆",
        "accent": "company",
    }),
    ("公司动态", {
        "label": "AI Company",
        "icon": "◆",
        "accent": "company",
    }),
    ("国内 AI 行业", {
        "label": "国内 AI 新闻",
        "icon": "●",
        "accent": "news",
    }),
    ("国际 AI 行业", {
        "label": "AI News",
        "icon": "●",
        "accent": "news",
    }),
    ("社区", {
        "label": "社区热点",
        "icon": "●",
        "accent": "oss",
    }),
    ("开源", {
        "label": "Open Source LLM",
        "icon": "●",
        "accent": "oss",
    }),
]

# ─── Parsing ────────────────────────────────────────────────────────────────


def cards_from_news_json(data: dict) -> list[dict]:
    """从 produce_news 产出的 news.json 转成模板卡片结构。"""
    cards = []
    for sec in data.get("sections", []):
        entries = []
        for item in sec.get("items", [])[:8]:
            title = (item.get("title") or "").strip()
            detail = (item.get("detail") or "").strip()
            if not title:
                continue
            text = title if not detail else f"{title} — {detail}"
            entries.append({"text": text[:90], "is_subheader": False})
        if not entries:
            continue
        cards.append({
            "label": sec.get("label") or "AI News",
            "icon": ICON_TO_SYMBOL.get(sec.get("icon"), "●"),
            "accent": sec.get("accent") or "news",
            "entries": entries,
        })
    return cards


def parse_news_json(file_path: Path) -> tuple[list[dict], date]:
    data = json.loads(file_path.read_text(encoding="utf-8"))
    cards = cards_from_news_json(data)
    d = date.today()
    if data.get("date"):
        try:
            d = date.fromisoformat(data["date"])
        except ValueError:
            pass
    return cards, d


def parse_markdown(file_path: Path) -> list[dict]:
    """Parse ai_news markdown into structured card data."""
    text = file_path.read_text(encoding="utf-8")

    # Split by ## headers
    sections_raw = re.split(r"^## ", text, flags=re.MULTILINE)
    cards = []

    for sec in sections_raw:
        lines = sec.strip().split("\n")
        if not lines or not lines[0].strip():
            continue
        header = lines[0].strip()

        # Determine card config
        card_config = None
        for key, config in SECTION_MAP:
            if key.lower() in header.lower():
                card_config = dict(config)
                break
        if not card_config:
            continue

        # Parse items
        items = []
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue

            # Handle company subsections (### OpenAI)
            sub_match = re.match(r"^###\s+(.+)$", line)
            if sub_match:
                # If we have company sections, treat each as a separate text
                items.append({"text": f"[{sub_match.group(1).strip()}]", "is_subheader": True})
                continue

            # Handle markdown links: - [title](url) or - [text](url) - more text
            link_match = re.match(r"^-\s+\[([^\]]+)\]\(([^)]+)\)(?:\s*-\s*(.+))?$", line)
            if link_match:
                title = link_match.group(1).strip()
                desc = (link_match.group(3) or "").strip()
                text = f"{title}" if not desc else f"{title} — {desc}"
                items.append({"text": text[:90], "is_subheader": False})
                continue

            # Handle bare links: - /repo - desc
            bare_match = re.match(r"^-\s+(/\S+)(?:\s*-\s*(.+))?$", line)
            if bare_match:
                repo = bare_match.group(1).strip()
                desc = (bare_match.group(2) or "").strip()
                text = f"{repo}" if not desc else f"{repo} — {desc}"
                items.append({"text": text[:90], "is_subheader": False})
                continue

            # Handle plain list items
            plain_match = re.match(r"^-\s+(.+)$", line)
            if plain_match:
                text = plain_match.group(1).strip()[:90]
                items.append({"text": text, "is_subheader": False})
                continue

        if items:
            items = items[:8]  # Cap at 8 per card for layout
            card_config["entries"] = items
            card_config["accent"] = card_config.get("accent", "company")
            cards.append(card_config)

    return cards


# ─── Layout ─────────────────────────────────────────────────────────────────


def arrange_cards(cards: list[dict]) -> list[list[dict]]:
    """Arrange cards into rows for 1920×1080 layout; 2 rows, 3 cols each."""
    priority = [
        "GitHub 热门趋势", "GitHub Trending",
        "HF 论文精选", "HF Daily Papers", "今日论文精选",
        "国际 AI 新闻", "AI News",
        "国内 AI 新闻",
        "国际公司动态", "国内公司动态",
        "社区热点", "Search & Rec Papers", "ArXiv Papers",
    ]

    ordered = []
    for name in priority:
        for c in cards:
            if c["label"] == name and c not in ordered:
                ordered.append(c)
                break

    for c in cards:
        if c not in ordered:
            ordered.append(c)

    rows = []
    for i in range(0, len(ordered), 3):
        rows.append(ordered[i:i + 3])
    return rows


# ─── Date helpers ───────────────────────────────────────────────────────────


def _date_format(d: date) -> str:
    """Format like '2026.06.13 周六'"""
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    wd = weekdays[d.weekday()]
    return f"{d.year}.{d.month:02d}.{d.day:02d} {wd}"


def _date_compact(d: date) -> str:
    """Format like '2026.06.13'"""
    return f"{d.year}.{d.month:02d}.{d.day:02d}"


# ─── Main ───────────────────────────────────────────────────────────────────


def render_cards_html(cards: list[dict], d: date) -> str:
    rows = arrange_cards(cards)
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template(TEMPLATE_NAME)
    return template.render(
        date=_date_format(d),
        date_compact=_date_compact(d),
        rows=rows,
    )


def html_from_news_json(data: dict) -> str:
    """供 server.py 在无 card.html 时即时渲染。"""
    cards = cards_from_news_json(data)
    if not cards:
        return ""
    d = date.today()
    if data.get("date"):
        try:
            d = date.fromisoformat(data["date"])
        except ValueError:
            pass
    return render_cards_html(cards, d)


def generate_html(source_path: Optional[str] = None, output_path: Optional[str] = None) -> Path:
    """从 news.json（优先）或 markdown 生成 HTML 卡片。"""
    src: Optional[Path] = Path(source_path) if source_path else None
    if src is None:
        if NEWS_JSON_PATH.exists():
            src = NEWS_JSON_PATH
        elif REFINED_MD_PATH.exists():
            src = REFINED_MD_PATH
        elif RAW_MD_PATH.exists():
            src = RAW_MD_PATH

    if src is None or not src.exists():
        print("[ERROR] 未找到 news.json / refined.md，请先运行: python3 produce_news.py")
        print(f"  查找路径: {NEWS_JSON_PATH}")
        sys.exit(1)

    print(f"[HTML] 读取: {src}")

    d = date.today()
    if src.suffix.lower() == ".json":
        cards, d = parse_news_json(src)
    else:
        cards = parse_markdown(src)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", str(src.name))
        if date_match:
            d = date.fromisoformat(date_match.group(1))
        elif NEWS_JSON_PATH.exists():
            try:
                meta = json.loads(NEWS_JSON_PATH.read_text(encoding="utf-8"))
                if meta.get("date"):
                    d = date.fromisoformat(meta["date"])
            except (json.JSONDecodeError, ValueError, OSError):
                pass

    if not cards:
        print("[ERROR] 未能解析出任何卡片数据")
        sys.exit(1)

    print(f"[HTML] 解析到 {len(cards)} 个卡片")
    rows = arrange_cards(cards)
    print(f"[HTML] 布局: {len(rows)} 行 × {max(len(r) for r in rows)} 列")

    html = render_cards_html(cards, d)
    out_file = Path(output_path) if output_path else CARD_HTML_PATH
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")

    removed = cleanup_dated_artifacts()
    if removed:
        print(f"[HTML] 已清理旧日期产物: {len(removed)} 个")

    print(f"[HTML] 已生成（滚动覆盖）: {out_file}")
    return out_file


if __name__ == "__main__":
    args = sys.argv[1:]
    src = None
    out = None
    i = 0
    while i < len(args):
        if args[i] == "--date" and i + 1 < len(args):
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            out = args[i + 1]
            i += 2
        elif not args[i].startswith("--"):
            src = args[i]
            i += 1
        else:
            i += 1

    generate_html(src, out)
