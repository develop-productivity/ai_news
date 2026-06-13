#!/usr/bin/python3
"""
AI News 二次加工助手
====================
将原始日报复制到 /mnt/d/wsl_data/ai_new_product/ 目录，
并生成一个可编辑的加工版本。

使用方法:
  python3 refine_news.py                    # 加工今天的日报
  python3 refine_news.py --date 2026-06-13   # 加工指定日期的日报
  python3 refine_news.py --edit              # 加工后自动打开编辑器
  python3 refine_news.py --date 2026-06-13 --edit

输出:
  /mnt/d/wsl_data/ai_new_product/{yyyy-mm-dd}_ai_news_draft.md  (原始副本，供编辑)
  /mnt/d/wsl_data/ai_new_product/{yyyy-mm-dd}_ai_news_final.md  (最终发布版)
"""

import os
import sys
import shutil
import datetime
import re

RAW_DIR = "/mnt/d/wsl_data/ai_new_product/original"
PROD_DIR = "/mnt/d/wsl_data/ai_new_product/processed"


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def find_latest_raw(date_str=None):
    """查找最新的原始日报文件"""
    if date_str:
        fname = os.path.join(RAW_DIR, f"{date_str}_ai_news.md")
        if os.path.exists(fname):
            return fname, date_str
        return None, date_str

    # Find the most recent
    today = today_str()
    fname = os.path.join(RAW_DIR, f"{today}_ai_news.md")
    if os.path.exists(fname):
        return fname, today

    # Check yesterday
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    fname = os.path.join(RAW_DIR, f"{yesterday}_ai_news.md")
    if os.path.exists(fname):
        return fname, yesterday

    return None, None


def copy_to_production(raw_path, date_str):
    """复制原始日报到生产目录"""
    os.makedirs(PROD_DIR, exist_ok=True)

    # Draft copy (editable)
    draft_path = os.path.join(PROD_DIR, f"{date_str}_ai_news_draft.md")
    shutil.copy2(raw_path, draft_path)
    print(f"  📄 草稿: {draft_path}")

    return draft_path


def create_final_template(draft_path, date_str):
    """创建最终发布版模板"""
    final_path = os.path.join(PROD_DIR, f"{date_str}_ai_news_final.md")

    with open(draft_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add editorial header
    editorial_header = f"""---
layout: daily-report
title: AI 行业日报 - {date_str}
date: {date_str}
status: draft
editor: []
reviewed: false
---

<!--
========================================
  AI 行业日报 - 编辑工作区
========================================
  已完成内容: ✅
  需要审核: 🔍
  待补充: 📝
  待删除: ❌

  编辑说明:
  - 请在此版本上进行删改、补充、润色
  - 确认无误后将 status 改为 published
  - 完成后可移除外框注释
========================================
-->

"""

    # Insert after the first heading
    if content.startswith("# "):
        first_newline = content.index("\n")
        content = editorial_header + content[first_newline+1:]
    else:
        content = editorial_header + "\n" + content

    with open(final_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  📝 终极版模板: {final_path}")
    return final_path


def print_summary(raw_path):
    """打印原始报告概要"""
    with open(raw_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Count sections
    sections = re.findall(r'^## (.+)$', content, re.MULTILINE)
    item_count = len(re.findall(r'^### \d+\.', content, re.MULTILINE))
    lines = content.count("\n")

    print(f"\n📊 报告概览:")
    print(f"  • 章节: {len(sections)} 个")
    for s in sections:
        print(f"    - {s}")
    print(f"  • 条目: ~{item_count} 条")
    print(f"  • 行数: {lines} 行")
    print(f"  • 大小: {os.path.getsize(raw_path):,} bytes")


def main():
    # Parse args
    date_str = None
    open_editor = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--date" and i + 1 < len(args):
            date_str = args[i + 1]
            i += 2
        elif args[i] == "--edit":
            open_editor = True
            i += 1
        else:
            print(f"未知参数: {args[i]}")
            print("用法: python3 refine_news.py [--date YYYY-MM-DD] [--edit]")
            sys.exit(1)

    # Find raw file
    raw_path, actual_date = find_latest_raw(date_str)
    if not raw_path:
        print(f"❌ 未找到{'指定日期' if date_str else '最近'}的原始日报")
        print(f"   请先运行 ai_news_aggregator.py")
        sys.exit(1)

    print(f"{'='*55}")
    print(f"  AI News 二次加工助手")
    print(f"{'='*55}")
    print(f"\n📂 原始文件: {raw_path}")

    # Copy to production
    draft_path = copy_to_production(raw_path, actual_date)

    # Create final template
    final_path = create_final_template(draft_path, actual_date)

    # Summary
    print_summary(raw_path)

    print(f"\n{'='*55}")
    print(f"  ✅ 二次加工就绪!")
    print(f"\n  编辑建议:")
    print(f"  1. 编辑草稿: {os.path.basename(draft_path)}")
    print(f"  2. 删改润色后保存到: {os.path.basename(final_path)}")
    print(f"  3. 修改 status 为 published 后即可发布")
    print(f"{'='*55}")

    # Open editor if requested
    if open_editor:
        editor = os.environ.get("EDITOR", "vim")
        print(f"\n  打开编辑器: {editor} {final_path}")
        os.system(f'{editor} "{final_path}"')


if __name__ == "__main__":
    main()
