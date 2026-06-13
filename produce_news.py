#!/usr/bin/python3
"""
AI 日报生产者 - 过滤精炼 + 口播稿
====================================
流程: 原始日报 → 精炼版 → 口播稿

用法:
  python3 produce_news.py                           # 今天
  python3 produce_news.py --date 2026-06-13         # 指定日期
  python3 produce_news.py --cat                     # 只看口播稿内容
  python3 produce_news.py --no-script               # 只生成精炼版，不提取口播稿
"""

import os, re, sys, datetime, glob

RAW_DIR = "/mnt/d/wsl_data/ai_new_product/original"
PROD_DIR = "/mnt/d/wsl_data/ai_new_product/processed"

def today(): return datetime.date.today().strftime("%Y-%m-%d")

# ================================================================
# 1. 读取最新加工版 > 原始版
# ================================================================

def find_source(date_str=None):
    ds = date_str or today()
    # 优先读取二次加工版 (final > draft > raw)
    candidates = [
        (os.path.join(PROD_DIR, f"{ds}_ai_news_final.md"), "final"),
        (os.path.join(PROD_DIR, f"{ds}_ai_news_draft.md"), "draft"),
        (os.path.join(RAW_DIR, f"{ds}_ai_news.md"), "raw"),
    ]
    for path, label in candidates:
        if os.path.exists(path):
            return path, label, ds
    # fallback: 最近的文件
    all_md = sorted(glob.glob(os.path.join(RAW_DIR, "*_ai_news.md")), reverse=True)
    if all_md:
        fn = os.path.basename(all_md[0])
        return all_md[0], "raw", fn.split("_")[0]
    return None, None, None


# ================================================================
# 2. 二次加工：过滤 + 精炼
# ================================================================

def refine(raw_text):
    """
    二次加工：去掉不适合口播的内容，保留精华。
    输入：原始日报 Markdown
    输出：(过滤后的精炼版 Markdown, 提取的朗读文本)
    """
    lines = raw_text.split("\n")

    # -- 要删除的整块 --
    removes = []

    # YAML frontmatter (--- ... ---)
    if lines and lines[0].strip() == "---":
        fm_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i
                break
        if fm_end > 0:
            removes.append((0, fm_end + 1))
    # HTML 注释块 (<!-- ... -->)
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
        if l.startswith("## 📌 目录"):
            in_toc = True
            toc_start = i
        if in_toc and l.startswith("---") and i > toc_start:
            removes.append((toc_start, i + 1))
            in_toc = False
            break

    # 页脚（最后一个 --- 之后的内容）
    last_sep = -1
    for i, l in enumerate(lines):
        if l.strip() == "---":
            last_sep = i
    if last_sep > 0:
        removes.append((last_sep, len(lines)))

    # 逐行标记要删除的行
    drop_line = set()
    for rs, re_ in removes:
        for j in range(rs, re_):
            drop_line.add(j)

    # -- 行级过滤 --
    kept_lines = []
    for i, l in enumerate(lines):
        if i in drop_line:
            continue
        stripped = l.strip()

        # 删除纯元数据行
        if stripped.startswith(">") and ("数据来源" in stripped or "自动聚合" in stripped or "生成时间" in stripped):
            continue
        if stripped.startswith("🤖") or stripped.startswith("📅") or stripped.startswith("🌐"):
            continue
        # 空表行
        if re.match(r'^\|[\s\-:]+\|$', stripped):
            continue
        # 所有 | 行（表格数据）删除
        if stripped.startswith("|") and stripped.endswith("|"):
            # 但是保留表格中的文字内容？算了，表不好读，全删
            continue

        kept_lines.append(l)

    # -- 章节级过滤 --
    # 重新组装
    text = "\n".join(kept_lines)

    # 去掉 huggingface 模型排行整节（数字太多不适合口播）
    text = re.sub(
        r'## 🏆 HuggingFace 模型排行榜.*?(?=^## )',
        '',
        text,
        flags=re.DOTALL | re.MULTILINE,
    )

    # 去掉 arXiv 分类列
    text = re.sub(r'\| 分类:.*$', '', text, flags=re.MULTILINE)

    # 去掉社区热点中的纯数字/低信息行
    text = re.sub(r'^\d+\s*$', '', text, flags=re.MULTILINE)

    # 合并多余空行
    text = re.sub(r'\n{4,}', '\n\n', text)
    text = text.strip()

    return text


# ================================================================
# 3. 从精炼版提取口播文本
# ================================================================

