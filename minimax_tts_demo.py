#!/usr/bin/python3
"""
MiniMax Speech 2.6/2.8 TTS Demo (WebSocket)
=============================================
用法:
  python3 minimax_tts_demo.py                           # 默认文本
  python3 minimax_tts_demo.py "你的文本"                 # 自定义文本
  python3 minimax_tts_demo.py --file 日报.md             # 从日报读取
  python3 minimax_tts_demo.py --voice female-zh-001      # 指定声音
  python3 minimax_tts_demo.py --model speech-2.6-turbo   # 指定模型

环境变量:
  export MINIMAX_API_KEY="你的key"
"""

import asyncio
import websockets
import json
import ssl
import os
import sys
import re
import time
import subprocess

# ========== 配置 ==========
VOICES = {
    "female-zh-001": "中文女声",
    "male-zh-001": "中文男声",
    "female-en-001": "英文女声",
    "male-en-001": "英文男声",
    "English_expressive_narrator": "英文叙述者",
}
OUTPUT_DIR = "/mnt/d/wsl_data/ai_new_product/processed/audio"


def clean_text(text):
    """清洗文本，去掉 Markdown 标记"""
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\|.*\|', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


async def tts_save(api_key, text, output_path,
                   voice_id="female-zh-001",
                   model="speech-2.6-turbo",
                   speed=1.0):
    """
    MiniMax WebSocket TTS - 直接保存音频文件
    """
    if len(text) > 9000:
        text = text[:9000]

    url = "wss://api.minimax.io/ws/v1/t2a_v2"
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    ws = None
    try:
        ws = await websockets.connect(
            url,
            additional_headers={"Authorization": f"Bearer {api_key}"},
            ssl=ssl_context,
            ping_interval=None,
            max_size=10_000_000,
        )

        # 1. 等待连接成功
        msg = json.loads(await ws.recv())
        assert msg.get("event") == "connected_success", f"连接失败: {msg}"

        # 2. 启动任务
        await ws.send(json.dumps({
            "event": "task_start",
            "model": model,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": speed,
                "vol": 1.0,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }))
        msg = json.loads(await ws.recv())
        assert msg.get("event") == "task_started", f"启动失败: {msg}"

        # 3. 发送文本
        await ws.send(json.dumps({
            "event": "task_continue",
            "text": text,
        }))

        # 4. 收集音频
        audio_data = b""
        chunk_count = 0

        while True:
            msg = json.loads(await ws.recv())

            if "data" in msg and "audio" in msg["data"]:
                audio_hex = msg["data"]["audio"]
                if audio_hex:
                    audio_data += bytes.fromhex(audio_hex)
                    chunk_count += 1

            if msg.get("is_final"):
                break

        # 5. 保存文件
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_data)

        # 预估时长 (MP3 32000bps mono: 约 0.064s/KB 的近似)
        est_duration = len(audio_data) / 16000 if len(audio_data) > 0 else 0

        return True, {
            "path": output_path,
            "size": len(audio_data),
            "chunks": chunk_count,
            "duration_sec": round(est_duration, 1),
        }

    except Exception as e:
        return False, str(e)
    finally:
        if ws:
            try:
                await ws.send(json.dumps({"event": "task_finish"}))
                await ws.close()
            except Exception:
                pass


async def main():
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        print("❌ 请设置: export MINIMAX_API_KEY='你的key'")
        sys.exit(1)

    voice_id = "female-zh-001"
    model = "speech-2.6-turbo"
    speed = 1.0
    text = ""
    output_name = "minimax_tts_demo"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--voice" and i + 1 < len(args):
            voice_id = args[i + 1]
            i += 2
        elif args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif args[i] == "--speed" and i + 1 < len(args):
            speed = float(args[i + 1])
            i += 2
        elif args[i] == "--file" and i + 1 < len(args):
            fp = args[i + 1]
            with open(fp, "r", encoding="utf-8") as f:
                raw = f.read()
            text = clean_text(raw)
            output_name = os.path.splitext(os.path.basename(fp))[0]
            i += 2
        elif args[i] == "--save" and i + 1 < len(args):
            output_name = args[i + 1]
            i += 2
        else:
            text = " ".join(args[i:])
            break

    if not text:
        text = """你好！欢迎收听每日 AI 行业日报。今天是2026年6月13日，星期六。

首先来看今天的重磅新闻。Anthropic 的 Fable 5 和 Mythos 5 模型被美国政府下达紧急出口管制指令，被迫全球暂停服务。Anthropic 公开表示反对这一决定。

在开源模型方面，月之暗面开源了 Kimi K2.7 Code 编程模型，并预告六倍速高速版将于下周一发布。智谱 AI 宣布 GLM 5.2 模型将面向 Coding Plan 用户开放，并计划下周正式开源。

以上就是今天的 AI 日报摘要，感谢收听。
"""

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    model_short = model.replace("speech-", "").replace("-turbo", "").replace("-hd", "")
    output_path = os.path.join(OUTPUT_DIR, f"{output_name}_{voice_id}_{model_short}.mp3")

    voice_label = VOICES.get(voice_id, voice_id)
    print(f"{'='*55}")
    print(f"  MiniMax Speech TTS")
    print(f"{'='*55}")
    print(f"  🎙 声音: {voice_label} ({voice_id})")
    print(f"  📦 模型: {model}")
    print(f"  🏃 语速: {speed}x")
    print(f"  📝 文本: {len(text)} 字符")
    print(f"  💬 {text[:100]}...")
    print(f"  📁 输出: {output_path}")
    print()

    t1 = time.time()
    ok, result = await tts_save(api_key, text, output_path, voice_id, model, speed)
    elapsed = time.time() - t1

    if ok:
        print(f"  ✅ 生成成功!")
        print(f"  📁 {result['path']}")
        print(f"  📏 {result['size']:,} bytes")
        print(f"  🧩 {result['chunks']} 个音频块")
        print(f"  ⏱ 生成: {elapsed:.1f}s")
        print(f"  ⏱ 时长: ~{result['duration_sec']}s")
        cost = len(text) / 1_000_000 * 60
        print(f"  💰 费用: ${cost:.6f}")
        print()
        print(f"  ▶ 播放: python3 -c \"import subprocess; subprocess.run(['xdg-open','{result['path']}'])\"")
    else:
        print(f"  ❌ 失败: {result}")

    print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
