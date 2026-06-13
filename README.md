# 🤖 AI 日报系统

每天自动采集 AI 行业信息，经精炼过滤后产出**口播稿、语音、视频卡片**。
模块化设计、**每步解耦**，支持逐步扩展为全自动管线。

---

## 📦 包结构

```
ai_news/                          # ── 工作目录 ──
│
├── ai_news_aggregator.py         # 采集：9 模块并行 → 原始日报
├── produce_news.py               # 精炼：过滤无用信息 + 提取口播稿
├── tts_news.py                   # 语音：口播稿 → MP3（edge-tts / MiniMax）
├── render_card.py                # 卡片：精炼版 → HTML → 截图（管线编排）
├── generate_html.py              # HTML：精炼版 → 1920×1080 卡片（Jinja2）
├── screenshot.js                 # 截图：HTML → PNG（Playwright）
│
├── refine_news.py                # [辅助] 二次加工编辑
├── tts_demo.py                   # [demo] edge-tts vs MiniMax 对比
├── minimax_tts_demo.py           # [demo] MiniMax WebSocket 流式 TTS
│
├── templates/
│   └── news_cards.html           # 橘鸦Juya风格 1920×1080 卡片模板
│
├── output/frames/                # 截图临时缓存
├── .env                          # HF/MiniMax 密钥
├── package.json                  # Node.js 依赖（Playwright）
└── README.md

ai_new_product/                   # ── 最终产出目录 ──
│
├── original/                     # 原始数据（ai_news_aggregator.py 输出）
│   ├── {date}_ai_news.md         # 完整日报（26KB，9 个模块）
│   └── .env                      # API 密钥
│
└── processed/                    # 加工产物
    ├── {date}_refined.md         # 精炼版（过滤后 ~24KB）
    ├── {date}_script.md          # 口播稿（~4KB，可编辑）
    ├── {date}_broadcast.mp3      # 口播语音（~2.6MB / ~3min）
    ├── {date}_card.html          # 1920×1080 新闻卡片
    ├── {date}_card.png           # 卡片截图（280KB，1920×1080）
    ├── {date}_ai_news_draft.md   # 二次加工草稿
    ├── {date}_ai_news_final.md   # 二次加工终版
    └── audio/                    # TTS 缓存
```

---

## 🔌 架构设计原则

### 核心思想：管线解耦

每一步的**输出是文件**，下一步的**输入是文件**。没有运行时耦合。

```
原始日报 (Markdown)
    │  produce_news.py  ← 纯文本处理，无外部依赖
    ▼
精炼版 + 口播稿 (Markdown)
    │
    ├──▶ tts_news.py    ← 可换 TTS 引擎
    │     │
    │     └── broadcast.mp3
    │
    └──▶ generate_html.py + screenshot.js  ← 可换截图工具
          │
          └── card.html + card.png
                   │
                   ▼
          视频编辑器 (卡点合成)
```

**好处**：
- 每一步可以独立调试、替换、升级
- 可以随时停在任何环节，查看/编辑中间产物
- 新增功能只需增加一个新的处理模块，不改已有代码

---

## 🚀 当前工作流

### 前置准备

```bash
# ── TTS 语音 ──
pip install edge-tts

# ── HTML 卡片 + 截图 ──
pip install jinja2
cd /mnt/d/wsl_data/ai_news
npm install

# ── MiniMax 语音（可选） ──
export MINIMAX_API_KEY="你的key"
```

### 步骤

```bash
# 1️⃣ 采集（crontab 每天 7:30 自动执行）
python3 ai_news_aggregator.py

# 2️⃣ 精炼 + 口播稿
python3 produce_news.py

# 3️⃣ 语音合成
python3 tts_news.py                          # edge-tts（免费）
python3 tts_news.py --engine minimax         # MiniMax（需充值）
python3 tts_news.py --voice zh-CN-YunyangNeural  # 男声

# 4️⃣ 卡片截图
python3 render_card.py                       # 全自动：精炼版 → HTML → PNG
python3 render_card.py --html-only           # 只生成 HTML
python3 render_card.py --open                # 浏览器预览

# 5️⃣ 视频剪辑
# 把 ai_new_product/{date}_card.png + {date}_broadcast.mp3
# 拖入剪映 / Premiere / 达芬奇 合成视频
```

---

## ⚙️ 模块详解

### `ai_news_aggregator.py` — 采集

9 个模块并行抓取：