def extract_broadcast_script(refined_text):
    """
    从精炼版日报提取适合口播的纯文本。
    保留标题、新闻条目、论文标题、GitHub 项目名、社区讨论。
    """
    lines = refined_text.split("\n")
    parts = []

    # 日期（从标题行 "AI 行业日报 - YYYY-MM-DD (星期X)" 中提取）
    date_line = ""
    for l in lines:
        if "AI 行业日报" in l:
            date_line = l
            break
    ds = today()
    weekday = ""
    if date_line:
        dm = re.search(r'(\d{4}-\d{2}-\d{2})', date_line)
        if dm:
            ds = dm.group(1)
        wm = re.search(r'\((星期[一二三四五六日])\)', date_line)
        if wm:
            weekday = wm.group(1)
    d = ds.replace("-", "年", 1).replace("-", "月", 1) + "日"
    d = re.sub(r'年0', '年', d)
    d = re.sub(r'月0', '月', d)

    parts.append(f"欢迎收听每日 AI 行业日报。今天是{d}，{weekday}。")

    # 按章节提取
    sections_raw = []
    current_sec = []
    current_title = "head"
    for l in lines:
        if l.startswith("## "):
            if current_sec:
                sections_raw.append((current_title, current_sec))
            current_title = l
            current_sec = []
        else:
            current_sec.append(l)
    if current_sec:
        sections_raw.append((current_title, current_sec))

    def clean_item(text):
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        text = re.sub(r'\*(.*?)\*', r'\1', text)
        text = re.sub(r'^###\s*\d*\.?\s*', '', text)
        text = re.sub(r'^\d+\.\s+', '', text)
        text = re.sub(r'^- ', '', text)
        text = re.sub(r'^>\s*', '', text)
        text = re.sub(r'^🔗.*', '', text)
        text = re.sub(r'^👥.*', '', text)
        text = re.sub(r'^👍.*', '', text)
        text = text.strip()
        return text

    # 按类型分组
    news_lines, gh_lines, paper_lines, company_lines, community_lines = [], [], [], [], []
    for title, sec_lines in sections_raw:
        # 公司优先于国际/国内（避免 "国际大模型公司" 被误判为新闻）
        if re.search(r'公司|动态', title):
            company_lines = sec_lines
        elif re.search(r'国际|国内', title):
            news_lines.extend(sec_lines)
        elif re.search(r'GitHub', title):
            gh_lines = sec_lines
        elif re.search(r'论文|模型排行|搜索', title):
            paper_lines = sec_lines
        elif re.search(r'社区|热点', title):
            community_lines = sec_lines

    # -- 1. 要闻 --
    if news_lines:
        parts.append("")
        parts.append("先来看今日要闻。")
        for l in news_lines:
            m = re.match(r'^###\s+\d+\.\s+\[(.+?)\]', l)
            if m:
                t = re.sub(r'\*\*(.*?)\*\*', r'\1', m.group(1))
                parts.append(t)

    # -- 2. GitHub --
    if gh_lines:
        parts.append("")
        parts.append("GitHub 热门趋势。")
        for l in gh_lines:
            cl = clean_item(l)
            if cl and len(cl) > 5 and not cl.startswith('---'):
                cl = re.sub(r'描述:\s*', '', cl)
                cl = re.sub(r'\s*[⭐] Stars:.*$', '', cl)
                cl = re.sub(r'\s*[🔤] 语言:.*$', '', cl)
                cl = cl.strip()
                if cl:
                    parts.append(cl)

    # -- 3. 论文 --
    if paper_lines:
        parts.append("")
        parts.append("今日论文精选。")
        for l in paper_lines:
            cl = clean_item(l)
            if cl and len(cl) > 15 and not l.startswith('-') and not l.startswith('|'):
                parts.append(cl)

    # -- 4. 公司 --
    if company_lines:
        parts.append("")
        parts.append("公司动态方面。")
        for l in company_lines:
            cl = clean_item(l)
            if cl and len(cl) > 10 and cl not in ('Hugging Face Blog', 'Google Research', 'Anthropic', 'OpenAI', 'DeepSeek'):
                parts.append(cl)

    # -- 5. 社区 --
    if community_lines:
        parts.append("")
        parts.append("社区热点方面。")
        for l in community_lines:
            cl = clean_item(l)
            if cl and len(cl) > 10:
                cl = re.sub(r' 🔥\d+', '', cl)
                if cl not in ('HackerNews Top', 'Lobsters'):
                    parts.append(cl)
    parts.append("")
    parts.append("以上是今天的 AI 行业日报。感谢收听，我们明天再见。")

    return "\n".join(parts)


# ================================================================
# 主入口
# ================================================================

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="日期 YYYY-MM-DD")
    p.add_argument("--cat", action="store_true", help="输出口播稿内容到终端")
    p.add_argument("--no-script", action="store_true", help="只生成精炼版，不提取口播稿")
    args = p.parse_args()

    os.makedirs(PROD_DIR, exist_ok=True)

    # 1. 读取源文件
    src_path, src_label, date_str = find_source(args.date)
    if not src_path:
        print("❌ 未找到日报文件")
        return

    with open(src_path, "r", encoding="utf-8") as f:
        raw = f.read()

    print(f"📄 读取: {os.path.basename(src_path)} ({src_label}) — {len(raw):,} chars")

    # 2. 二次加工（过滤）
    print(f"🔍 二次加工: 过滤无用信息...")
    refined = refine(raw)

    refined_path = os.path.join(PROD_DIR, f"{date_str}_refined.md")
    with open(refined_path, "w", encoding="utf-8") as f:
        f.write(refined)
    print(f"   ✅ 精炼版 → {refined_path} ({len(refined):,} chars)")

    if args.no_script:
        print(f"\n{'='*55}")
        print(f"  ✅ 完成！")
        print(f"{'='*55}")
        return

    # 3. 提取口播稿
    print(f"📝 提取口播稿...")
    script = extract_broadcast_script(refined)

    script_path = os.path.join(PROD_DIR, f"{date_str}_script.md")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script + "\n")

    if args.cat:
        print(f"\n{'─'*55}")
        print(script)
        print(f"{'─'*55}")
    else:
        print(f"\n{'='*55}")
        print(f"  🎙 口播稿")
        print(f"{'='*55}")
        print(f"  📁 {script_path}")
        print(f"  📏 {len(script):,} chars")
        print()
        for line in script.split("\n")[:12]:
            print(f"    {line}" if line else "")
        if len(script.split("\n")) > 12:
            print(f"    ... (共 {len(script.split(chr(10)))} 行)")

    print(f"\n{'='*55}")
    print(f"  ✅ 完成！输出: {PROD_DIR}/")
    print(f"  💡 下一步: python3 tts_news.py 生成语音")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
