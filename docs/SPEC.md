# AI News — 项目规格与升级路线

> 本文档是 ai_news 项目的完整 SPEC，供多 session / 多模型协作使用。
> 每个阶段标注状态（✅ 已完成 / 🔲 未开始 / 🔄 进行中），完成后更新此处。

---

## 项目概要

一个自动采集、评分、排序 AI 行业资讯的系统，提供 JSON API 和独立网站。

- **语言**: Python 3 (后端) + Jinja2 SSR (网站)
- **框架**: FastAPI + Uvicorn
- **数据库**: SQLite (历史记录) + JSON 文件 (当前快照)
- **LLM**: OpenAI 兼容 API (DeepSeek / Qwen / GLM)，无 key 时回退到关键词启发式
- **远程仓库**: `github.com/develop-productivity/ai_news`

## 当前架构

```
ai_news_aggregator.py     produce_news.py                    server.py
采集 9+ 来源       →      过滤精炼                    →      API + 独立网站
                           ↓
                    llm_score 评分 (0-100)
                           ↓
                    llm_write 写作 (中文标题/摘要, score>=70)
                           ↓
                    dedup 去重/聚类
                           ↓
                    热门板块 Top 6
                           ↓
                    history.py → SQLite 快照
                           ↓
                    output/news.json
```

## 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `ai_news_aggregator.py` | 1284 | 采集 9+ 来源 → `output/ai_news.md` |
| `produce_news.py` | 510 | 过滤精炼 → 评分 → 写作 → 去重 → 热门 → JSON |
| `llm_score.py` | 227 | LLM 批量评分 (0-100)，无 key 回退关键词 |
| `llm_write.py` | 178 | LLM 写作 (高分条目中文标题/摘要) |
| `dedup.py` | 138 | 跨板块标题相似度去重/聚类 |
| `history.py` | 130 | SQLite 存储每日快照，支持历史查询/搜索 |
| `server.py` | 255 | FastAPI: 网站页面 + JSON API |
| `generate_html.py` | 371 | 1920x1080 卡片 HTML 渲染 |
| `paths.py` | 47 | 滚动产物路径与旧文件清理 |
| `templates/site/` | 455 | Jinja2 SSR 模板 (6 个页面) |
| `static/style.css` | 355 | 亮/暗主题样式 |
| `static/app.js` | 25 | 主题切换交互 |
| `docs/AIHOT_SOURCES_SPEC.md` | 117 | AIHOT 信源集成规格 |

## 数据流

```
采集层          过滤层          评分层          写作层          去重层          发布层
┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
│9+ 来源  │ -> │ 关键词  │ -> │ LLM/   │ -> │ LLM   │ -> │ 标题  │ -> │ JSON   │
│ RSS    │    │ 过滤   │    │ 关键词 │    │ 写作  │    │ 相似度│    │ API    │
│ JSON   │    │ 时效性  │    │ 0-100  │    │ >=70  │    │ 去重  │    │ 网站   │
│ HTML   │    │ 精炼   │    │        │    │ 翻译  │    │ 聚类  │    │ 历史   │
└────────┘    └────────┘    └────────┘    └────────┘    └────────┘    └────────┘
                                                            ↓
                                                    output/news.json
                                                    output/history.db
```

## API 端点

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| GET | `/` | 网站首页 (热门+板块卡片+事件) | ✅ |
| GET | `/hot` | 热门排行 (按分档列表) | ✅ |
| GET | `/history` | 历史日期列表 | ✅ |
| GET | `/archive/<date>` | 存档日报页面 | ✅ |
| GET | `/about` | 关于页面 | ✅ |
| GET | `/api/v1/ai_news/news` | 结构化日报 JSON | ✅ |
| GET | `/api/v1/ai_news/news?date=` | 按日期查询 | ✅ |
| GET | `/api/v1/ai_news/hot` | 热门条目 JSON | ✅ |
| GET | `/api/v1/ai_news/cards` | HTML 卡片 | ✅ |
| GET | `/api/v1/ai_news/dates` | 可用日期 | ✅ |
| GET | `/api/v1/ai_news/history` | 历史日期 JSON | ✅ |
| GET | `/api/v1/ai_news/search?q=` | 搜索历史条目 | ✅ |

