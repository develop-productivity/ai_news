"""
Generate HTML news cards from ai_news refined markdown.
Creates a 1920×1080 card layout for screenshot/video production.

Input:  ai_new_product/{date}_refined.md
Output: ai_new_product/{date}_card.html

Usage:
    python generate_html.py                           # auto-detect today's refined
    python generate_html.py --date 2026-06-13         # specified date
    python generate_html.py path/to/file.md           # custom file
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

# ─── Constants ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
TEMPLATE_DIR = SCRIPT_DIR / "templates"
# Try to find ai_new_product relative to project structure
for candidate in [
    SCRIPT_DIR.parent.parent / "ai_new_product" / "processed",
    SCRIPT_DIR.parent / "ai_new_product" / "processed",
]:
    if candidate.exists():
        PROD_DIR = candidate
        break
else:
    PROD_DIR = SCRIPT_DIR.parent / "ai_new_product" / "processed"

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
    # Priority order matching the original markdown
    priority = ["GitHub Trending", "HF Daily Papers", "今日论文精选",
                "AI News", "国内 AI 新闻",
                "国际公司动态", "国内公司动态",
                "Search & Rec Papers", "ArXiv Papers", "社区热点"]

    ordered = []
    for name in priority:
        for c in cards:
            if c["label"] == name:
                ordered.append(c)
                break

    # Fill remaining if any
    for c in cards:
        if c not in ordered:
            ordered.append(c)

    # Split into rows of 3 cols each
    rows = []
    for i in range(0, len(ordered), 3):
        rows.append(ordered[i:i+3])
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


def generate_html(md_path: Optional[str] = None, output_path: Optional[str] = None) -> Path:
    """Generate HTML news cards from markdown. Returns HTML file path."""
    # Resolve input
    if md_path:
        md_file = Path(md_path)
    else:
        # Auto-detect today's refined.md from ai_new_product
        td = date.today().isoformat()
        md_file = PROD_DIR / f"{td}_refined.md"
        if not md_file.exists():
            # Also check raw file
            raw_dir = SCRIPT_DIR
            md_file = raw_dir / f"{td}_ai_news.md"

    if not md_file.exists():
        print(f"[ERROR] 未找到精炼版文件，请先运行: python3 produce_news.py")
        print(f"  查找路径: {md_file}")
        sys.exit(1)

    print(f"[HTML] 读取: {md_file}")

    # Parse
    cards = parse_markdown(md_file)
    if not cards:
        print("[ERROR] 未能从 markdown 解析出任何卡片数据")
        sys.exit(1)

    print(f"[HTML] 解析到 {len(cards)} 个卡片")

    # Arrange layout
    rows = arrange_cards(cards)
    print(f"[HTML] 布局: {len(rows)} 行 × {max(len(r) for r in rows)} 列")

    # Resolve date from filename
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", str(md_file.name))
    d = date.fromisoformat(date_match.group(1)) if date_match else date.today()

    # Render
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template(TEMPLATE_NAME)
    html = template.render(
        date=_date_format(d),
        date_compact=_date_compact(d),
        rows=rows,
    )

    # Output
    if output_path:
        out_file = Path(output_path)
    else:
        out_name = f"{d.isoformat()}_card.html"
        out_file = PROD_DIR / out_name

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")

    print(f"[HTML] 已生成: {out_file}")
    return out_file


if __name__ == "__main__":
    args = sys.argv[1:]
    md = None
    out = None
    i = 0
    while i < len(args):
        if args[i] == "--date" and i + 1 < len(args):
            from datetime import datetime as _dt
            td = _dt.strptime(args[i+1], "%Y-%m-%d").date().isoformat()
            md = str(PROD_DIR / f"{td}_refined.md")
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            out = args[i + 1]
            i += 2
        elif not args[i].startswith("--"):
            md = args[i]
            i += 1
        else:
            i += 1

    generate_html(md, out)