| # | 模块 | 数据源 |
|---|------|--------|
| 1 | GitHub Trending | github.com/trending |
| 2 | HF Daily Papers | huggingface.co/api/daily_papers |
| 3 | HF 模型排行榜 | huggingface.co/api/models |
| 4 | arXiv IR（搜索/广告/推荐） | export.arxiv.org/api/query |
| 5 | 国际 AI 新闻 | TechCrunch, HackerNews, Ars Technica, The Verge |
| 6 | 国内 AI 新闻 | 36氪, IT之家 |
| 7 | 国际公司动态 | HuggingFace Blog, Google Research, Anthropic |
| 8 | 国内公司动态 | DeepSeek, 智谱, 百度, 阿里, 月之暗面... |
| 9 | 社区热点 | HackerNews Top, Lobsters |

输出：`ai_news/{yyyy-mm-dd}_ai_news.md`

### `produce_news.py` — 精炼

过滤规则：
- 删除 YAML frontmatter、HTML 注释块
- 删除目录区、页脚
- 删除 `>` 元数据行（数据来源、生成时间）
- 删除表格（不适于朗读）
- 删除 HuggingFace 模型排行榜整节（数字过多）
- 从精炼版提取口播稿（章节排序、清理标记）

```
用法:  python3 produce_news.py [options]

  --date YYYY-MM-DD    指定日期
  --cat                 输出口播稿内容到终端
  --no-script           只生成精炼版，不提取口播稿
```

输出：
- `ai_new_product/{date}_refined.md` — 精炼版
- `ai_new_product/{date}_script.md` — 口播稿（可编辑）

### `tts_news.py` — 语音

支持两种 TTS 引擎：

| 引擎 | 费用 | 中文质量 | 配置 |
|------|------|---------|------|
| **edge-tts** | ✅ 完全免费 | ⭐⭐⭐⭐⭐ 微软神经TTS | 无需配置 |
| **MiniMax** | 💰 $60/百万字 | ⭐⭐⭐⭐⭐ 情感丰富 | `MINIMAX_API_KEY` |

```
用法:  python3 tts_news.py [options]

  --date YYYY-MM-DD       指定日期
  --engine {edge,minimax} TTS 引擎（默认 edge）
  --voice VOICE_ID         声音 ID
  --play                   生成后播放
  --list-voices            列出 edge-tts 中文声音
  --output NAME            输出文件名（不含路径）
```

推荐声音：

| 声音 ID | 描述 |
|---------|------|
| `zh-CN-XiaoxiaoNeural` | 晓晓 — 温暖女声 |
| `zh-CN-YunyangNeural` | 云扬 — 沉稳男声 |
| `zh-CN-YunxiNeural` | 云希 — 活力青年 |

输出：`ai_new_product/{date}_broadcast.mp3`

### `render_card.py` — 卡片渲染管线

```
用法:  python3 render_card.py [options]

  --date YYYY-MM-DD   指定日期
  --html-only          只生成 HTML 不截图
  --no-html            只用已有 HTML 重新截图
  --open               浏览器预览
```

### `generate_html.py` — HTML 卡片

从精炼版自动匹配章节，生成 1920×1080 深色科技风卡片布局。

> 🎯 **未来目标**：卡片风格改为 **juya-daily 风格**（待定具体设计参数）

自动匹配规则：

| 章节标题含 | 卡片标题 | 主题色 |
|-----------|---------|--------|
| `github` | GitHub Trending | 🟢 绿色 |
| `hugging` / `论文精选` | HF Daily Papers / 今日论文精选 | 🟡 金色 |
| `arxiv` / `搜索` | ArXiv Papers / Search & Rec Papers | 🟡 金色 |
| `国际大模型公司` | 国际公司动态 | 🔵 青色 |
| `国内大模型公司` | 国内公司动态 | 🔵 青色 |
| `国际 AI 行业` | AI News | 🟠 橙色 |
| `国内 AI 行业` | 国内 AI 新闻 | 🟠 橙色 |
| `社区` | 社区热点 | 🟣 紫色 |

```
用法:  python3 generate_html.py [--date YYYY-MM-DD]
       python3 generate_html.py path/to/file.md [--output out.html]
```

输出：`ai_new_product/{date}_card.html`

### `screenshot.js` — 卡片截图

Playwright 截图引擎：
- 自动检测 Chromium（优先 snap 版 → Playwright 缓存 → 系统路径）
- viewport：1920×1080
- `waitUntil: 'domcontentloaded'` 避免 Google Fonts 被墙卡住
- 等待 3s 确保动画和字体 fallback 完成

输出：`ai_new_product/{date}_card.png`（1920×1080 PNG）

---

## 🔮 未来扩展设计

系统架构预留了清晰的扩展点，以下是规划中的新功能及实现思路：

### Phase A：自动化音频（MiniMax API）

```
当前:  tts_news.py --engine edge                # 免费，已可用
未来:  tts_news.py --engine minimax             # 更高品质，需充值
       tts_news.py --voice clone                # 声音克隆
       tts_news.py --emotion happy/sad/calm     # 情感控制
```

