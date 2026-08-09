#!/usr/bin/python3
"""
AI 日报生产者 — 过滤精炼 + JSON 输出
======================================
流程: 原始日报 → 精炼版 Markdown → 结构化 JSON

用法:
  python3 produce_news.py                           # 今天
  python3 produce_news.py --date 2026-06-13         # 指定日期
"""

import os, re, sys, json, datetime, glob
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output"


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


# ================================================================
# 1. 读取源文件
# ================================================================

def find_source(date_str=None):
    ds = date_str or today_str()

    # 先在 output/ 里找
    out_path = OUTPUT_DIR / f"{ds}_ai_news.md"
    if out_path.exists():
        return str(out_path), ds

    # 也在项目根目录找（兼容之前存的）
    local_path = SCRIPT_DIR / f"{ds}_ai_news.md"
    if local_path.exists():
        return str(local_path), ds

    # fallback: 最近的文件
    candidates = sorted(
        glob.glob(str(OUTPUT_DIR / "*_ai_news.md")) +
        glob.glob(str(SCRIPT_DIR / "*_ai_news.md")),
        reverse=True
    )
    if candidates:
        fn = os.path.basename(candidates[0])
        return candidates[0], fn.split("_")[0]

    return None, None


# ================================================================
# 2. 过滤 + 精炼
# ================================================================

def refine(raw_text):
    """去掉不适合展示的内容，保留精华。"""
    lines = raw_text.split("\n")

    # 要删除的整块
    removes = []

    # YAML frontmatter
    if lines and lines[0].strip() == "---":
        fm_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i
                break
        if fm_end > 0:
            removes.append((0, fm_end + 1))

    # HTML 注释块
    for i, l in enumerate(lines):
        if l.strip().startswith("<!--"):
            comment_end = -1
            for j in range(i, len(lines)):
                if lines[j].strip().endswith("-->"):
                    comment_end = j
                    break
            if comment_end > 0:
                removes.append((i, comment_end + 1))

    # 目录区
    in_toc = False
    toc_start = -1
    for i, l in enumerate(lines):
        if l.startswith("## ") and "目录" in l:
            in_toc = True
            toc_start = i
        if in_toc and l.startswith("---") and i > toc_start:
            removes.append((toc_start, i + 1))
            in_toc = False
            break

    # 页脚
    last_sep = -1
    for i, l in enumerate(lines):
        if l.strip() == "---":
            last_sep = i
    if last_sep > 0:
        after = "\n".join(lines[last_sep:]).strip()
        if len(after) < 200:
            removes.append((last_sep, len(lines)))

    drop_line = set()
    for rs, re_ in removes:
        for j in range(rs, re_):
            drop_line.add(j)

    # 行级过滤
    kept_lines = []
    for i, l in enumerate(lines):
        if i in drop_line:
            continue
        stripped = l.strip()

        # 元数据行
        if stripped.startswith(">") and any(kw in stripped for kw in
            ["数据来源", "自动聚合", "生成时间"]):
            continue
        if any(stripped.startswith(c) for c in ["\U0001f916", "\U0001f4c5", "\U0001f310"]):
            continue
        # 空表格
        if re.match(r'^\|[\s\-:]+\|$', stripped):
            continue
        # 表格数据
        if stripped.startswith("|") and stripped.endswith("|"):
            continue

        kept_lines.append(l)

    text = "\n".join(kept_lines)

    # 去掉 HuggingFace 模型排行榜
    text = re.sub(
        r'## [^\n]*模型排行[^\n]*\n.*?(?=^## )',
        '',
        text,
        flags=re.DOTALL | re.MULTILINE,
    )

    # 合并多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip() + "\n"
    return text


# ================================================================
# 3. 结构化 JSON 输出
# ================================================================



# ── 时效性过滤 ──
# 关键词模式：仅对无法提取真实日期的条目生效
_STALE_PATTERNS = [
    re.compile(r"据[悉传称]"),
    re.compile(r"传[闻言]"),
    re.compile(r"reportedly", re.IGNORECASE),
]

MAX_AGE_DAYS = 7


