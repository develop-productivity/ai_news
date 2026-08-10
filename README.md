# AI 日报系统

自动采集 AI 行业资讯，经精炼过滤后输出结构化 JSON，通过 FastAPI 接口供前端项目请求展示。

产物采用**滚动单份**：每次运行覆盖同一组文件，不按日期堆积，节省磁盘。

---

## 项目结构

```
ai_news/
├── ai_news_aggregator.py     # 采集：9 来源 → output/ai_news.md
├── produce_news.py           # 精炼：过滤 + 时效性 + output/news.json
├── generate_html.py          # 渲染：refined.md → output/card.html
├── server.py                 # API 服务 (FastAPI)
├── paths.py                  # 滚动产物路径与旧文件清理
├── templates/
│   └── news_cards.html
├── output/                   # 运行时产物（滚动覆盖）
│   ├── ai_news.md            #   原始日报
│   ├── refined.md            #   精炼版
│   ├── news.json             #   API 数据源（可提交一份种子）
│   └── card.html             #   HTML 卡片（可选）
├── requirements.txt
└── README.md
```

---

## 数据流

```
ai_news_aggregator.py     produce_news.py      server.py
采集 9 个来源     →       过滤 + 精炼    →     FastAPI 提供接口
                                    ↓
                              output/news.json（覆盖写入）
                                    ↓
                    前端 fetch /api/v1/ai_news/news
```

日期写在 JSON 的 `date` 字段里；磁盘上始终只有一份当前结果。

### 采集来源

| 模块 | 来源 |
|------|------|
| GitHub Trending | github.com/trending（AI 相关过滤） |
| HF Daily Papers | huggingface.co/api/daily_papers |
| arXiv IR | export.arxiv.org/api/query |
| 国际新闻 | TechCrunch, Ars Technica, The Verge |
| 国内新闻 | 36氪, IT之家 |
| 国际公司 | HuggingFace Blog, Google Research, Anthropic, OpenAI |
| 国内公司 | DeepSeek, 智谱, 百度, 阿里, 月之暗面... |
| 社区热点 | HackerNews / Lobsters（AI 主题过滤） |

### 时效性与主题过滤

`produce_news.py`：

- 从条目中提取真实日期，超过 7 天过滤
- 屏蔽游戏/噪声；社区与 GitHub 板块强制 AI 主题

---

## API 接口

部署依赖：**运行时读取 `output/news.json`**。前端（zero-to-tech `AiNewsView.jsx`）只请求：

`GET /api/v1/ai_news/news`（不带 date）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/ai_news/news` | 当前滚动版 JSON |
| GET | `/api/v1/ai_news/news?date=YYYY-MM-DD` | 可选校验；与当前 `date` 不一致则 404 |
| GET | `/api/v1/ai_news/cards` | 当前滚动版 HTML 卡片 |
| GET | `/api/v1/ai_news/dates` | `{ dates: [当前日期], latest }` |

### JSON 结构

```json
{
  "date": "2026-08-10",
  "date_formatted": "2026年08月10日",
  "weekday": "星期一",
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
# 国内网络可用清华源：
# pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 1. 采集（需要网络）→ 覆盖 output/ai_news.md
python3 ai_news_aggregator.py

# 2. 精炼 → 覆盖 output/refined.md + output/news.json
python3 produce_news.py

# 3. 启动 API
python3 server.py
# → http://127.0.0.1:8001
```

前端：

```bash
NEXT_PUBLIC_AI_NEWS_API=http://localhost:8001 npx next dev
```

生产环境 `AiNewsView` 默认同源请求 `/api/v1/ai_news/news`，由 nginx 转到 8001。

---

## 服务器部署

### 依赖

| 层级 | 依赖 |
|------|------|
| Python | `requirements.txt`（fastapi / uvicorn / requests / bs4 / jinja2） |
| 运行时数据 | `output/news.json`（仓库可带一份种子；日常由定时任务覆盖） |
| 前端页面 | **React 运行时请求** `GET /api/v1/ai_news/news`，不是读仓库里的 HTML 静态文件 |
| `/cards` | 可选；无 `card.html` 时会用 `news.json` 即时渲染 |
| 系统 | systemd + nginx 反代 `/api/v1/ai_news/` → `127.0.0.1:8001` |

### pull 后页面空白？

网站 HTML 壳在 **zero-to-tech**，日报内容来自 **ai_news API**。只 pull `ai_news` 不够，需确认：

```bash
# 1) 数据在
ls output/news.json

# 2) API 在跑（改代码后要重启）
sudo systemctl restart ai-news-api   # 或你的服务名
curl -s http://127.0.0.1:8001/api/v1/ai_news/news | head

# 3) nginx 把 /api/v1/ai_news/ 转到 8001
curl -s https://你的域名/api/v1/ai_news/news | head

# 4) 可选：生成静态卡片页
.venv/bin/python generate_html.py    # 现在可只凭 news.json 生成
```

### 1. 安装

```bash
cd /opt/ai_news
git clone <repo> .
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 生成 / 更新数据（滚动覆盖）

```bash
python3 ai_news_aggregator.py
python3 produce_news.py
# 可选：python3 generate_html.py
```

无需重启 API：`server.py` 每次请求读磁盘上的 `news.json`。

### 3. systemd

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

### 4. Nginx

```nginx
location /api/v1/ai_news/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

### 5. 定时更新（建议）

```bash
# 每天 7:30 滚动更新
30 7 * * * cd /opt/ai_news && .venv/bin/python3 ai_news_aggregator.py && .venv/bin/python3 produce_news.py
```

日更 / 周更可之后再定；当前脚本按「每次运行覆盖当前份」设计。

---

## 故障排查

| 问题 | 解决 |
|------|------|
| `No module named 'fastapi'` | `pip install -r requirements.txt` |
| 采集时部分来源为空 | 网络或源站改版，看 `ai_news_aggregator.py` 日志 |
| API 返回 404 | 无 `output/news.json`，先跑 `produce_news.py` |
| 前端 Failed to fetch | 确认 8001 在跑，检查 nginx |
| 端口冲突 | 默认 8001，可用 `--port` |
