#!/usr/bin/python3
"""
AI 日报生产者 — 过滤精炼 + JSON 输出
======================================
流程: 原始日报 → 精炼版 Markdown → 结构化 JSON

用法:
  python3 produce_news.py                 # 读取 output/ai_news.md，滚动覆盖输出
  python3 produce_news.py --date 2026-08-10  # 用指定日期写入 JSON 元数据
"""

import os, re, sys, json, datetime, glob
from pathlib import Path

from paths import (
    SCRIPT_DIR,
    OUTPUT_DIR,
    RAW_MD_PATH,
    REFINED_MD_PATH,
    NEWS_JSON_PATH,
    ensure_output_dir,
    cleanup_dated_artifacts,
)


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def _date_from_raw(text, fallback=None):
    m = re.search(r"AI 行业日报\s*[-—]\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    return fallback or today_str()


# ================================================================
# 1. 读取源文件
# ================================================================

def find_source(date_str=None):
    """优先读滚动文件 output/ai_news.md；兼容旧的日期文件名。"""
    if RAW_MD_PATH.exists():
        text = RAW_MD_PATH.read_text(encoding="utf-8")
        return str(RAW_MD_PATH), _date_from_raw(text, date_str)

    ds = date_str or today_str()
    out_path = OUTPUT_DIR / f"{ds}_ai_news.md"
    if out_path.exists():
        return str(out_path), ds

    local_path = SCRIPT_DIR / f"{ds}_ai_news.md"
    if local_path.exists():
        return str(local_path), ds

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

# ── 主题过滤：游戏 / 明显非 AI 噪声 ──
_OFFTOPIC_PATTERNS = [
    re.compile(r"游戏|手游|网游|电竞|游戏联动"),
    re.compile(r"米哈游|无畏契约|原神|王者荣耀|和平精英"),
    re.compile(r"\bgaming\b|\bvideogame\b|\besport", re.IGNORECASE),
    re.compile(r"酒店订单|opens in a new window|IT早报"),
    re.compile(r"^\s*官网\s*$"),
]


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

    # 3. 中文早报日期：IT早报 0808 / 早报0808（用报告年份推断）
    m = re.search(r"(?:IT)?早报\s*(\d{2})(\d{2})", text)
    if m and hasattr(_extract_item_date, "_report_year"):
        try:
            return datetime.date(
                _extract_item_date._report_year, int(m.group(1)), int(m.group(2))
            )
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
            _extract_item_date._report_year = report_date.year
            item_date = _extract_item_date(text)
            if item_date:
                age = (report_date - item_date).days
                return age > MAX_AGE_DAYS
        except ValueError:
            pass

    # 无日期 → 关键词兜底
    return any(p.search(text) for p in _STALE_PATTERNS)


# 短英文词加词边界，避免 Tail/email 误命中 ai
_AI_TOPIC_RE = re.compile(
    r"(?<![a-z0-9])(?:ai|aigc|llm|gpt|glm|rag|mlx|nlp|cv)(?![a-z0-9])|"
    r"claude|gemini|openai|anthropic|deepseek|qwen|kimi|mistral|llama|agent|"
    r"大模型|人工智能|机器学习|深度学习|智能体|生成式|"
    r"huggingface|pytorch|transformer|copilot|vllm|ollama|"
    r"多模态|蒸馏|对齐|强化学习|neural|diffusion",
    re.IGNORECASE,
)


def _is_offtopic(text):
    """游戏相关或明显非 AI 展示噪声。"""
    if any(p.search(text) for p in _OFFTOPIC_PATTERNS):
        return True
    # 论坛灌水/长独白（少数派等偶发混入）
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    plain = re.sub(r"^###\s*\d+\.\s*", "", plain).strip()
    if len(plain) > 90 and ("我是" in plain[:30] or plain.startswith("[")):
        return True
    return False


def _is_ai_topic(text):
    return bool(_AI_TOPIC_RE.search(text or ""))

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

        # 社区 / GitHub 板块强制 AI 主题（源站首页易混入无关内容）
        require_ai = cfg.get("accent") in {"oss", "github"}

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
                    if _is_offtopic(entry_text):
                        continue
                    if require_ai and not _is_ai_topic(entry_text):
                        continue
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
                    # 下方每个链接/编号都是一个独立条目（按行过滤）
                    cat = clean_md(sub_text)
                    for line in entry[1:]:
                        if is_meta(line):
                            continue
                        if _is_offtopic(line):
                            continue
                        if require_ai and not _is_ai_topic(line):
                            continue
                        clean = clean_md(line)
                        clean = re.sub(r"^(?:-|•|\d+\.)\s+", "", clean)
                        if len(clean) > 5:
                            full_title = f"{cat} · {clean}" if cat else clean
                            items.append({"title": full_title[:120], "detail": ""})
            else:
                # 无 ### 结构，用第一行做 title
                if _is_offtopic(entry_text):
                    continue
                if require_ai and not _is_ai_topic(entry_text):
                    continue
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
    p.add_argument("--date", help="覆盖写入 JSON 的日期 YYYY-MM-DD（默认从原文提取）")
    args = p.parse_args()

    ensure_output_dir()

    # 1. 读取源文件
    src_path, date_str = find_source(args.date)
    if not src_path:
        print("❌ 未找到日报文件，请先运行: python3 ai_news_aggregator.py")
        return

    if args.date:
        date_str = args.date

    with open(src_path, "r", encoding="utf-8") as f:
        raw = f.read()

    print(f"📄 读取: {os.path.basename(src_path)} — {len(raw):,} chars")

    # 2. 精炼（滚动覆盖）
    print("🔍 精炼中...")
    refined = refine(raw)

    REFINED_MD_PATH.write_text(refined, encoding="utf-8")
    print(f"   ✅ refined.md → {REFINED_MD_PATH} ({len(refined):,} chars)")

    # 3. JSON 输出（滚动覆盖）
    print("📊 生成 JSON...")
    data = refined_to_json(refined, date_str)

    with open(NEWS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"   ✅ news.json → {NEWS_JSON_PATH} ({len(data['sections'])} 个板块)")

    removed = cleanup_dated_artifacts()
    if removed:
        print(f"   🧹 已清理旧日期产物: {len(removed)} 个")

    # 4. 输出概要
    print(f"\n{'='*55}")
    print(f"  📅 {date_str} · 滚动单份产物")
    for sec in data["sections"]:
        print(f"  {sec['icon']} {sec['label']}: {len(sec['items'])} 条")
    print(f"{'='*55}")
    print(f"  💡 下一步: python3 generate_html.py 生成卡片 HTML")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
