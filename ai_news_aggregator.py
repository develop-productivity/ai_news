#!/usr/bin/python3
"""
AI News Aggregator v2 - 每日 AI 新闻聚合
========================================
数据来源:
  - GitHub Trending
  - HuggingFace Daily Papers + 模型排行榜
  - arXiv (cs.IR - 搜索/广告/推荐)
  - TechCrunch, HackerNews, The Verge, Ars Technica
  - Reddit (r/LocalLLaMA, r/MachineLearning)
  - 36kr / ithome 国内AI新闻
  - 各大模型公司博客 (OpenAI, Anthropic, Google, HF, Meta)
  - 国内大模型公司动态 (DeepSeek, 智谱, 百度, 阿里等)

  - AIHOT 18 个 RSS 信源（官方 T1 / 媒体个人 T2，见 sources_config.json）

输出（滚动覆盖，不按日期堆积）:
  output/raw_items.json  结构化条目（含 url / 来源 / tier / 时间），produce_news.py 的主输入
  output/ai_news.md      可读 Markdown 版本
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import datetime
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

from paths import (
    OUTPUT_DIR as OUTPUT_DIR_PATH,
    RAW_MD_PATH,
    RAW_ITEMS_PATH,
    ensure_output_dir,
    cleanup_dated_artifacts,
)

# ============ 配置 ============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = str(OUTPUT_DIR_PATH)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REQUESTS_TIMEOUT = 20
MAX_RETRIES = 2

GITHUB_TRENDING_URL = "https://github.com/trending"
HF_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HF_MODELS_URL = "https://huggingface.co/api/models"
ARXIV_API_URL = "https://export.arxiv.org/api/query"

CACHE_FILE = os.path.join(OUTPUT_DIR, ".translation_cache.json")


# ============ 工具函数 ============

def safe_request(url, headers=None, params=None, timeout=REQUESTS_TIMEOUT, post_data=None):
    """安全请求，带重试。post_data 不为 None 时发起 POST 请求"""
    if headers is None:
        headers = {"User-Agent": USER_AGENT}
    for attempt in range(MAX_RETRIES):
        try:
            if post_data is not None:
                resp = requests.post(url, headers=headers, json=post_data, timeout=timeout)
            else:
                resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            return None


def safe_parse_html(html):
    try:
        return BeautifulSoup(html, "html.parser")
    except Exception:
        return None


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def output_filename():
    """滚动覆盖的固定路径。"""
    return str(RAW_MD_PATH)


def truncate(text, max_len=300):
    if not text:
        return ""
    text = text.strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def strip_html(text):
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)


# ── 主题过滤：屏蔽游戏/噪声，保留 AI 相关 ──

_GAME_BLOCKLIST = [
    "游戏", "手游", "网游", "电竞", "端游", "主机游戏", "游戏联动",
    "米哈游", "无畏契约", "原神", "王者荣耀", "和平精英", "崩坏",
    "steam", "xbox", "playstation", "nintendo", "switch 游戏",
    "gaming", "videogame", "video game", "esport",
]

_NOISE_BLOCKLIST = [
    "酒店订单", "opens in a new window", "it早报",
    "渠道佣金", "运营商低价", "美瞳广告", "必胜客",
]

_AI_TOPIC_KEYWORDS = [
    "ai", "aigc", "llm", "gpt", "claude", "gemini", "openai", "anthropic",
    "deepseek", "qwen", "kimi", "glm", "mistral", "llama", "agent",
    "大模型", "人工智能", "机器学习", "深度学习", "神经网络", "多模态",
    "智能体", "生成式", "transformer", "rag", "embedding", "推理",
    "huggingface", "pytorch", "tensorflow", "mlx", "cuda", "gpu",
    "nlp", "cv", "diffusion", "微调", "蒸馏", "对齐", "强化学习",
    "coding agent", "copilot", "cursor", "vllm", "ollama",
]


def _keyword_hit(text, keyword):
    """短英文词用词边界，避免 Tail/email 误匹配 ai。"""
    t = text or ""
    k = keyword.lower()
    if re.fullmatch(r"[a-z0-9_+./-]{1,4}", k):
        return re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", t, re.IGNORECASE) is not None
    return k in t.lower()


def _contains_any(text, keywords):
    return any(_keyword_hit(text, k) for k in keywords)


def is_game_or_noise(text):
    """游戏相关或明显噪声标题。"""
    return _contains_any(text, _GAME_BLOCKLIST) or _contains_any(text, _NOISE_BLOCKLIST)


def is_ai_topic(text, min_hits=1):
    """粗粒度 AI 主题判断。"""
    if not text:
        return False
    hits = sum(1 for k in _AI_TOPIC_KEYWORDS if _keyword_hit(text, k))
    return hits >= min_hits


# ============ 翻译模块 ============

_translation_cache = {}

def _load_cache():
    global _translation_cache
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                _translation_cache = json.load(f)
    except Exception:
        _translation_cache = {}


def _save_cache():
    try:
        # Keep only last 500 entries to avoid unbounded growth
        if len(_translation_cache) > 500:
            keys = list(_translation_cache.keys())[-500:]
            _translation_cache = {k: _translation_cache[k] for k in keys}
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_translation_cache, f, ensure_ascii=False)
    except Exception:
        pass


def translate_to_chinese(text, max_len=400):
    """Translate English text to Chinese using HF inference API (free tier)"""
    if not text or len(text.strip()) < 15:
        return ""

    text = text[:max_len]
    cache_key = text[:100]

    _load_cache()
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    token = os.environ.get("HF_TOKEN", "")
    if not token:
        return ""

    try:
        url = "https://api-inference.huggingface.co/models/Helsinki-NLP/opus-mt-en-zh"
        resp = safe_request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            post_data={"inputs": text},
            timeout=45,
        )
        if resp and resp.status_code == 200:
            result = resp.json()
            if isinstance(result, list) and len(result) > 0:
                translation = result[0].get("translation_text", "")
                if translation:
                    _translation_cache[cache_key] = translation
                    _save_cache()
                    return translation
    except Exception:
        pass

    return ""


def translate_papers(papers, field="summary"):
    """批量翻译论文摘要"""
    texts = [p.get(field, "")[:350] for p in papers if p.get(field)]
    if not texts:
        return papers

    translated = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        fut_map = {ex.submit(translate_to_chinese, t): i for i, t in enumerate(texts)}
        results = [""] * len(texts)
        for fut in as_completed(fut_map):
            idx = fut_map[fut]
            try:
                results[idx] = fut.result()
            except Exception:
                results[idx] = ""
            time.sleep(0.3)  # rate limit

    # Attach translations back
    translated_idx = 0
    for p in papers:
        if p.get(field):
            p["summary_cn"] = results[translated_idx]
            translated_idx += 1
        else:
            p["summary_cn"] = ""
    return papers


def extract_arxiv_id(url_or_id):
    """Extract arXiv ID from URL or ID string"""
    if not url_or_id:
        return ""
    m = re.search(r'(\d{4}\.\d{4,5})(v\d+)?', url_or_id)
    return m.group(1) if m else url_or_id.replace("arXiv:", "").strip()


def deduplicate_papers(papers, key="arxiv_id"):
    """Remove duplicate papers by a key field"""
    seen = set()
    unique = []
    for p in papers:
        k = p.get(key, "")
        if k and k not in seen:
            seen.add(k)
            unique.append(p)
        elif not k:
            unique.append(p)
    return unique


# ============ 数据采集模块 ============

# ── 1. GitHub Trending ──

def fetch_github_trending():
    """GitHub 今日热门仓库"""
    print("  [GitHub] 正在获取趋势仓库...")
    repos = []

    resp = safe_request(GITHUB_TRENDING_URL, params={"since": "daily"})
    if not resp:
        return repos

    soup = safe_parse_html(resp.text)
    if not soup:
        return repos

    for el in (soup.select("article.Box-row") or soup.select("div.Box-row"))[:15]:
        try:
            h2 = el.find("h2")
            if not h2 or not h2.find("a"):
                continue
            full_name = h2.find("a").get("href", "").strip("/")
            if not full_name:
                continue

            desc_el = el.find("p", class_="col-9") or el.find("p")
            description = desc_el.text.strip() if desc_el else ""

            lang_el = el.find("span", itemprop="programmingLanguage")
            lang = lang_el.text.strip() if lang_el is not None else ""

            # Stars
            stars_text = ""
            for a in el.find_all("a", href=True):
                if "/stargazers" in a.get("href", ""):
                    stars_text = a.text.strip().replace(",", "")
                    break

            blob = f"{full_name} {description}"
            if is_game_or_noise(blob) or not is_ai_topic(blob):
                continue

            repos.append({
                "name": full_name,
                "url": f"https://github.com/{full_name}",
                "description": truncate(description, 80),
                "language": lang,
                "stars": stars_text,
            })
        except Exception:
            continue

    print(f"    ✓ {len(repos)} 个仓库 (已过滤非 AI/游戏)")
    return repos


# ── 2. HuggingFace Daily Papers（主要论文来源）──

def fetch_hf_papers():
    """HF Daily Papers - 每日精选论文"""
    print("  [HF Papers] 正在获取每日论文...")
    papers = []

    resp = safe_request(HF_PAPERS_URL)
    if not resp:
        return papers

    try:
        data = resp.json()
    except (json.JSONDecodeError, TypeError):
        return papers

    for item in data[:15]:
        try:
            paper = item.get("paper", {})
            if not paper:
                continue

            pid = paper.get("id", "")
            title = paper.get("title", "")
            authors = [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]
            summary = truncate(paper.get("summary", ""), 400)

            papers.append({
                "title": title,
                "hf_url": f"https://huggingface.co/papers/{pid}" if pid else "",
                "arxiv_url": f"https://arxiv.org/abs/{pid}" if pid else "",
                "arxiv_id": pid,
                "authors": authors[:5],
                "summary": summary,
                "summary_cn": "",
                "upvotes": paper.get("upvotes", 0),
                "published_at": item.get("publishedAt") or paper.get("publishedAt"),
            })
        except Exception:
            continue

    # Translate summaries
    papers = translate_papers(papers)

    print(f"    ✓ {len(papers)} 篇论文")
    return papers


# ── 3. HuggingFace 模型排行榜（新增）──

def fetch_hf_trending_models():
    """HF Trending Models - 热门模型排行榜"""
    print("  [HF Models] 正在获取热门模型...")
    models = []

    resp = safe_request(HF_MODELS_URL, params={
        "sort": "trendingScore",
        "direction": -1,
        "limit": 15,
    })
    if not resp:
        return models

    try:
        data = resp.json()
    except (json.JSONDecodeError, TypeError):
        return models

    for m in data[:15]:
        try:
            models.append({
                "id": m.get("id", ""),
                "url": f"https://huggingface.co/{m.get('id', '')}",
                "downloads": m.get("downloads", 0),
                "likes": m.get("likes", 0),
                "pipeline_tag": m.get("pipeline_tag", ""),
                "description": truncate(m.get("cardData", {}).get("summary", ""), 100),
            })
        except Exception:
            continue

    print(f"    ✓ {len(models)} 个热门模型")
    return models


# ── 4. arXiv IR (搜索/广告/推荐) ──

def fetch_arxiv_ir_papers():
    """arXiv cs.IR - 搜索/广告/推荐论文（与 HF Papers 无重叠）"""
    print("  [arXiv IR] 正在获取搜索/广告/推荐论文...")
    papers = []

    url = (f"{ARXIV_API_URL}?search_query=cat:cs.IR"
           f"&sortBy=submittedDate&sortOrder=descending&max_results=10")

    resp = safe_request(url)
    if not resp:
        return papers

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return papers

    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for entry in root.findall("atom:entry", ns):
        try:
            title_el = entry.find("atom:title", ns)
            title = title_el.text.strip().replace("\n", " ") if title_el is not None else ""

            summary_el = entry.find("atom:summary", ns)
            summary = truncate(summary_el.text.strip().replace("\n", " ") if summary_el is not None else "", 400)

            id_el = entry.find("atom:id", ns)
            url_str = id_el.text.strip() if id_el is not None else ""
            arxiv_id = extract_arxiv_id(url_str)

            authors = []
            for ae in entry.findall("atom:author", ns):
                ne = ae.find("atom:name", ns)
                if ne is not None:
                    authors.append(ne.text.strip())

            cats = []
            for ce in entry.findall("atom:category", ns):
                t = ce.get("term", "")
                if t:
                    cats.append(t)

            published_el = entry.find("atom:published", ns)
            published_date = published_el.text[:10] if published_el is not None else ""

            papers.append({
                "title": title,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "arxiv_id": arxiv_id,
                "authors": authors[:5],
                "summary": summary,
                "summary_cn": "",
                "categories": cats[:5],
                "published": published_date,
            })
        except Exception:
            continue

    # Translate
    papers = translate_papers(papers)

    print(f"    ✓ {len(papers)} 篇论文")
    return papers


# ── 5. 国际 AI 新闻 ──
# RSS 媒体源（TechCrunch / Verge / Ars / MIT TR / Decoder / ...）统一走 rss_sources，
# 这里只保留非 RSS 的 HackerNews 搜索。

def fetch_international_ai_news():
    """国际 AI 新闻（非 RSS 部分）：HackerNews AI 搜索"""
    print("  [AI News] 正在获取 HackerNews AI 讨论...")
    news = []
    try:
        cutoff = int(time.time()) - 86400 * 2
        # Algolia 不支持 OR 语法；用 optionalWords 让任一词命中即可，再按热度门槛过滤
        words = "AI LLM machine learning"
        hn = safe_request("https://hn.algolia.com/api/v1/search", params={
            "query": words, "optionalWords": words,
            "tags": "story", "hitsPerPage": 20,
            "numericFilters": f"created_at_i>{cutoff},points>30",
        })
        if hn:
            hits = sorted(hn.json().get("hits", []), key=lambda h: h.get("points", 0), reverse=True)
            for hit in hits:
                if len(news) >= 8:
                    break
                title = hit.get("title", "")
                if not title or is_game_or_noise(title) or not is_ai_topic(title):
                    continue
                oid = hit.get("objectID", "")
                news.append({
                    "source": "Hacker News", "title": title,
                    "url": hit.get("url", "") or f"https://news.ycombinator.com/item?id={oid}",
                    "discuss_url": f"https://news.ycombinator.com/item?id={oid}" if oid else "",
                    "points": hit.get("points", 0),
                    "published_at": hit.get("created_at"),
                    "summary": "",
                })
    except Exception as e:
        print(f"    [WARN] HN: {e}")
    print(f"    ✓ {len(news)} 条")
    return news


# ── 5b. RSS 信源（AIHOT 18 源 + Anthropic，见 sources_config.json）──

def fetch_rss_feeds():
    """按 sources_config.json 抓取全部 RSS 信源，返回 {section_key: [items]}"""
    print("  [RSS] 正在抓取配置信源...")
    from rss_sources import fetch_all
    items, statuses = fetch_all(reject=is_game_or_noise)
    by_section = {}
    for it in items:
        by_section.setdefault(it["section_key"], []).append(it)
    ok = sum(1 for s in statuses if s["ok"])
    print(f"    ✓ {ok}/{len(statuses)} 信源成功，共 {len(items)} 条")
    return by_section


# ── 6. 国内 AI 新闻 ──

def fetch_chinese_ai_news():
    """国内 AI 行业新闻 —— 聚焦最新 AI 动态"""
    print("  [CN News] 正在爬取国内 AI 新闻...")
    all_news = []

    # ---- AI 关键词列表（用于过滤和打分） ----
    AI_KEYWORDS_HIGH = ["大模型", "LLM", "人工智能", "AGI", "GPT", "deepseek",
                        "智谱", "文心", "通义千问", "混元", "moonshot",
                        "kimi", "qwen", "glm", "yi-", "minimax", "step-",
                        "openai", "claude", "gemini", "llama", "mistral",
                        "生成式AI", "AIGC", "多模态", "AI Agent", "AI代理"]

    AI_KEYWORDS_MED = ["AI", "模型", "芯片", "GPU", "算力", "训练", "推理",
                       "算法", "智能", "自动驾驶", "机器人", "数据集",
                       "开源", "编程", "代码", "深度学习", "机器学习",
                       "transformer", "注意力机制", "embedding",
                       "RAG", "检索增强", "智能体", "Agent",
                       "量化", "微调", "fine-tuning", "SFT", "RLHF",
                       "华为", "百度", "腾讯", "阿里", "字节", "小米",
                       "英伟达", "NVIDIA", "AMD", "Intel"]

    def _ai_relevance_score(title):
        """计算标题的 AI 相关度分数"""
        title_lower = title.lower()
        score = 0
        for kw in AI_KEYWORDS_HIGH:
            if kw.lower() in title_lower:
                score += 3
        for kw in AI_KEYWORDS_MED:
            if kw.lower() in title_lower:
                score += 1
        return score

    def _is_ai_related(title):
        return _ai_relevance_score(title) >= 1

    # 6a. 36氪 AI 文章搜索
    try:
        # Try search page (server-rendered)
        kr = safe_request("https://36kr.com/search/articles/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD")
        if not kr:
            kr = safe_request("https://36kr.com/")
        if kr:
            soup = BeautifulSoup(kr.content, "html.parser", from_encoding="utf-8")
            seen_36kr = set()
            for a in soup.find_all("a", href=True):
                title = a.text.strip()
                href = a["href"]
                if not title or len(title) < 8:
                    continue
                title = re.sub(r'\s+', ' ', title).strip()
                if is_game_or_noise(title):
                    continue
                score = _ai_relevance_score(title)
                if score < 2:
                    continue
                if title in seen_36kr:
                    continue
                seen_36kr.add(title)
                url = href if href.startswith("http") else "https://36kr.com" + href
                all_news.append({
                    "source": "36氪", "title": title,
                    "url": url, "summary": "",
                    "_score": score,
                })
            print(f"    ✓ 36氪: {len([n for n in all_news if n['source']=='36氪'])} 条")
    except Exception as e:
        print(f"    [WARN] 36kr: {e}")

    # 6b. IT之家 AI 版块
    try:
        it = safe_request("https://ithome.com/")
        if it:
            soup = BeautifulSoup(it.content, "html.parser", from_encoding="utf-8")
            seen_titles = set()
            for a in soup.find_all("a", href=True):
                title = a.text.strip()
                href = a["href"]
                if not title or len(title) < 8:
                    continue
                title = re.sub(r'\s+', ' ', title).strip()
                if is_game_or_noise(title):
                    continue
                if not _is_ai_related(title):
                    continue
                score = _ai_relevance_score(title)
                if score < 2:  # Require at least 2 keyword matches for IT之家
                    continue
                # Skip navigation/UI elements
                skip_words = ["登录", "注册", "导航", "搜索", "关于", "联系",
                              "copyright", "footer", "首页", "最新", "热门"]
                if any(s in title.lower() for s in skip_words):
                    continue
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                url = href if href.startswith("http") else "https://ithome.com" + href
                all_news.append({
                    "source": "IT之家",
                    "title": title,
                    "url": url,
                    "summary": "",
                    "_score": score,  # for ranking
                })
            print(f"    ✓ IT之家: {len([n for n in all_news if n['source']=='IT之家'])} 条")
    except Exception as e:
        print(f"    [WARN] ithome: {e}")

    # 6c. 少数派 AI 相关 - 试试其他中文科技媒体
    try:
        ss = safe_request("https://sspai.com/")
        if ss:
            soup = BeautifulSoup(ss.content, "html.parser", from_encoding="utf-8")
            for a in soup.find_all("a", href=True):
                title = a.text.strip()
                href = a["href"]
                if not title or len(title) < 8 or len(title) > 80:
                    continue
                title = re.sub(r'\s+', ' ', title).strip()
                # 过滤论坛灌水/长独白
                if title.startswith("[") or "我是" in title[:20]:
                    continue
                if is_game_or_noise(title):
                    continue
                if _ai_relevance_score(title) < 2:
                    continue
                url = href if href.startswith("http") else "https://sspai.com" + href
                all_news.append({
                    "source": "少数派", "title": title,
                    "url": url, "summary": "", "_score": _ai_relevance_score(title),
                })
            print(f"    ✓ 少数派: {len([n for n in all_news if n['source']=='少数派'])} 条")
    except Exception as e:
        print(f"    [WARN] 少数派: {e}")

    # Dedup + score sort
    seen = set()
    unique = []
    for n in all_news:
        title = n.get("title", "")
        if is_game_or_noise(title):
            continue
        key = title.lower().strip()[:40]
        if key not in seen:
            seen.add(key)
            score = n.get("_score", 0) or _ai_relevance_score(title)
            n["_score"] = score
            unique.append(n)

    # Sort by AI relevance score (higher = more relevant)
    unique.sort(key=lambda x: x.get("_score", 0), reverse=True)

    print(f"    ✓ 国内新闻共计 {len(unique)} 条")
    return unique[:15]


# ── 8. 国内大模型公司动态 ──

def fetch_chinese_company_news():
    """国内大模型公司动态 —— 从IT之家/36氪收集各公司最新消息"""
    print("  [CN Companies] 正在获取国内公司动态...")
    news = []

    # 国内大模型公司及其关注关键词
    companies = {
        "DeepSeek": ["deepseek", "深度求索", "deep seek"],
        "智谱AI": ["智谱", "zhipu", "glm", "chatglm"],
        "百度 文心一言": ["百度", "文心", "ernie", "百度AI"],
        "阿里 通义千问": ["阿里", "通义千问", "通义", "qwen"],
        "月之暗面 Moonshot": ["月之暗面", "moonshot", "kimi"],
        "腾讯 混元": ["腾讯", "混元", "hunyuan"],
        "字节跳动 豆包": ["字节跳动", "字节", "豆包", "doubao"],
        "MiniMax": ["minimax", "hailuo"],
        "零一万物": ["零一万物", "yi-"],
        "百川智能": ["百川", "baichuan"],
    }

    # 从IT之家和36氪的已有数据中提取各公司新闻
    # 重新抓取 IT之家 AI 相关新闻并分类到各公司
    try:
        it = safe_request("https://ithome.com/")
        if it:
            soup = BeautifulSoup(it.content, "html.parser", from_encoding="utf-8")
            company_articles = {}
            for a in soup.find_all("a", href=True):
                title = a.text.strip()
                href = a["href"]
                if not title or len(title) < 8:
                    continue
                title = re.sub(r'\s+', ' ', title).strip()
                url = href if href.startswith("http") else "https://ithome.com" + href

                if is_game_or_noise(title):
                    continue
                # 公司名命中还不够：必须同时是 AI 话题（避免腾讯手游、豆包酒店等）
                if not is_ai_topic(title):
                    continue

                for comp_name, keywords in companies.items():
                    if any(k.lower() in title.lower() for k in keywords):
                        if comp_name not in company_articles:
                            company_articles[comp_name] = []
                        if len(company_articles[comp_name]) < 2:
                            company_articles[comp_name].append({
                                "title": title, "url": url,
                            })

            for comp_name, articles in company_articles.items():
                # Dedup by title
                seen_titles = set()
                unique_articles = []
                for art in articles:
                    if art["title"] not in seen_titles:
                        seen_titles.add(art["title"])
                        unique_articles.append(art)
                for article in unique_articles:
                    news.append({
                        "source": comp_name,
                        "title": article["title"],
                        "url": article["url"],
                        "origin": "IT之家",
                    })
                print(f"    ✓ {comp_name}: {len(unique_articles)} 条")
    except Exception as e:
        print(f"    [WARN] 公司新闻爬取: {e}")

    # 无新闻的公司不再填充「官网」占位（无时效、无信息量）
    missing = set(companies) - set(n["source"] for n in news)
    if missing:
        print(f"    [跳过] 今日无 AI 相关动态: {', '.join(sorted(missing))}")

    print(f"    ✓ 国内公司动态共计 {len(news)} 条")
    return news[:15]


# ── 9. Reddit 社区热点 ──

def fetch_community_highlights():
    """社区热门讨论（HackerNews + Lobsters 替代 Reddit）"""
    print("  [Community] 正在获取社区热门...")
    highlights = []

    # HackerNews front page (top stories)
    try:
        hn = safe_request("https://hacker-news.firebaseio.com/v0/topstories.json")
        if hn:
            top_ids = hn.json()[:15]
            for story_id in top_ids:
                try:
                    item = safe_request(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
                    if item:
                        data = item.json()
                        title = data.get("title", "")
                        url = data.get("url", "") or f"https://news.ycombinator.com/item?id={story_id}"
                        score = data.get("score", 0)
                        if title and is_ai_topic(title) and not is_game_or_noise(title):
                            highlights.append({
                                "title": title,
                                "url": url,
                                "source": "HackerNews Top",
                                "score": score,
                                "discuss_url": f"https://news.ycombinator.com/item?id={story_id}",
                            })
                except Exception:
                    continue
        print(f"    ✓ HackerNews: {len(highlights)} 条 (AI 过滤后)")
    except Exception as e:
        print(f"    [WARN] HN: {e}")

    # Lobsters (tech-focused)
    try:
        lob = safe_request("https://lobste.rs/hottest.json", headers={"User-Agent": USER_AGENT})
        if lob:
            for item in lob.json()[:5]:
                title = item.get("title", "")
                url = item.get("url", "") or f"https://lobste.rs/s/{item.get('short_id', '')}"
                if title and is_ai_topic(title) and not is_game_or_noise(title):
                    highlights.append({
                        "title": title,
                        "url": url,
                        "source": "Lobsters",
                        "score": item.get("score", 0),
                        "discuss_url": item.get("comments_url", ""),
                    })
    except Exception as e:
        print(f"    [WARN] Lobsters: {e}")

    # Dedup by title
    seen = set()
    unique = []
    for h in highlights:
        key = h["title"].lower().strip()[:50]
        if key not in seen:
            seen.add(key)
            unique.append(h)

    print(f"    ✓ 共计 {len(unique)} 条")
    return unique[:12]


# ============ 报告生成 ============

def fmt_stars(n):
    """Format star count"""
    if not n:
        return "N/A"
    try:
        n = int(n.replace(",", ""))
        if n >= 1000:
            return f"{n/1000:.1f}k"
        return str(n)
    except (ValueError, AttributeError):
        return str(n)


def generate_report(gh, hf_papers, hf_models, arxiv_ir, intl_news, cn_news, intl_companies, cn_companies, community):
    """生成完整 Markdown 报告"""
    today = today_str()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays[datetime.date.today().weekday()]

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md = f"""# 🤖 AI 行业日报 - {today} ({weekday})

