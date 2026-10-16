# AI 日报系统

自动采集 AI 行业资讯，经 LLM 评分排序后输出结构化 JSON，通过 FastAPI 接口供前端项目调用，同时提供独立可访问的网站。

## 项目结构

```
ai_news/
├── ai_news_aggregator.py     # 采集 → output/raw_items.json（结构化）+ output/ai_news.md
├── rss_sources.py            # RSS 信源采集（feedparser，配置见 sources_config.json）
├── sources_config.json       # AIHOT 18 个 RSS 信源 + tier 门槛
├── produce_news.py           # 精炼 + 评分 + 热门板块 → output/news.json
├── llm_score.py              # LLM 评分模块（支持 OpenAI 兼容 API，无 key 回退关键词评分）
├── generate_html.py          # 渲染：refined.md → output/card.html
├── server.py                 # API 服务 + 独立网站 (FastAPI + Jinja2 SSR)
├── paths.py                  # 滚动产物路径与旧文件清理
├── prompts/
│   └── score.txt             # 评分提示词（预留）
├── templates/
│   ├── news_cards.html       # 1920×1080 卡片模板
│   └── site/
│       ├── base.html         # 网站基模板（导航 + 主题切换）
│       ├── index.html        # 首页（今日热门 + 板块卡片）
│       ├── hot.html          # 热门排行（按分数分档列表）
│       └── about.html        # 关于页面
├── static/
│   ├── style.css             # 网站样式（亮/暗主题）
│   └── app.js                # 主题切换交互
├── output/                   # 运行时产物（滚动覆盖）
│   └── news.json             #   API 数据源
├── .env.example              # LLM API 配置示例
├── requirements.txt
└── README.md
```

## 数据流

```
ai_news_aggregator.py          produce_news.py           server.py
采集 9+ 来源          →        过滤 + 精炼          →    FastAPI API + 独立网站
                                    ↓
                         llm_score.py 评分
                                    ↓
                         热门板块生成
                                    ↓
                         output/news.json
```

### 评分

每条新闻按"AI 读者注意力价值"打 0-100 分：

- **LLM 模式**（配置 `LLM_API_KEY` 后）：调用 OpenAI 兼容 API 批量评分
- **关键词模式**（未配置 API key 时）：基于关键词命中数启发式评分

评分后按分数排序，提取 Top 6 组成"今日热门"板块。

### 采集来源

| 模块 | 来源 |
|------|------|
| GitHub Trending | github.com/trending（AI 相关过滤） |
| HF Daily Papers | huggingface.co/api/daily_papers |
| HF Models | huggingface.co/api/models（热门模型） |
| arXiv IR | export.arxiv.org/api/query |
| 国际新闻 (T2 RSS) | The Verge, TechCrunch, Ars Technica, MIT Tech Review, The Decoder, Simon Willison, Import AI, Latent Space + HN 搜索 |
| 国内新闻 | 36氪, IT之家 |
| 国际公司 (T1 RSS) | OpenAI, Google DeepMind, Google Research, Hugging Face, Microsoft Research, NVIDIA, AWS ML, GitHub, Mistral, BAIR |
| 国内公司 | DeepSeek, 智谱, 百度, 阿里, 月之暗面... |
| 社区热点 | HackerNews, Lobsters（AI 主题过滤） |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 独立网站首页 |
| GET | `/hot` | 热门排行页 |
| GET | `/about` | 关于页面 |
| GET | `/api/v1/ai_news/news` | 结构化日报 JSON（滚动版） |
| GET | `/api/v1/ai_news/news?date=YYYY-MM-DD` | 按日期校验 |
| GET | `/api/v1/ai_news/hot` | 热门条目 JSON（按评分排序） |
| GET | `/api/v1/ai_news/cards` | HTML 卡片 |
| GET | `/api/v1/ai_news/dates` | `{ dates: [当前日期], latest }` |

### JSON 结构

```json
{
  "date": "2026-08-10",
  "date_formatted": "2026年08月10日",
  "weekday": "星期一",
  "sections": [
    {
      "label": "今日热门",
      "icon": "flame",
      "accent": "hot",
      "items": [
        { "title": "...", "detail": "...", "score": 85, "source_section": "国际 AI 新闻" }
      ]
    },
    {
      "label": "GitHub 热门趋势",
      "icon": "star",
      "accent": "github",
      "items": [
        { "title": "addyosmani/agent-skills", "detail": "Production-grade engineering skills...", "score": 47 }
      ]
    }
  ],
  "meta": {
    "total_items": 46,
    "scored": true,
    "generated_at": "2026-08-10T12:00:00"
  }
}
```

## 配置

复制 `.env.example` 为 `.env` 并填写 LLM API 信息：

```bash
cp .env.example .env
# 编辑 .env，填入你的 API key
```

不配置 `.env` 也能运行，评分会自动回退到关键词启发式模式。

## 本地开发

```bash
cd ai_news

# 安装依赖
pip install -r requirements.txt

# 1. 采集（需要网络）→ output/ai_news.md
python3 ai_news_aggregator.py

# 2. 精炼 + 评分 → output/news.json
python3 produce_news.py

# 3. 启动 API + 网站
python3 server.py
# → http://127.0.0.1:8001
```

前端（zero-to-tech）：

```bash
cd zero-to-tech/nextjs
NEXT_PUBLIC_AI_NEWS_API=http://localhost:8001 npm run dev
# → http://localhost:3000/demos/ai-news
```

## 服务器部署

### 依赖

| 层级 | 依赖 |
|------|------|
| Python | `requirements.txt` |
| LLM（可选） | `.env` 中的 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` |
| 运行时数据 | `output/news.json` |
| 系统 | systemd + nginx 反代 |

```bash
# 1) 数据在
ls output/news.json

# 2) API + 网站在跑
sudo systemctl restart ai-news-api

# 3) nginx 把 /api/v1/ai_news/ 和网站路径转到 8001
curl -s https://你的域名/api/v1/ai_news/news | head
curl -s https://你的域名/  # 独立网站
```

### systemd

```ini
[Unit]
Description=AI Daily News API + Website
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/ai_news
ExecStart=/opt/ai_news/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 定时更新

```bash
# 每天 7:30 采集 + 评分
30 7 * * * cd /opt/ai_news && .venv/bin/python3 ai_news_aggregator.py && .venv/bin/python3 produce_news.py
```

## 向后兼容

`/api/v1/ai_news/news` 端点保持原有 JSON 结构不变。新增的 `score`、`source_section`、`meta` 字段对旧前端透明——前端只读 `title` 和 `detail`，多余字段自动忽略。新增的"今日热门"板块会作为 `sections[0]` 出现，旧前端自动渲染为额外一张卡片。
