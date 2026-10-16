#!/usr/bin/python3
"""
AI 日报生产者 — 过滤精炼 + LLM 评分 + 结构化 JSON 输出
=========================================================
流程: 原始日报 → 过滤精炼 → LLM/关键词评分 → 热门板块 → 结构化 JSON

用法:
  python3 produce_news.py                 # 读取 output/ai_news.md，滚动覆盖输出
  python3 produce_news.py --date 2026-08-10  # 用指定日期写入 JSON 元数据
  python3 produce_news.py --no-score       # 跳过评分步骤
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
    lines = raw_text.split("\n")
    removes = []

    if lines and lines[0].strip() == "---":
        fm_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i
                break
        if fm_end > 0:
            removes.append((0, fm_end + 1))

    for i, l in enumerate(lines):
        if l.strip().startswith("<!--"):
            comment_end = -1
            for j in range(i, len(lines)):
                if lines[j].strip().endswith("-->"):
                    comment_end = j
                    break
            if comment_end > 0:
                removes.append((i, comment_end + 1))

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

    kept_lines = []
    for i, l in enumerate(lines):
        if i in drop_line:
            continue
        stripped = l.strip()
        if stripped.startswith(">") and any(kw in stripped for kw in
            ["数据来源", "自动聚合", "生成时间"]):
            continue
        if any(stripped.startswith(c) for c in ["\U0001f916", "\U0001f4c5", "\U0001f310"]):
            continue
        if re.match(r'^\|[\s\-:]+\|$', stripped):
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            continue
        kept_lines.append(l)

    text = "\n".join(kept_lines)

    text = re.sub(
        r'## [^\n]*模型排行[^\n]*\n.*?(?=^## )',
        '',
        text,
        flags=re.DOTALL | re.MULTILINE,
    )

    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip() + "\n"
    return text


# ================================================================
# 3. 结构化 JSON 输出
# ================================================================

_STALE_PATTERNS = [
    re.compile(r"据[悉传称]"),
    re.compile(r"传[闻言]"),
    re.compile(r"reportedly", re.IGNORECASE),
]

MAX_AGE_DAYS = 7

_OFFTOPIC_PATTERNS = [
    re.compile(r"游戏|手游|网游|电竞|游戏联动"),
    re.compile(r"米哈游|无畏契约|原神|王者荣耀|和平精英"),
    re.compile(r"\bgaming\b|\bvideogame\b|\besport", re.IGNORECASE),
    re.compile(r"酒店订单|opens in a new window|IT早报"),
    re.compile(r"^\s*官网\s*$"),
]


def _extract_item_date(text):
    m = re.search(r"(?:投稿日期|发布日期)[^0-9]*(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return datetime.date.fromisoformat(m.group(1))
        except ValueError:
            pass
    m = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", text)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"(?:IT)?早报\s*(\d{2})(\d{2})", text)
    if m and hasattr(_extract_item_date, "_report_year"):
        try:
            return datetime.date(
                _extract_item_date._report_year, int(m.group(1)), int(m.group(2))
            )
        except ValueError:
            pass
    return None


def _is_stale(text, report_date_str=None):
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
    return any(p.search(text) for p in _STALE_PATTERNS)


_AI_TOPIC_RE = re.compile(
    r"(?<![a-z0-9])(?:ai|aigc|llm|gpt|glm|rag|mlx|nlp|cv)(?![a-z0-9])|"
    r"claude|gemini|openai|anthropic|deepseek|qwen|kimi|mistral|llama|agent|"
    r"大模型|人工智能|机器学习|深度学习|智能体|生成式|"
    r"huggingface|pytorch|transformer|copilot|vllm|ollama|"
    r"多模态|蒸馏|对齐|强化学习|neural|diffusion",
    re.IGNORECASE,
)


def _is_offtopic(text):
    if any(p.search(text) for p in _OFFTOPIC_PATTERNS):
        return True
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    plain = re.sub(r"^###\s*\d+\.\s*", "", plain).strip()
    if len(plain) > 90 and ("我是" in plain[:30] or plain.startswith("[")):
        return True
    return False


def _is_ai_topic(text):
    return bool(_AI_TOPIC_RE.search(text or ""))


def refined_to_json(refined_text, date_str):
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

        require_ai = cfg.get("accent") in {"oss", "github"}

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

        if not entries:
            entries = [[l.strip()] for l in sec_lines[1:] if l.strip()]

        def clean_md(text):
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            text = re.sub(r"\*(.+?)\*", r"\1", text)
            text = re.sub(r"`(.+?)`", r"\1", text)
            text = re.sub(r"^\d+\.\s*", "", text)
            text = re.sub(r"^[-•]\s*", "", text)
            text = re.sub(r"^[\U0001f300-\U0001f9ff\u2600-\u26ff\u2700-\u27bf]+\s*", "", text)
            text = re.sub(r"^(?:英文摘要|描述|摘要|内容|详情)[:：]\s*", "", text)
            text = re.sub(r"\s*🔥\d+", "", text)
            return text.strip()

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
# 4. 评分 + 热门板块
# ================================================================

def apply_scoring(data):
    """对 JSON 数据中的条目评分、写作，生成"今日热门"板块。"""
    try:
        from llm_score import score_sections, build_hot_section
    except ImportError as e:
        print(f"  [评分] 跳过（无法导入 llm_score: {e}）")
        return data

    sections = data.get("sections", [])
    print("\n📊 评分阶段...")
    sections = score_sections(sections)

    # LLM 写作：为高分条目生成中文标题/摘要
    try:
        from llm_write import write_sections
        print("\n✍️ 写作阶段...")
        sections = write_sections(sections)
    except ImportError as e:
        print(f"  [写作] 跳过（无法导入 llm_write: {e}）")

    # 去重/聚类：跨板块合并同一事件
    try:
        from dedup import dedup_sections
        print("\n🔗 去重/聚类...")
        sections, events = dedup_sections(sections)
        if events:
            data["events"] = events
    except ImportError as e:
        print(f"  [去重] 跳过（无法导入 dedup: {e}）")

    hot = build_hot_section(sections, top_n=6)
    if hot:
        sections.insert(0, hot)
        print(f"  [热门] 生成 {len(hot['items'])} 条热门条目")

    data["sections"] = sections
    data["meta"] = {
        "total_items": sum(len(s.get("items", [])) for s in sections),
        "scored": True,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # 保存历史快照
    try:
        from history import save_snapshot
        save_snapshot(data)
    except Exception as e:
        print(f"  [历史] 保存失败: {e}")

    return data


# ================================================================
# 主入口
# ================================================================

def main():
    import argparse
    p = argparse.ArgumentParser(description="AI 日报精炼 → Markdown + JSON + 评分")
    p.add_argument("--date", help="覆盖写入 JSON 的日期 YYYY-MM-DD")
    p.add_argument("--no-score", action="store_true", help="跳过评分步骤")
    p.add_argument("--rescore", action="store_true", help="从现有 news.json 重新评分（不需要 raw markdown）")
    args = p.parse_args()

    ensure_output_dir()

    # --rescore: 从现有 news.json 重新评分
    if args.rescore:
        if not NEWS_JSON_PATH.exists():
            print("❌ 未找到 news.json，无法重新评分")
            return
        print("🔄 重新评分模式：从现有 news.json 评分")
        with open(NEWS_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # 去掉旧的 hot 板块和 meta
        data["sections"] = [s for s in data.get("sections", []) if s.get("accent") != "hot"]
        data.pop("meta", None)
        data = apply_scoring(data)
        with open(NEWS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"   ✅ news.json 已更新 ({len(data['sections'])} 个板块)")
        return

    src_path, date_str = find_source(args.date)
    if not src_path:
        print("❌ 未找到日报文件，请先运行: python3 ai_news_aggregator.py")
        return

    if args.date:
        date_str = args.date

    with open(src_path, "r", encoding="utf-8") as f:
        raw = f.read()

    print(f"📄 读取: {os.path.basename(src_path)} — {len(raw):,} chars")

    print("🔍 精炼中...")
    refined = refine(raw)

    REFINED_MD_PATH.write_text(refined, encoding="utf-8")
    print(f"   ✅ refined.md → {REFINED_MD_PATH} ({len(refined):,} chars)")

    print("📊 生成 JSON...")
    data = refined_to_json(refined, date_str)

    if not args.no_score:
        data = apply_scoring(data)

    with open(NEWS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"   ✅ news.json → {NEWS_JSON_PATH} ({len(data['sections'])} 个板块)")

    removed = cleanup_dated_artifacts()
    if removed:
        print(f"   🧹 已清理旧日期产物: {len(removed)} 个")

    print(f"\n{'='*55}")
    print(f"  📅 {date_str} · 滚动单份产物")
    for sec in data["sections"]:
        print(f"  {sec['icon']} {sec['label']}: {len(sec['items'])} 条")
    print(f"{'='*55}")
    print(f"  💡 下一步: python3 server.py 启动网站")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
