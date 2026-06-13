#!/usr/bin/python3
"""
TTS Demo - 对比 edge-tts (免费) vs MiniMax Speech 2.6 Turbo (API)
===============================================================
用法:
  python3 tts_demo.py                        # 使用默认文本测试
  python3 tts_demo.py --file 日报文件.md      # 从日报中提取内容
  python3 tts_demo.py --edge-only             # 只测试 edge-tts
  python3 tts_demo.py --minimax-only          # 只测试 MiniMax
"""

import os
import sys
import re
import asyncio
import json
import argparse
import time

MINIMAX_API_KEY = "API_KEY_HERE"  # 替换为你的 MiniMax API Key
OUTPUT_DIR = "/mnt/d/wsl_data/ai_new_product/processed/audio"


# ======== 文本处理 ========

def clean_markdown_for_tts(text):
    """清洗 Markdown，保留纯文本用于朗读"""
    # 移除代码块
    text = re.sub(r'```[\s\S]*?```', '', text)
    # 移除行内代码
    text = re.sub(r'`[^`]+`', '', text)
    # 移除图片
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 链接保留文字
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 移除加粗/斜体标记
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    # 标题符号换成更自然的朗读停顿
    text = re.sub(r'^### +', '📌 ', text, flags=re.MULTILINE)
    text = re.sub(r'^## +', '\n📌 ', text, flags=re.MULTILINE)
    text = re.sub(r'^# +', '\n📢 ', text, flags=re.MULTILINE)
    # 分隔线换成停顿
    text = re.sub(r'^---+\s*$', '\n...\n', text, flags=re.MULTILINE)
    # 列表符号
    text = re.sub(r'^- ', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s*', '', text, flags=re.MULTILINE)
    # 表格行（只保留文字）
    text = re.sub(r'\|.*\|', '', text)
    text = re.sub(r'\|?[-:]+\|?[-:| ]+\|?', '', text)
    # 移除引用
    text = re.sub(r'^> ', '', text, flags=re.MULTILINE)
    # 移除 HTML
    text = re.sub(r'<[^>]+>', '', text)
    # 多余空行合并
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    return text


def get_sample_text():
    """获取一段测试文本"""
    text = """
欢迎收听每日 AI 行业日报。

今天是2026年6月13日，星期六。

首先来看今天的热点新闻。

Anthropic 的 Fable 5 和 Mythos 5 模型被美国政府下达紧急出口管制指令，
被迫全球暂停服务。Anthropic 公开表示反对这一决定，
称其基于一次窄范围的越狱测试就召回商业模型是不合理的。

在开源模型方面，月之暗面开源了 Kimi K2.7 Code 编程模型，
并预告六倍速高速版将于下周一发布。

智谱 AI 宣布 GLM 5.2 模型将面向 Coding Plan 用户开放，
并计划下周正式开源。

Hugging Face 今日热门模型榜首是 Google 的 Diffusion Gemma 26B，
该模型在图像生成领域表现突出。

以上就是今天的 AI 日报摘要，感谢收听。
"""
    return text.strip()


def extract_intro_from_report(md_path):
    """从日报中提取开头部分作为测试样本"""
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 提取标题和顶部简介
        lines = content.split('\n')
        intro = []
        for line in lines[:50]:
            if line.startswith('# ') or line.startswith('## 📌'):
                intro.append(line)
            elif line.startswith('## 🔥'):
                break
            elif line.strip():
                intro.append(line)

        return '\n'.join(intro)
    except Exception:
        return get_sample_text()


# ======== edge-tts 模块（免费） ========

async def test_edge_tts(text, filename="edge_tts_demo.mp3", voice="zh-CN-XiaoxiaoNeural"):
    """测试 edge-tts"""
    print(f"\n{'='*50}")
    print(f"🎤 测试: edge-tts (完全免费)")
    print(f"{'='*50}")

    try:
        import edge_tts
    except ImportError:
        print("  ❌ 需要安装: pip install edge-tts")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, filename)

    t1 = time.time()
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        elapsed = time.time() - t1
        duration_sec = os.path.getsize(output_path) / 16000  # rough estimate

        print(f"  ✅ 生成成功!")
        print(f"  📁 {output_path}")
        print(f"  📏 {os.path.getsize(output_path):,} bytes")
        print(f"  ⏱  耗时: {elapsed:.1f}s")
        print(f"  🎙 声音: {voice}")
        print(f"  📝 文本长度: {len(text)} 字符")
        return output_path
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return None


# ======== MiniMax TTS 模块 ========