> 自动聚合 | 数据来源: GitHub · HuggingFace · arXiv · TechCrunch · HN · Lobsters · 36氪 · IT之家

---

## 📌 目录

1. [🔥 GitHub 热门趋势](#-github-热门趋势)
2. [📄 今日论文精选 (HuggingFace)](#-今日论文精选-huggingface)
3. [🏆 HuggingFace 模型排行榜](#-huggingface-模型排行榜)
4. [🔍 搜索/广告/推荐 最新论文 (arXiv)](#-搜索广告推荐-最新论文-arxiv)
5. [🌐 国际 AI 行业新闻](#-国际-ai-行业新闻)
6. [🇨🇳 国内 AI 行业新闻](#-国内-ai-行业新闻)
7. [🏢 国际大模型公司动态](#-国际大模型公司动态)
8. [🏢 国内大模型公司动态](#-国内大模型公司动态)
9. [💬 社区热点](#-社区热点)

---

## 🔥 GitHub 热门趋势

> 数据来源: [GitHub Trending](https://github.com/trending) · Daily

"""

    if gh:
        for i, repo in enumerate(gh[:15], 1):
            name = repo["name"]
            desc = repo.get("description", "") or "暂无描述"
            lang = repo.get("language", "") or "—"
            stars = fmt_stars(repo.get("stars", ""))
            md += (
                f"### {i}. [{name}]({repo['url']})\n\n"
                f"- **描述**: {desc}\n"
                f"- **⭐ Stars**: {stars}  |  **🔤 语言**: {lang}\n\n"
            )
    else:
        md += "*暂无数据*\n\n"

    # ── HF Papers ──
    md += f"""---
## 📄 今日论文精选 (HuggingFace)

> 来源: [HuggingFace Daily Papers](https://huggingface.co/papers) · AI/ML/NLP 精选论文

"""

    if hf_papers:
        for i, p in enumerate(hf_papers[:12], 1):
            md += f"### {i}. {p['title']}\n\n"

            # Links
            parts = []
            if p.get("hf_url"):
                parts.append(f"[HuggingFace]({p['hf_url']})")
            if p.get("arxiv_url"):
                parts.append(f"[arXiv]({p['arxiv_url']})")
            if p.get("arxiv_id"):
                parts.append(f"`{p['arxiv_id']}`")
            if parts:
                md += f"- **🔗 链接**: {' | '.join(parts)}\n"
            if p.get("authors"):
                md += f"- **👥 作者**: {', '.join(p['authors'])}\n"
            if p.get("upvotes"):
                md += f"- **👍 点赞**: {p['upvotes']}\n"

            # English summary
            if p.get("summary"):
                md += f"- **📝 英文摘要**: {p['summary']}\n"

            # Chinese translation
            if p.get("summary_cn"):
                md += f"- **📝 中文摘要**: {p['summary_cn']}\n"

            md += "\n"
    else:
        md += "*暂无数据*\n\n"

    # ── HF Models ──
    md += f"""---
## 🏆 HuggingFace 模型排行榜

> 数据来源: [HuggingFace Hub](https://huggingface.co/models) · Trending 排行

| # | 模型 | 📥 下载量 | 👍 点赞数 | 🔧 类型 |
|---|------|----------|----------|--------|
"""

    if hf_models:
        for i, m in enumerate(hf_models[:12], 1):
            downloads = f"{m['downloads']:,}" if m.get("downloads") else "N/A"
            likes = f"{m['likes']:,}" if m.get("likes") else "N/A"
            tag = m.get("pipeline_tag", "—") or "—"
            md += f"| {i} | [{m['id']}]({m['url']}) | {downloads} | {likes} | {tag} |\n"
    else:
        md += "| — | 暂无数据 | — | — | — |\n"

    # ── arXiv IR ──
    md += f"""\n---
## 🔍 搜索/广告/推荐 最新论文 (arXiv)

> 来源: [arXiv cs.IR](https://arxiv.org/list/cs.IR/recent) · Information Retrieval

"""

    if arxiv_ir:
        for i, p in enumerate(arxiv_ir[:8], 1):
            md += f"### {i}. {p['title']}\n\n"
            md += f"- **🔗 链接**: [`{p.get('arxiv_id', '')}`]({p['url']})"
            if p.get("categories"):
                md += f" | 分类: `{'`, `'.join(p['categories'][:3])}`"
            md += "\n"
            if p.get("authors"):
                md += f"- **👥 作者**: {', '.join(p['authors'])}\n"
            if p.get("published"):
                md += f"- **📅 投稿日期**: {p['published']}\n"
            if p.get("summary"):
                md += f"- **📝 英文摘要**: {p['summary']}\n"
            if p.get("summary_cn"):
                md += f"- **📝 中文摘要**: {p['summary_cn']}\n"
            md += "\n"
    else:
        md += "*暂无数据*\n\n"

    # ── International News ──
    md += f"""---
## 🌐 国际 AI 行业新闻

"""

    if intl_news:
        for i, n in enumerate(intl_news, 1):
            pts = n.get("points", 0)
            pts_str = f" 🔥{pts}" if pts else ""
            md += f"### {i}. [{n['title']}]({n['url']})\n\n"
            md += f"- **来源**: {n['source']}{pts_str}\n"
            if n.get("summary"):
                md += f"- **摘要**: {n['summary']}\n"
            md += "\n"
    else:
        md += "*暂无数据*\n\n"

    # ── Chinese News ──
    md += f"""---
## 🇨🇳 国内 AI 行业新闻

"""

    if cn_news:
        for i, n in enumerate(cn_news, 1):
            md += f"### {i}. [{n['title']}]({n['url']})\n\n"
            md += f"- **来源**: {n['source']}\n"
            md += "\n"
    else:
        md += "*暂无数据*\n\n"

    # ── International Companies ──
    md += f"""---
## 🏢 国际大模型公司动态

"""

    if intl_companies:
        by_src = {}
        for item in intl_companies:
            by_src.setdefault(item["source"], []).append(item)
        for src, items in by_src.items():
            md += f"### {src}\n\n"
            for i, item in enumerate(items[:5], 1):
                md += f"{i}. [{item['title']}]({item['url']})\n"
            md += "\n"
    else:
        md += "*暂无数据*\n\n"

    # ── Chinese Companies ──
    md += f"""---
## 🏢 国内大模型公司动态

"""

    if cn_companies:
        by_src = {}
        for item in cn_companies:
            by_src.setdefault(item["source"], []).append(item)
        for src, items in by_src.items():
            md += f"### {src}\n\n"
            for i, item in enumerate(items[:3], 1):
                title = item.get("title", "官网")
                if title == "官网":
                    md += f"{i}. [{src} 官网]({item['url']})\n"
                else:
                    md += f"{i}. [{title}]({item['url']})\n"
            md += "\n"
    else:
        md += "*暂无数据*\n"

    # ── Community ──
    md += f"""\n---
## 💬 社区热点

> 数据来源: HackerNews Top Stories · Lobsters

"""

    if community:
        by_src = {}
        for item in community:
            by_src.setdefault(item["source"], []).append(item)
        for src, items in by_src.items():
            md += f"### {src}\n\n"
            for i, item in enumerate(items[:6], 1):
                score = item.get("score", 0)
                score_str = f" 🔥{score}" if score else ""
                md += f"{i}. [{item['title']}]({item['url']}){score_str}\n"
            md += "\n"
    else:
        md += "*暂无数据*\n"

    # Footer
    md += f"""---
> 📅 生成时间: {now}
> 🤖 AI News Aggregator v2
> 🌐 数据来源: GitHub · HuggingFace · arXiv · TechCrunch · HN · Lobsters · 36氪 · IT之家
"""

    return md


# ============ 结构化输出 ============

def _raw_item(title, url, detail="", source="", tier="", published_at=None,
              links=None, meta=None, tags=None, item_id=None):
    from rss_sources import item_id as make_id
    links = [l for l in (links or []) if l.get("url")]
    meta = {k: v for k, v in (meta or {}).items() if v}
    return {
        "id": item_id or make_id(url, title),
        "title": (title or "").strip(),
        "url": url or "",
        "detail": (detail or "").strip(),
        "source": source,
        "tier": tier,
        "tags": tags or [],
        "published_at": published_at,
        "links": links,
        "meta": meta,
    }


def build_raw_items(r):
    """把各采集模块的结果统一成 {section_key: [item]}，保留 url / 来源 / 时间等元数据。
    produce_news.py 优先读取它，不再从 Markdown 反解析（反解析会丢失链接）。"""
    sections = {}

    sections["github"] = [
        _raw_item(g["name"], g["url"], g.get("description", ""), "GitHub Trending",
                  meta={"stars": fmt_stars(g.get("stars", "")), "language": g.get("language", "")})
        for g in r.get("gh", [])
    ]
    sections["hf_papers"] = [
        _raw_item(p["title"], p.get("hf_url") or p.get("arxiv_url"),
                  p.get("summary_cn") or p.get("summary", ""), "HF Daily Papers",
                  published_at=p.get("published_at"),
                  links=[{"label": "arXiv", "url": p.get("arxiv_url", "")}],
                  meta={"authors": ", ".join(p.get("authors", [])), "upvotes": p.get("upvotes", 0)})
        for p in r.get("hf_papers", [])
    ]
    sections["arxiv_ir"] = [
        _raw_item(p["title"], p["url"], p.get("summary_cn") or p.get("summary", ""), "arXiv cs.IR",
                  published_at=p.get("published") or None,
                  meta={"authors": ", ".join(p.get("authors", [])), "categories": ", ".join(p.get("categories", [])[:3])})
        for p in r.get("arxiv_ir", [])
    ]

    def news_item(n):
        if n.get("id"):  # 来自 rss_sources，已是标准结构
            return _raw_item(n["title"], n["url"], n.get("summary", ""), n["source"], n.get("tier", ""),
                             n.get("published_at"), tags=n.get("tags"), item_id=n["id"])
        return _raw_item(n["title"], n["url"], n.get("summary", ""), n.get("source", ""),
                         published_at=n.get("published_at"),
                         links=[{"label": "讨论", "url": n.get("discuss_url", "")}],
                         meta={"points": n.get("points") or n.get("score")})

    sections["intl_news"] = [news_item(n) for n in r.get("intl_news", [])]
    sections["intl_company"] = [news_item(n) for n in r.get("intl_companies", [])]
    sections["cn_news"] = [news_item(n) for n in r.get("cn_news", [])]
    sections["cn_company"] = [
        _raw_item(n["title"], n["url"], "", n.get("origin", ""), tags=[n["source"]])
        for n in r.get("cn_companies", [])
    ]
    sections["community"] = [news_item(n) for n in r.get("community", [])]

    return {
        "date": today_str(),
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "sections": sections,
    }


# ============ 主函数 ============

def main():
    start = time.time()
    print(f"{'='*60}")
    print(f"  AI News Aggregator v2 - {today_str()}")
    print(f"{'='*60}\n")

    ensure_output_dir()

    # Load HF_TOKEN from .env if available
    env_file = os.path.join(OUTPUT_DIR, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()

    # Load translation cache
    _load_cache()

    modules = [
        ("📊 1/9 GitHub Trending", fetch_github_trending, "gh"),
        ("📄 2/9 HF Daily Papers", fetch_hf_papers, "hf_papers"),
        ("🏆 3/9 HF Model Leaderboard", fetch_hf_trending_models, "hf_models"),
        ("🔍 4/9 arXiv IR Papers", fetch_arxiv_ir_papers, "arxiv_ir"),
        ("🌐 5/9 International AI News", fetch_international_ai_news, "intl_news"),
        ("🇨🇳 6/9 Chinese AI News", fetch_chinese_ai_news, "cn_news"),
        ("📡 7/9 RSS Feeds (AIHOT)", fetch_rss_feeds, "rss"),
        ("🏢 8/9 Chinese Companies", fetch_chinese_company_news, "cn_companies"),
        ("💬 9/9 Community Highlights", fetch_community_highlights, "community"),
    ]

    results = {}
    for label, func, key in modules:
        print(f"\n{'─'*40}")
        print(f"{label}")
        print(f"{'─'*40}")
        try:
            results[key] = func()
        except Exception as e:
            print(f"  [ERROR] {e}")
            results[key] = {} if key == "rss" else []

    rss = results.pop("rss", {}) or {}
    results["intl_news"] = rss.get("intl_news", []) + results.get("intl_news", [])
    results["intl_companies"] = rss.get("intl_company", [])

    raw = build_raw_items(results)
    with open(RAW_ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print(f"\n  🧾 结构化条目 → {RAW_ITEMS_PATH} ({sum(len(v) for v in raw['sections'].values())} 条)")

    # Generate report
    print(f"\n{'─'*40}")
    print("📝 生成 Markdown 报告...")
    print(f"{'─'*40}")

    report = generate_report(
        gh=results.get("gh", []),
        hf_papers=results.get("hf_papers", []),
        hf_models=results.get("hf_models", []),
        arxiv_ir=results.get("arxiv_ir", []),
        intl_news=results.get("intl_news", []),
        cn_news=results.get("cn_news", []),
        intl_companies=results.get("intl_companies", []),
        cn_companies=results.get("cn_companies", []),
        community=results.get("community", []),
    )

    # Write file（滚动覆盖）
    filename = output_filename()
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)

    removed = cleanup_dated_artifacts()
    if removed:
        print(f"  🧹 已清理旧日期产物: {len(removed)} 个")

    elapsed = time.time() - start
    size = os.path.getsize(filename)

    print(f"\n{'✅'} 报告已生成（滚动覆盖）!")
    print(f"  📁 {filename}")
    print(f"  📏 {size:,} bytes | ⏱ {elapsed:.1f}s\n")

    print("📋 今日概要:")
    summary = {
        "GitHub 仓库": len(results.get("gh", [])),
        "HF 论文": len(results.get("hf_papers", [])),
        "HF 模型": len(results.get("hf_models", [])),
        "arXiv IR 论文": len(results.get("arxiv_ir", [])),
        "国际新闻": len(results.get("intl_news", [])),
        "国内新闻": len(results.get("cn_news", [])),
        "国际公司": len(results.get("intl_companies", [])),
        "国内公司": len(results.get("cn_companies", [])),
        "社区热点": len(results.get("community", [])),
    }
    for k, v in summary.items():
        print(f"  • {k}: {v}")

    return filename


if __name__ == "__main__":
    main()