def _extract_item_date(text):
    """从条目文本中提取日期，返回 datetime.date 或 None。"""
    # 1. 投稿日期: 2026-06-11
    m = re.search(r"(?:投稿日期|发布日期)[^0-9]*(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return datetime.date.fromisoformat(m.group(1))
        except ValueError:
            pass

    # 2. URL 中的日期 /2026/06/12/
    m = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", text)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # 注意: 不从 arXiv ID (如 2606.XXXXX) 提取日期，
    # 因为只有月份精度，会导致同月论文被误判为过期。
    # 没有精确日期的条目默认保留。

    return None


def _is_stale(text, report_date_str=None):
    """检查条目是否时效性不足。优先用真实日期，无日期时回退到关键词。"""
    # 尝试提取真实日期
    if report_date_str:
        try:
            report_date = datetime.date.fromisoformat(report_date_str)
            item_date = _extract_item_date(text)
            if item_date:
                age = (report_date - item_date).days
                return age > MAX_AGE_DAYS
        except ValueError:
            pass

    # 无日期 → 关键词兜底
    return any(p.search(text) for p in _STALE_PATTERNS)

def refined_to_json(refined_text, date_str):
    """从精炼版 Markdown 解析为结构化 JSON。"""
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    try:
        d = datetime.date.fromisoformat(date_str)
        weekday = weekdays[d.weekday()]
        date_formatted = f"{d.year}年{d.month:02d}月{d.day:02d}日"
    except ValueError:
        weekday = ""
        date_formatted = date_str

    lines = refined_text.split("\n")

    section_map = [
        ("github", {"label": "GitHub 热门趋势", "icon": "star", "accent": "github"}),
        ("hugging", {"label": "HF 论文精选", "icon": "diamond", "accent": "paper"}),
        ("论文", {"label": "今日论文精选", "icon": "diamond", "accent": "paper"}),
        ("arxiv", {"label": "arXiv 论文", "icon": "diamond", "accent": "paper"}),
        ("搜索", {"label": "搜索 & 推荐论文", "icon": "diamond", "accent": "paper"}),
        ("国际大模型公司", {"label": "国际公司动态", "icon": "building", "accent": "company"}),
        ("国内大模型公司", {"label": "国内公司动态", "icon": "building", "accent": "company"}),
        ("公司动态", {"label": "公司动态", "icon": "building", "accent": "company"}),
        ("国内 AI", {"label": "国内 AI 新闻", "icon": "globe", "accent": "news"}),
        ("国际 AI", {"label": "国际 AI 新闻", "icon": "globe", "accent": "news"}),
        ("社区", {"label": "社区热点", "icon": "message-circle", "accent": "oss"}),
    ]

    def match_section(header):
        for key, cfg in section_map:
            if key.lower() in header.lower():
                return dict(cfg)
        return None

    raw_sections = re.split(r"\n## ", "\n" + refined_text)
    sections = []

    for sec in raw_sections:
        sec_lines = sec.strip().split("\n")
        if not sec_lines or not sec_lines[0].strip():
            continue
        header = sec_lines[0].strip().lstrip("#").strip()

        cfg = match_section(header)
        if not cfg:
            continue

        # 按 ### 分组为条目，整条做日期检查
        entries = []
        current = []
        for line in sec_lines[1:]:
            line = line.strip()
            if not line:
                continue
            if line.startswith("### "):
                if current:
                    entries.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            entries.append(current)

        # 无 ### 结构时，每行独立
        if not entries:
            entries = [[l.strip()] for l in sec_lines[1:] if l.strip()]

        # ── 文本清理 ──
        def clean_md(text):
            """剥离 Markdown 格式，返回纯文本。"""
            # [title](url) → title
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
            # **bold** → plain
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            # *italic* → plain
            text = re.sub(r"\*(.+?)\*", r"\1", text)
            # `code` → plain
            text = re.sub(r"`(.+?)`", r"\1", text)
            # 去掉编号前缀
            text = re.sub(r"^\d+\.\s*", "", text)
            # 去掉 bullet 前缀
            text = re.sub(r"^[-•]\s*", "", text)
            # 去掉 emoji 前缀标记
            text = re.sub(r"^[\U0001f300-\U0001f9ff\u2600-\u26ff\u2700-\u27bf]+\s*", "", text)
            # 去掉字段标签 (英文摘要: / 描述: / 摘要: / 内容:)
            text = re.sub(r"^(?:英文摘要|描述|摘要|内容|详情)[:：]\s*", "", text)
            # 去掉 🔥 热度标记
            text = re.sub(r"\s*🔥\d+", "", text)
            return text.strip()

        # 低价值元数据行，不展示
        META_KEYS = {"链接", "来源", "作者", "投稿日期", "发布日期", "Stars", "语言", "点赞"}
        def is_meta(text):
            clean = clean_md(text)
            return any(k.lower() in clean.lower() for k in META_KEYS)

        items = []
        for entry in entries:
            entry_text = "\n".join(entry)
            if _is_stale(entry_text, date_str):
                continue

            first_line = entry[0]
            sub = re.match(r"^###\s+(.+)$", first_line)
            if sub:
                sub_text = sub.group(1).strip()
                # ### 1. [title](url) → 编号条目（论文/新闻/GitHub）
                if re.match(r"^\d+\.", sub_text):
                    title = clean_md(sub_text)
                    detail = ""
                    for line in entry[1:]:
                        if is_meta(line):
                            continue
                        clean = clean_md(line)
                        if len(clean) > 15:
                            detail = clean[:200]
                            break
                    if title:
                        items.append({"title": title[:120], "detail": detail})
                else:
                    # ### 分类标题（如 OpenAI、HackerNews Top）
                    # 下方每个链接/编号都是一个独立条目
                    cat = clean_md(sub_text)
                    for line in entry[1:]:
                        if is_meta(line):
                            continue
                        clean = clean_md(line)
                        clean = re.sub(r"^(?:-|•|\d+\.)\s+", "", clean)
                        if len(clean) > 5:
                            full_title = f"{cat} · {clean}" if cat else clean
                            items.append({"title": full_title[:120], "detail": ""})
            else:
                # 无 ### 结构，用第一行做 title
                for line in entry:
                    if is_meta(line):
                        continue
                    clean = clean_md(line)
                    if len(clean) > 5:
                        items.append({"title": clean[:120], "detail": ""})
                        break

        if items:
            cfg["items"] = items[:6]
            sections.append(cfg)

    return {
        "date": date_str,
        "date_formatted": date_formatted,
        "weekday": weekday,
        "sections": sections,
    }


# ================================================================
# 主入口
# ================================================================

def main():
    import argparse
    p = argparse.ArgumentParser(description="AI 日报精炼 → Markdown + JSON")
    p.add_argument("--date", help="日期 YYYY-MM-DD")
    args = p.parse_args()

    os.makedirs(str(OUTPUT_DIR), exist_ok=True)

    # 1. 读取源文件
    src_path, date_str = find_source(args.date)
    if not src_path:
        print("❌ 未找到日报文件，请先运行: python3 ai_news_aggregator.py")
        return

    with open(src_path, "r", encoding="utf-8") as f:
        raw = f.read()

    print(f"📄 读取: {os.path.basename(src_path)} — {len(raw):,} chars")

    # 2. 精炼
    print("🔍 精炼中...")
    refined = refine(raw)

    refined_path = OUTPUT_DIR / f"{date_str}_refined.md"
    refined_path.write_text(refined, encoding="utf-8")
    print(f"   ✅ refined.md → {refined_path} ({len(refined):,} chars)")

    # 3. JSON 输出
    print("📊 生成 JSON...")
    data = refined_to_json(refined, date_str)

    json_path = OUTPUT_DIR / f"{date_str}_news.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"   ✅ news.json → {json_path} ({len(data['sections'])} 个板块)")

    # 4. 输出概要
    print(f"\n{'='*55}")
    for sec in data["sections"]:
        print(f"  {sec['icon']} {sec['label']}: {len(sec['items'])} 条")
    print(f"{'='*55}")
    print(f"  💡 下一步: python3 generate_html.py 生成卡片 HTML")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
