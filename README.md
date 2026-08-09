# AI 日报系统

自动采集 AI 行业资讯，经精炼过滤后输出结构化 JSON，通过 FastAPI 接口供前端项目请求展示。

---

## 项目结构

```
ai_news/
├── ai_news_aggregator.py     # 采集：9 来源并行 → 原始日报 Markdown
├── produce_news.py           # 精炼：过滤 + 时效性检查 + 结构化 JSON
├── generate_html.py          # 渲染：精炼版 → HTML 卡片 (Jinja2)
├── server.py                 # API 服务 (FastAPI)
├── templates/
│   └── news_cards.html       # HTML 卡片模板
├── output/                   # 所有产物
│   ├── {date}_ai_news.md     #   原始日报
│   ├── {date}_refined.md     #   精炼版
│   └── {date}_news.json      #   结构化 JSON (API 数据源)
├── requirements.txt
└── README.md
```

---

## 数据流

```
ai_news_aggregator.py     produce_news.py      server.py
采集 9 个来源     →       过滤 + 精炼    →     FastAPI 提供接口
                                    ↓
                              output/{date}_news.json
                                    ↓
                    前端 fetch /api/v1/ai_news/news
```

### 采集来源

| 模块 | 来源 |
|------|------|
| GitHub Trending | github.com/trending |
| HF Daily Papers | huggingface.co/api/daily_papers |
| arXiv IR | export.arxiv.org/api/query |
| 国际新闻 | TechCrunch, Ars Technica, The Verge |
| 国内新闻 | 36氪, IT之家 |
| 国际公司 | HuggingFace Blog, Google Research, Anthropic, OpenAI |
| 国内公司 | DeepSeek, 智谱, 百度, 阿里, 月之暗面... |
| 社区热点 | HackerNews Top, Lobsters |

### 时效性过滤

`produce_news.py` 从条目内容中提取真实日期，与报告日期比对，超过 7 天的条目自动过滤：

- `投稿日期: 2026-06-11` — 精确到日
- URL 路径 `/2026/06/12/` — 精确到日
- 无日期的条目（GitHub Trending 等）默认保留

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/ai_news/news` | 最新日报 JSON（结构化） |
| GET | `/api/v1/ai_news/news?date=2026-06-13` | 指定日期 |
| GET | `/api/v1/ai_news/cards` | 渲染好的 HTML 卡片 |
| GET | `/api/v1/ai_news/dates` | 所有可用日期列表 |

### JSON 结构

```json
{
  "date": "2026-06-13",
  "date_formatted": "2026年06月13日",
  "weekday": "星期六",
  "sections": [
    {
      "label": "GitHub 热门趋势",
      "icon": "star",
      "accent": "github",
      "items": [
        { "title": "addyosmani/agent-skills", "detail": "Production-grade engineering skills..." }
      ]
    }
  ]
}
```

---

## 本地开发

```bash
cd ai_news
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. 采集（可选，需要网络）
python3 ai_news_aggregator.py

# 2. 精炼 + 生成 JSON
python3 produce_news.py

# 3. 启动 API 服务
python3 server.py
# → http://127.0.0.1:8001
```

前端项目（zero-to-tech）默认使用同源请求，本地开发时可通过环境变量指定 API 地址：

```bash
NEXT_PUBLIC_AI_NEWS_API=http://localhost:8001 npx next dev
```

---

## 服务器部署

### 1. 创建虚拟环境

```bash
cd /opt/ai_news          # 或你的部署目录
git clone <repo> .
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 生成初始数据

```bash
python3 ai_news_aggregator.py
python3 produce_news.py
```

### 3. 启动服务（监听本机 8001）

```bash
uvicorn server:app --host 127.0.0.1 --port 8001
```

与 text-lab-api（端口 8000）互不冲突。

### 4. 用 systemd 保持运行

```bash
sudo vim /etc/systemd/system/ai-news-api.service
```

```ini
[Unit]
Description=AI Daily News API
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

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-news-api
sudo systemctl start ai-news-api
sudo systemctl status ai-news-api
```

### 5. Nginx 配置

ai_news 的路径前缀是 `/api/v1/ai_news/`，text-lab-api 是 `/api/v1/analyze`，nginx 按最长前缀自动分流：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # AI 日报 API → 8001
    location /api/v1/ai_news/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Text Lab API → 8000
    location /api/v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # 前端静态文件
    location / {
        root /var/www/zero-to-tech/nextjs/out;
        try_files $uri $uri.html $uri/ =404;
    }
}
```

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 6. 前端配置

zero-to-tech 的 `AiNewsView.jsx` 默认使用同源请求（`API_BASE` 为空字符串），不需要设置环境变量。浏览器请求 `/api/v1/ai_news/news`，nginx 自动转发到 `127.0.0.1:8001`。

---

## 每日更新

```bash
cd /opt/ai_news
source .venv/bin/activate
python3 ai_news_aggregator.py
python3 produce_news.py
```

刷新页面即可看到最新内容，无需重启 API 服务。

未来可用 crontab 自动化：

```bash
# 每天 7:30 采集 + 精炼
30 7 * * * cd /opt/ai_news && .venv/bin/python3 ai_news_aggregator.py && .venv/bin/python3 produce_news.py
```

---

## 故障排查

| 问题 | 解决 |
|------|------|
| `No module named 'fastapi'` | `pip install -r requirements.txt` |
| 采集时部分来源为空 | 网络问题或源站改版，检查 `ai_news_aggregator.py` 输出日志 |
| API 返回 404 | `output/` 中无 `*_news.json`，先运行 `produce_news.py` |
| 前端 Failed to fetch | 确认 `server.py` 在运行，检查 nginx 代理配置 |
| 端口冲突 | 默认 8001，可用 `--port` 指定其他端口 |