**扩展方式**：`tts_news.py` 已内置 `edge` 和 `minimax` 双引擎，新增引擎只需在 `generate_tts()` 中添加一个 `elif` 分支。

### Phase B：自动化视频合成

```
当前:  手动在剪映中合成 (PNG + MP3 → MP4)
未来:  python3 compose_video.py                  # 全自动合成
       python3 compose_video.py --subtitle        # 自动字幕
       python3 compose_video.py --ken-burns       # 画面缩放动效
       python3 compose_video.py --transition      # 转场效果
```

**扩展方式**：新增 `compose_video.py`，用 `ffmpeg` 或 `moviepy` 实现：

```
ffmpeg -loop 1 -i card.png -i broadcast.mp3 \
  -c:v libx264 -t 180 -pix_fmt yuv420p output.mp4
```

不需要修改任何现有模块。

### Phase C：口播稿 AI 润色

```
当前:  produce_news.py 提取原始标题
未来:  python3 polish_script.py --ai              # LLM 润色口播稿
       python3 polish_script.py --style news       # 新闻风格
       python3 polish_script.py --style casual     # 轻松风格
```

**扩展方式**：新增 `polish_script.py`，读取 `_script.md`，输出润色后的 `_script.md`，`tts_news.py` 无需改动。

### Phase D：发布自动化

```
未来:  python3 publish.py --platform bilibili     # B站发布
       python3 publish.py --platform youtube       # YouTube 发布
       python3 publish.py --platform weixin        # 公众号发布
```

### 架构演进图

```
当前                                                 未来
─────                                               ─────
ai_news_aggregator.py     →  (不变)
produce_news.py           →  (不变)
                          ┆
tts_news.py               →  + minimax 引擎（情感控制、声音克隆）
                          ┆
render_card.py            →  (不变)
                          ┆
（手动剪辑）                →  compose_video.py  ← 新增模块
                          ┆                          + 字幕
                          ┆                          + 转场
                          ┆                          + 片头片尾
                          ┆
（口播稿纯提取）            →  polish_script.py  ← 新增模块
                          ┆    + AI 润色
                          ┆    + 多风格
                          ┆
                          →  publish.py  ← 新增模块
                               + 多平台发布
```

**核心原则**：所有新功能都是**新增文件**，不修改已有模块。每个模块的输入输出都是**文件接口**，可以独立替换和升级。

---

## 🐛 故障排查

| 问题 | 解决 |
|------|------|
| `No module named 'jinja2'` | `pip install jinja2` |
| `No module named 'edge_tts'` | `pip install edge-tts` |
| `No module named 'websockets'` | `pip install websockets` |
| `No module named 'openai'` | `pip install openai` |
| 截图时黑屏 | 确保 Chromium 可用: `npm run playwright install chromium` |
| 截图时 Google Fonts 卡死 | 已设置 `waitUntil: 'domcontentloaded'` 跳过字体加载 |
| 中文新闻乱码 | Python 解析时使用 `.content` + `from_encoding="utf-8"` |
| MiniMax `insufficient balance` | 账户余额不足，需要充值 |
| MiniMax `voice id not exist` | 声音 ID 不可用，尝试 `English_expressive_narrator` |
| `SSL: UNEXPECTED_EOF_WHILE_READING` | 代理问题，设置 `http_proxy="" https_proxy=""` 绕过 |

---

## 📊 数据流总览

```
每天 7:30 (crontab)
    │
    ▼
┌─────────────────────────────┐
│ ai_news_aggregator.py       │  9 模块并行采集
│ 9 modules → 1 markdown      │  输出: {date}_ai_news.md (26KB)
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ produce_news.py             │  纯文本处理，无外部依赖
│ refine → extract script     │  输出: _refined.md + _script.md
└──────────┬──────────────────┘
           │
     ┌─────┴─────┐
     │           │
     ▼           ▼
┌─────────┐ ┌──────────────┐
│tts_news │ │render_card   │
│.py      │ │.py           │
│         │ │              │
│ edge-   │ │ generate_    │
│ tts /   │ │ html.py      │
│ minimax │ │   +          │
│         │ │ screenshot.js│
└────┬────┘ └──────┬───────┘
     │             │
     ▼             ▼
 broadcast.mp3   card.png
 (2.6MB)        (561KB 1920×1080)
     │             │
     └──────┬──────┘
            ▼
      ┌──────────┐
      │ 视频编辑器 │  (当前手动)
      │ 剪映/PR   │
      │ 达芬奇    │
      └──────────┘
            │
            ▼
         video.mp4

────────── 未来扩展 ──────────

            ▼
      ┌──────────┐
      │ compose_ │  (全自动合成)
      │ video.py │  ffmpeg
      └──────────┘
            │
            ▼
      ┌──────────┐
      │ publish  │  (自动发布)
      │ .py      │  B站/YouTube
      └──────────┘
```