## JSON 结构

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
        {
          "title": "...",
          "detail": "...",
          "score": 88,
          "source_section": "国内公司动态"
        }
      ]
    }
  ],
  "events": [
    {
      "title": "...",
      "score": 88,
      "section": "...",
      "source_count": 2,
      "sources": [{"title": "...", "section": "...", "score": 88}]
    }
  ],
  "meta": {
    "total_items": 43,
    "scored": true,
    "generated_at": "2026-10-16T21:49:23"
  }
}
```

## 配置 (.env)

```ini
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=deepseek-flash
```

无 `.env` 时全部回退到关键词模式，零成本运行。

---

## 升级路线

### Phase 1: LLM 评分 ✅

- [x] `llm_score.py` — LLM 批量评分模块
- [x] 支持 OpenAI 兼容 API (DeepSeek/Qwen/GLM)
- [x] 无 key 回退关键词启发式评分
- [x] 按板块独立评分，按分数排序
- [x] 热门板块 Top 6 生成

### Phase 2: 独立网站 ✅

- [x] Jinja2 SSR 模板 (base/index/hot/about)
- [x] FastAPI 静态文件服务
- [x] 亮/暗主题切换
- [x] 响应式布局
- [x] zero-to-tech 兼容 (AiNewsView.jsx 加 hot accent + flame icon)

### Phase 3: LLM 写作 ✅

- [x] `llm_write.py` — 高分条目中文标题/摘要生成
- [x] 英文标题翻译成中文
- [x] 已有中文标题优化措辞
- [x] 保留原标题到 `title_original` 字段

### Phase 4: 去重/聚类 ✅

- [x] `dedup.py` — 跨板块标题相似度去重
- [x] SequenceMatcher 相似度 > 0.55 归组
- [x] 保留最高分条目为代表，记录来源
- [x] 事件列表 (`events` 字段)

### Phase 5: 历史记录 ✅

- [x] `history.py` — SQLite 存储每日快照
- [x] `output/history.db` (daily_news + news_items 表)
- [x] `/history` 页面列出可用日期
- [x] `/archive/<date>` 查看存档
- [x] `/api/v1/ai_news/search` 搜索历史

### Phase 6: 卡片展开 + 布局 ✅

- [x] 板块卡片点击弹 Modal 展示全部条目
- [x] 2 列网格布局
- [x] 事件聚类展示区
- [x] "+N 更多..." 提示

### Phase 7: AIHOT 信源集成 🔲

详见 `docs/AIHOT_SOURCES_SPEC.md`。

- [ ] 创建 `sources_config.json` (27 个信源: 18 AIHOT RSS + 9 现有)
- [ ] 用 `feedparser` 重写 RSS 采集 (替代手写 XML 解析)
- [ ] 信源三级分层 T1/T1.5/T2，不同评分门槛
- [ ] 每条新闻标注来源 tier
- [ ] 评分模块按 tier 使用对应门槛 (T1=60, T1.5=65, T2=76)
- [ ] SQLite 存储信源配置和采集状态
- [ ] 按 `interval_minutes` 独立调度采集
- [ ] 失败信源标记并降频

**AIHOT 18 个 RSS 源:**

T1 官方一手 (10 个, 门槛 60):
1. OpenAI — `https://openai.com/news/rss.xml`
2. Google DeepMind — `https://deepmind.google/blog/rss.xml`
3. Google Research — `https://research.google/blog/rss/`
4. HuggingFace Blog — `https://huggingface.co/blog/feed.xml` (已有)
5. Microsoft Research — `https://www.microsoft.com/en-us/research/feed/`
6. NVIDIA Blog — `https://blogs.nvidia.com/feed/`
7. AWS ML — `https://aws.amazon.com/blogs/machine-learning/feed/`
8. GitHub Blog AI — `https://github.blog/ai-and-ml/feed/`
9. Mistral AI — `https://mistral.ai/news/rss`
10. BAIR Blog — `https://bair.berkeley.edu/blog/feed.xml`

