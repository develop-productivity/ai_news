#!/usr/bin/env python3
"""
AI News 卡片渲染器 — 精炼版 → HTML 卡片 → 截图
================================================
从 ai_new_product 读取 refined.md，生成精美的 1920×1080 新闻卡片 HTML 和 PNG。

用法:
  python3 render_card.py                        # 今天的精炼版
  python3 render_card.py --date 2026-06-13      # 指定日期
  python3 render_card.py --html-only            # 只生成 HTML，不截图
  python3 render_card.py --no-html              # 只用已有的 HTML 重新截图
  python3 render_card.py --open                 # 生成后用浏览器打开
"""

import os, sys, re, subprocess, glob
from pathlib import Path
from datetime import date

SCRIPT_DIR = Path(__file__).parent
PROD_DIR = SCRIPT_DIR.parent / "ai_new_product" / "processed"
FRAMES_DIR = SCRIPT_DIR / "output" / "frames"


def today():
    return date.today().isoformat()


def find_refined(date_str=None):
    ds = date_str or today()
    path = PROD_DIR / f"{ds}_refined.md"
    if path.exists():
        return path, ds
    # fallback to raw
    raw_dir = SCRIPT_DIR
    path2 = raw_dir / f"{ds}_ai_news.md"
    if path2.exists():
        return path2, ds
    # fallback to latest
    all_f = sorted(glob.glob(str(PROD_DIR / "*_refined.md")), reverse=True)
    if all_f:
        p = Path(all_f[0])
        return p, p.name.split("_")[0]
    return None, None


def phase_html(md_path, date_str):
    """Phase 1: Generate HTML cards from refined markdown"""
    print(f"[Phase 1/2] 精炼版 → HTML 卡片")
    sys.path.insert(0, str(SCRIPT_DIR))
    from generate_html import generate_html

    # generate_html auto-detects or uses md_path; we pass it explicitly
    out_path = str(PROD_DIR / f"{date_str}_card.html")
    result = generate_html(str(md_path), out_path)
    print(f"  ✅ HTML: {result}")
    return result


def check_playwright():
    """Check if Playwright + Chromium is available."""
    pw_path = SCRIPT_DIR / "node_modules" / "playwright"
    if not pw_path.exists():
        return False
    try:
        r = subprocess.run(
            ["node", "-e", "require('playwright'); console.log('ok')"],
            capture_output=True, text=True, timeout=10, cwd=str(SCRIPT_DIR),
        )
        return r.returncode == 0 and r.stdout.strip() == "ok"
    except Exception:
        return False


def phase_screenshot(html_path, date_str):
    """Phase 2: Screenshot HTML to PNG"""
    print(f"[Phase 2/2] HTML → 截图")
    png_path = PROD_DIR / f"{date_str}_card.png"

    if not check_playwright():
        print("  ⚠ Playwright 不可用，跳过截图。")
        print(f"  📄 HTML 已生成: {html_path}")
        print(f"  💡 请在浏览器中打开该文件，手动截图 (1920×1080)")
        return None

    script = SCRIPT_DIR / "screenshot.js"
    try:
        r = subprocess.run(
            ["node", str(script), str(html_path), "--output", str(png_path), "--wait", "3000"],
            capture_output=True, text=True, timeout=60000, cwd=str(SCRIPT_DIR),
        )
        if r.returncode != 0:
            print(f"  ❌ 截图失败:\n{r.stderr}")
            return None
        if png_path.exists() and png_path.stat().st_size > 0:
            print(f"  ✅ PNG: {png_path} ({png_path.stat().st_size/1024:.1f} KB)")
            return png_path
        return None
    except subprocess.TimeoutExpired:
        print("  ❌ 截图超时")
        return None
    except Exception as e:
        print(f"  ❌ 截图异常: {e}")
        return None


def main():
    import argparse
    p = argparse.ArgumentParser(description="AI News 卡片渲染")
    p.add_argument("--date", help="日期 YYYY-MM-DD")
    p.add_argument("--html-only", action="store_true", help="只生成 HTML，不截图")
    p.add_argument("--no-html", action="store_true", help="只用已有 HTML 截图")
    p.add_argument("--open", action="store_true", help="生成后用浏览器打开 HTML")
    args = p.parse_args()

    md_path, date_str = find_refined(args.date)
    if not md_path:
        print("❌ 未找到精炼版文件，请先运行: python3 produce_news.py")
        sys.exit(1)

    print(f"=" * 55)
    print(f"  🃏 AI News 卡片渲染 — {date_str}")
    print(f"=" * 55)
    print(f"  📄 精炼版: {md_path}")

    # Phase 1: HTML
    html_path = None
    if not args.no_html:
        html_path = phase_html(md_path, date_str)
    else:
        html_path_candidate = PROD_DIR / f"{date_str}_card.html"
        if html_path_candidate.exists():
            html_path = html_path_candidate
            print(f"  📄 使用已有 HTML: {html_path}")
        else:
            print("  ❌ --no-html 但未找到已有 HTML")
            sys.exit(1)

    # Phase 2: Screenshot
    if not args.html_only:
        phase_screenshot(html_path, date_str)

    print(f"=" * 55)
    print(f"  ✅ 完成！")
    print(f"  📁 产出:")
    print(f"    HTML: {PROD_DIR / f'{date_str}_card.html'}")
    print(f"    PNG:  {PROD_DIR / f'{date_str}_card.png'}")
    print()
    print(f"  💡 视频剪辑流程:")
    print(f"    1. PNG 作为视频背景图")
    print(f"    2. broadcast.mp3 作为音频轨道")
    print(f"    3. 在剪映/Premiere/达芬奇中合成")
    print(f"=" * 55)

    if args.open and html_path:
        import subprocess as sp
        sp.run(["xdg-open", str(html_path)], timeout=2)


if __name__ == "__main__":
    main()
