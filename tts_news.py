#!/usr/bin/python3
"""
AI 新闻 TTS 生成器 - 口播稿 → 语音
=====================================
从 ai_new_product 读取口播稿，生成语音。

流程:  produce_news.py → script.md → tts_news.py → broadcast.mp3

用法:
  python3 tts_news.py                             # 今天的口播稿
  python3 tts_news.py --date 2026-06-13           # 指定日期
  python3 tts_news.py --engine minimax            # 用 MiniMax API
  python3 tts_news.py --voice zh-CN-YunyangNeural # 男声
  python3 tts_news.py --play                      # 生成后播放
  python3 tts_news.py --list-voices               # 列出可用声音
"""

import asyncio, os, sys, re, time, subprocess, argparse, glob, datetime

PROD_DIR = "/mnt/d/wsl_data/ai_new_product/processed"


# ================================================================
# 查找口播稿
# ================================================================

def find_script(date_str=None):
    ds = date_str or datetime.date.today().strftime("%Y-%m-%d")
    path = os.path.join(PROD_DIR, f"{ds}_script.md")
    if os.path.exists(path):
        return path, ds
    # fallback: 最近的口播稿
    all_scripts = sorted(glob.glob(os.path.join(PROD_DIR, "*_script.md")), reverse=True)
    if all_scripts:
        fn = os.path.basename(all_scripts[0])
        return all_scripts[0], fn.split("_")[0]
    return None, None


# ================================================================
# edge-tts 引擎
# ================================================================

async def edge_tts_generate(text, output_path, voice="zh-CN-XiaoxiaoNeural"):
    import edge_tts
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    t1 = time.time()
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
    elapsed = time.time() - t1
    size = os.path.getsize(output_path)
    return {"path": output_path, "size": size, "elapsed": round(elapsed, 1), "duration": round(size / 16000, 0)}


async def edge_tts_list_voices():
    import edge_tts
    voices = await edge_tts.list_voices()
    cn = [v for v in voices if "CN" in v.get("Locale", "")]
    print(f"\n{'='*55}")
    print(f"  edge-tts 中文声音 ({len(cn)} 个)")
    print(f"{'='*55}")
    for v in cn:
        name = v["ShortName"]
        gender = v.get("Gender", "—")
        local = v.get("LocalName", name)
        print(f"  {name}  ({gender} · {local})")
    print(f"\n  推荐: zh-CN-XiaoxiaoNeural (晓晓·女声)")
    print(f"          zh-CN-YunyangNeural (云扬·男声)")
    print(f"          zh-CN-YunxiNeural   (云希·青年)")
    print(f"{'='*55}")


# ================================================================
# MiniMax 引擎
# ================================================================

async def minimax_generate(text, output_path, voice="English_expressive_narrator"):
    import websockets, json, ssl
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        return {"error": "请设置环境变量: export MINIMAX_API_KEY=你的key"}

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    if len(text) > 8000:
        chunks = [text[i:i+8000] for i in range(0, len(text), 8000)]
    else:
        chunks = [text]

    t1 = time.time()
    audio_all = b""
    for ci, chunk in enumerate(chunks):
        ws = await websockets.connect(
            "wss://api.minimax.io/ws/v1/t2a_v2",
            additional_headers={"Authorization": f"Bearer {api_key}"},
            ssl=ssl_ctx, ping_interval=None, max_size=10_000_000,
        )
        await ws.recv()
        await ws.send(json.dumps({
            "event": "task_start", "model": "speech-2.6-turbo",
            "voice_setting": {"voice_id": voice, "speed": 1, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        }))
        msg = json.loads(await ws.recv())
        if msg.get("event") != "task_started":
            await ws.close()
            return {"error": f"chunk {ci+1}: {msg.get('base_resp',{}).get('status_msg','unknown')}"}
        await ws.send(json.dumps({"event": "task_continue", "text": chunk}))
        while True:
            msg = json.loads(await ws.recv())
            if "data" in msg and "audio" in msg["data"]:
                audio_all += bytes.fromhex(msg["data"]["audio"])
            if msg.get("is_final"):
                break
            if msg.get("event") == "task_failed":
                await ws.close()
                return {"error": f"chunk {ci+1}: {msg.get('base_resp',{}).get('status_msg','failed')}"}
        await ws.close()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(audio_all)
    elapsed = time.time() - t1
    return {"path": output_path, "size": len(audio_all), "elapsed": round(elapsed, 1), "duration": round(len(audio_all) / 16000, 0)}


# ================================================================
# 主入口
# ================================================================

async def main():
    p = argparse.ArgumentParser(description="口播稿 → 语音")
    p.add_argument("--date", help="日期 YYYY-MM-DD")
    p.add_argument("--engine", choices=["edge", "minimax"], default="edge",
                   help="TTS 引擎 (默认 edge-tts, 免费)")
    p.add_argument("--voice", default="zh-CN-XiaoxiaoNeural",
                   help="声音 ID (edge: Xiaoxiao | minimax: English_expressive_narrator)")
    p.add_argument("--play", action="store_true", help="生成后播放")
    p.add_argument("--list-voices", action="store_true", help="列出 edge-tts 中文声音")
    p.add_argument("--output", help="输出文件名 (不含路径)")
    args = p.parse_args()

    # 列出声音
    if args.list_voices:
        await edge_tts_list_voices()
        return

    # 查找口播稿
    script_path, date_str = find_script(args.date)
    if not script_path:
        print(f"❌ 未找到口播稿，请先运行: python3 produce_news.py")
        return

    with open(script_path, "r", encoding="utf-8") as f:
        text = f.read()

    # 输出
    out_name = args.output or f"{date_str}_broadcast"
    out_path = os.path.join(PROD_DIR, f"{out_name}.mp3")

    print(f"{'='*55}")
    print(f"  🎧 TTS 语音生成")
    print(f"{'='*55}")
    print(f"  📄 口播稿: {os.path.basename(script_path)}")
    print(f"  📏 文本: {len(text):,} chars")
    print(f"  🎙 引擎: {args.engine}")
    print(f"  🎤 声音: {args.voice}")
    print(f"  📁 输出: {out_path}")
    print()
    print(f"  💬 预览: {text[:80].strip()}...")
    print()

    # 生成
    t1 = time.time()
    if args.engine == "edge":
        result = await edge_tts_generate(text, out_path, args.voice)
    else:
        result = await minimax_generate(text, out_path, args.voice)
    elapsed = time.time() - t1

    if "error" in result:
        print(f"  ❌ 失败: {result['error']}")
        return

    # 输出结果
    print(f"  ✅ 生成成功！")
    print(f"  📁 {result['path']}")
    print(f"  📏 {result['size']:,} bytes")
    print(f"  ⏱ 时长: ~{result['duration']}s")
    print(f"  ⏱ 生成: {result['elapsed']}s")

    if args.play:
        try:
            subprocess.run(["xdg-open", out_path], timeout=2)
            print(f"  ▶ 已打开播放器")
        except:
            pass

    print(f"{'='*55}")
    print(f"  💡 播放: xdg-open {out_path}")
    print()
    print(f"  💡 如果您觉得内容需要调整:")
    print(f"     1. 编辑 {os.path.basename(script_path)}")
    print(f"     2. 重新运行: python3 tts_news.py --date {date_str}")
    print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