def test_minimax_tts(text, filename="minimax_demo.mp3"):
    """测试 MiniMax Speech 2.6 Turbo"""
    print(f"\n{'='*50}")
    print(f"🎤 测试: MiniMax Speech 2.6 Turbo")
    print(f"{'='*50}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, filename)

    try:
        from openai import OpenAI
    except ImportError:
        print("  ❌ 需要安装: pip install openai")
        # Try alternative with direct REST
        return test_minimax_rest(text, output_path)

    t1 = time.time()
    try:
        client = OpenAI(
            api_key=MINIMAX_API_KEY,
            base_url="https://api.minimax.chat/v1",
        )

        response = client.audio.speech.create(
            model="speech-2.6-turbo",
            input=text,
            voice="female-zh-001",
            speed=1.0,
            response_format="mp3",
        )

        response.stream_to_file(output_path)
        elapsed = time.time() - t1

        print(f"  ✅ 生成成功!")
        print(f"  📁 {output_path}")
        print(f"  📏 {os.path.getsize(output_path):,} bytes")
        print(f"  ⏱  耗时: {elapsed:.1f}s")
        print(f"  🎙 声音: female-zh-001")
        print(f"  📝 文本长度: {len(text)} 字符")
        print(f"  💰 API 费用: ~${len(text)/1_000_000 * 60:.4f}")
        return output_path

    except Exception as e:
        print(f"  ❌ OpenAI SDK 失败: {e}")
        print(f"  尝试使用 direct REST API...")
        return test_minimax_rest(text, output_path)


def test_minimax_rest(text, output_path):
    """MiniMax TTS via direct REST API (fallback)"""
    t1 = time.time()
    try:
        import requests
        import base64

        resp = requests.post(
            "https://api.minimaxi.com/v1/t2a_v2",
            headers={
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "speech-2.6-turbo",
                "text": text,
                "stream": False,
                "voice_setting": {
                    "voice_id": "female-zh-001",
                    "speed": 1.0,
                    "vol": 1.0,
                    "pitch": 0,
                },
                "audio_setting": {
                    "sample_rate": 32000,
                    "format": "mp3",
                    "channel": 1,
                },
            },
            timeout=60,
        )

        if resp.status_code == 200:
            result = resp.json()

            if "data" in result and "audio" in result["data"]:
                audio_hex = result["data"]["audio"]
                audio_bytes = bytes.fromhex(audio_hex)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                elapsed = time.time() - t1
                print(f"  ✅ 生成成功! (REST API)")
                print(f"  📁 {output_path}")
                print(f"  📏 {len(audio_bytes):,} bytes")
                print(f"  ⏱  耗时: {elapsed:.1f}s")
                return output_path
            else:
                print(f"  ❌ 响应异常: {result}")
        else:
            print(f"  ❌ HTTP {resp.status_code}: {resp.text[:200]}")

    except Exception as e:
        print(f"  ❌ REST API 也失败: {e}")

    # 如果是认证失败，给出明确的提示
    print(f"  💡 提示: 如果认证失败，请确认 API Key 格式是否正确")
    print(f"     MiniMax API Key 通常以 'sk-' 开头")
    return None


# ======== 测试多种声音 ========

async def test_edge_tts_voices(text):
    """测试多种 edge-tts 中文声音"""
    print(f"\n{'='*50}")
    print(f"🎤 对比: edge-tts 多种中文声音")
    print(f"{'='*50}")

    voices = [
        ("zh-CN-XiaoxiaoNeural", "👩 晓晓 - 温暖女声（推荐）"),
        ("zh-CN-YunyangNeural", "👨 云扬 - 新闻男声（推荐）"),
        ("zh-CN-YunxiNeural", "🧑 云希 - 活力少年"),
        ("zh-CN-XiaohanNeural", "👩 晓涵 - 抒情女声"),
        ("zh-CN-XiaomoNeural", "👩 晓墨 - 情感丰富"),
    ]

    results = []
    for voice_id, label in voices:
        short_text = text[:300]
        filename = f"edge_tts_{voice_id.split('-')[2].lower()}.mp3"
        print(f"\n  {label}:")
        try:
            import edge_tts
            communicate = edge_tts.Communicate(short_text, voice_id)
            path = os.path.join(OUTPUT_DIR, filename)
            await communicate.save(path)
            print(f"    ✅ {os.path.getsize(path):,} bytes → {filename}")
            results.append((label, path))
        except Exception as e:
            print(f"    ❌ {e}")

    return results


# ======== 主入口 ========

async def main():
    parser = argparse.ArgumentParser(description="TTS Demo - edge-tts vs MiniMax")
    parser.add_argument("--file", help="从指定日报文件提取文本")
    parser.add_argument("--edge-only", action="store_true", help="只测试 edge-tts")
    parser.add_argument("--minimax-only", action="store_true", help="只测试 MiniMax")
    parser.add_argument("--compare-voices", action="store_true", help="对比 edge-tts 多种声音")
    parser.add_argument("--quick", action="store_true", help="快速测试（使用短文本）")
    args = parser.parse_args()

    print(f"{'='*55}")
    print(f"  🎧 TTS Demo - 文本转语音测试")
    print(f"{'='*55}\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 获取测试文本
    if args.file and os.path.exists(args.file):
        with open(args.file, 'r', encoding='utf-8') as f:
            raw_text = f.read()
        text = clean_markdown_for_tts(raw_text)
        source_desc = os.path.basename(args.file)
    else:
        md_path = "/mnt/d/wsl_data/ai_news/2026-06-13_ai_news.md"
        if os.path.exists(md_path):
            raw_text = extract_intro_from_report(md_path)
            text = clean_markdown_for_tts(raw_text)
            source_desc = "今日日报"
        else:
            text = get_sample_text()
            source_desc = "测试文本"

    if args.quick:
        text = text[:500]  # 截取前500字快速测试

    print(f"📝 测试文本来源: {source_desc}")
    print(f"📏 清理后文本长度: {len(text)} 字符")
    print(f"\n📋 预览 (前200字):")
    print(f"   {text[:200]}...\n")

    # edge-tts 测试
    edge_result = None
    if not args.minimax_only:
        edge_result = await test_edge_tts(text)

    # 对比多种声音
    if args.compare_voices:
        await test_edge_tts_voices(text)

    # MiniMax 测试
    minimax_result = None
    if not args.edge_only:
        minimax_result = test_minimax_tts(text)

    # 结果对比
    print(f"\n{'='*55}")
    print(f"  📊 结果对比")
    print(f"{'='*55}")
    print(f"  edge-tts:       {'✅ ' + edge_result if edge_result else '❌ 未测试'}")
    print(f"  MiniMax 2.6:    {'✅ ' + minimax_result if minimax_result else '❌ 未测试'}")
    print(f"\n  所有文件输出到: {OUTPUT_DIR}/")
    print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
