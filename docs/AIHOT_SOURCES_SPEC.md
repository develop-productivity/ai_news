# AIHOT 信源集成规格 (SPEC)

## 目标

将 AIHOT 的 18 个 RSS 信源集成到 ai_news 的采集器中，利用其三级分层（T1/T1.5/T2）和评分门槛机制提升内容质量。

## AIHOT 信源概览

AIHOT 自带 18 个公开 AI 新闻信源，全部为 RSS 类型，分为两个层级：

| 层级 | 含义 | 评分门槛 | 信源 |
|------|------|---------|------|
| T1 | 官方一手信源 | 平均分 >= 60 | OpenAI, Google DeepMind, Google Research, HuggingFace, Microsoft Research, NVIDIA, AWS ML, GitHub AI, Mistral, BAIR |
| T2 | 媒体与个人 | 平均分 >= 76 | The Verge AI, TechCrunch AI, Ars Technica AI, MIT Tech Review AI, The Decoder, Simon Willison, Import AI, Latent Space |

## 信源映射格式

### AIHOT 格式 (`industry/sources.json`)

```json
{
  "id": "rss-openai-news",
  "name": "OpenAI News",
  "kind": "rss",
  "config": { "feedUrl": "https://openai.com/news/rss.xml" },
  "tier": "T1",
  "owner_entity_id": "openai",
  "participation_mode": "editorial",
  "interval_minutes": 120,
  "tags": ["官方"],
  "site_fulltext": false
}
```

### ai_news 格式 (`sources_config.json`)

```json
{
  "id": "rss-openai-news",
  "name": "OpenAI News",
  "type": "rss",
  "url": "https://openai.com/news/rss.xml",
  "tier": "T1",
  "interval_minutes": 120,
  "tags": ["官方"],
  "enabled": true
}
```

### 字段映射

| AIHOT 字段 | ai_news 字段 | 说明 |
|-----------|-------------|------|
| `id` | `id` | 直接复用 |
| `name` | `name` | 直接复用 |
| `kind` | `type` | 重命名 |
| `config.feedUrl` | `url` | 从 config 中提取 |
| `tier` | `tier` | 直接复用 |
| `interval_minutes` | `interval_minutes` | 直接复用 |
| `tags` | `tags` | 直接复用 |
| `participation_mode` | `participation_mode` | editorial / signal |
| `owner_entity_id` | `owner` | 实体归属 |
| `site_fulltext` | `fulltext` | 是否抓全文 |

## 评分门槛集成

按层级设置不同门槛：

- T1 官方一手：门槛 60，更容易入选
- T1.5 官方账号/准官方：门槛 65
- T2 媒体/个人：门槛 76，需更有分量

精选逻辑：每条新闻独立打两次分，两次之和 >= 2 x 门槛 = 精选。

## 完整信源清单

### T1 官方一手（10 个，门槛 60）
1. OpenAI News — `https://openai.com/news/rss.xml`
2. Google DeepMind — `https://deepmind.google/blog/rss.xml`
3. Google Research — `https://research.google/blog/rss/`
4. HuggingFace Blog — `https://huggingface.co/blog/feed.xml` (已有)
5. Microsoft Research — `https://www.microsoft.com/en-us/research/feed/`
6. NVIDIA Blog — `https://blogs.nvidia.com/feed/`
7. AWS ML Blog — `https://aws.amazon.com/blogs/machine-learning/feed/`
8. GitHub Blog AI — `https://github.blog/ai-and-ml/feed/`
9. Mistral AI — `https://mistral.ai/news/rss`
10. BAIR Blog — `https://bair.berkeley.edu/blog/feed.xml`

### T2 媒体与个人（8 个，门槛 76）
11. The Verge AI — `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml`
12. TechCrunch AI — `https://techcrunch.com/category/artificial-intelligence/feed/` (已有)
13. Ars Technica AI — `https://arstechnica.com/ai/feed/` (已有)
14. MIT Tech Review AI — `https://www.technologyreview.com/topic/artificial-intelligence/feed/`
15. The Decoder — `https://the-decoder.com/feed/`
16. Simon Willison — `https://simonwillison.net/atom/everything/`
17. Import AI — `https://importai.substack.com/feed`
18. Latent Space — `https://www.latent.space/feed`

### 现有非 RSS 源（保留）
19. GitHub Trending — web_list
20. HuggingFace Daily Papers — json_api
21. HuggingFace Models — json_api
22. arXiv IR — xml_api
23. HackerNews — json_api
24. Lobsters — json_api
25. 36氪 — web_list
26. IT之家 — web_list
27. 国内大模型公司 — web_list

## 实施计划

1. 创建 `sources_config.json` 配置文件（27 个信源）
2. 用 `feedparser` 重写 RSS 采集部分（替代手写 XML 解析）
3. 每条新闻标注来源 tier，传给评分模块
4. 评分模块按 tier 使用对应门槛
5. 跨信源去重：同一事件被多个 RSS 源报道时合并
6. SQLite 存储信源配置和采集状态，按 `interval_minutes` 独立调度