T2 媒体/个人 (8 个, 门槛 76):
11. The Verge AI — `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml`
12. TechCrunch AI — `https://techcrunch.com/category/artificial-intelligence/feed/` (已有)
13. Ars Technica AI — `https://arstechnica.com/ai/feed/` (已有)
14. MIT Tech Review AI — `https://www.technologyreview.com/topic/artificial-intelligence/feed/`
15. The Decoder — `https://the-decoder.com/feed/`
16. Simon Willison — `https://simonwillison.net/atom/everything/`
17. Import AI — `https://importai.substack.com/feed`
18. Latent Space — `https://www.latent.space/feed`

### Phase 8: 采集器重构 🔲

- [ ] 抽象 `Source` 基类 (rss / web_list / json_api / scrape)
- [ ] RSS 统一用 `feedparser` 解析
- [ ] 信源从配置文件加载 (不再硬编码)
- [ ] 每个信源独立采集、独立重试、独立降频
- [ ] 采集结果统一为 `{title, url, detail, source, tier, published_at}` 结构
- [ ] 采集状态存入 SQLite (last_fetched, last_ok, error_count)

### Phase 9: 事件聚类增强 🔲

- [ ] 当前 `dedup.py` 用标题相似度，升级为 embedding 向量相似度
- [ ] 相似度 > 0.6 的候选用 LLM 判断 (同一事件 / 后续发展 / 不同事件)
- [ ] 低相似度合并需第二次确认 (参考 AIHOT 的 `groupReview`)
- [ ] 事件页面展示关联报道和后续发展

### Phase 10: 热度排序 🔲

- [ ] 48 小时窗口，24 小时半衰期
- [ ] 每个独立来源只计一次 (重复采集不叠加)
- [ ] 与 6 小时前对比标记上升/新出现/暴涨
- [ ] 事件级热度 = 来源数 × 时间衰减权重

### Phase 11: 日报/周报/月报 🔲

- [ ] 每日自动生成日报 (取 Top 10 事件)
- [ ] 周报从本周日报汇总
- [ ] 月报从本月日报汇总
- [ ] LLM 只写概述和段落引言，正文由规则编排

### Phase 12: 前端增强 🔲

- [ ] 事件详情页 (关联报道 + 时间线)
- [ ] 搜索页面 (UI，不只是 API)
- [ ] RSS 输出 (`/feed.xml`)
- [ ] MCP 服务接口
- [ ] `llms.txt` 和 `sitemap.xml`

---

## 运行方式

```bash
cd ai_news

# 安装依赖 (或用 uv run)
pip install -r requirements.txt
# 或: uv run --with requests --with beautifulsoup4 --with fastapi --with uvicorn --with jinja2 python3 ...

# 1. 采集
python3 ai_news_aggregator.py

# 2. 精炼 + 评分 + 写作 + 去重 + 历史
python3 produce_news.py

# 2b. 重新评分 (从现有 news.json，不需要 raw markdown)
python3 produce_news.py --rescore

# 2c. 跳过评分
python3 produce_news.py --no-score

# 3. 启动 API + 网站
python3 server.py
# → http://127.0.0.1:8001
```

## 部署

```ini
# systemd
[Unit]
Description=AI Daily News API + Website
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/ai_news
ExecStart=/opt/ai_news/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8001
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# 定时更新
30 7 * * * cd /opt/ai_news && .venv/bin/python3 ai_news_aggregator.py && .venv/bin/python3 produce_news.py
```

## 向后兼容

`/api/v1/ai_news/news` 端点保持原有 JSON 结构不变。新增字段 (`score`, `source_section`, `meta`, `events`) 对旧前端透明。新增的"今日热门"板块作为 `sections[0]` 出现，旧前端自动渲染为额外卡片。

zero-to-tech (`AiNewsView.jsx`) 已更新：`ACCENT_MAP` 加了 `hot: "#e63946"`，`ICON_MAP` 加了 `flame: "🔥"`，条目显示评分标记。

## 参考项目

AIHOT (`/Users/Admin1/data/code/third_party/AIHOT`) — 全自动 AI 新闻站点引擎，本文档的升级路线大量参考其架构设计：
- 六阶段流水线 (采集 → 预筛 → 双重评分 → 写作 → 归组 → 热度)
- 三级信源分层 + 不同评分门槛
- 事件聚类 (embedding 召回 + LLM 确认)
- 热度排序 (48h 窗口半衰期)
- 日报/周报/月报
- 回执系统 + 预算熔断
