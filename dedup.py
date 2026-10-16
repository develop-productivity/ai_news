#!/usr/bin/python3
"""
简单去重/聚类模块 — 跨板块检测同一事件的多条报道并合并。

策略：
1. 跨所有板块收集全部条目
2. 用 SequenceMatcher 计算标题相似度
3. 相似度 > 0.6 的归为同一事件组
4. 每组保留分数最高的条目作为代表，记录其他来源
5. 被合并的条目从原板块中移除
"""

from difflib import SequenceMatcher
from typing import List, Dict, Any

SIMILARITY_THRESHOLD = 0.55


def _normalize_title(title: str) -> str:
    """归一化标题用于比较：去前缀、去标点、转小写。"""
    import re
    t = title.lower().strip()
    # 去掉常见前缀：板块名 · 标题
    t = re.sub(r'^[\w\s]+ · ', '', t)
    # 去掉标点
    t = re.sub(r'[，。、：；！？,.:;!?\'"“”‘’（）()\[\]【】]', ' ', t)
    # 压缩空格
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _similarity(a: str, b: str) -> float:
    """计算两个标题的相似度。"""
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    # 快速检查：包含关系
    if na in nb or nb in na:
        return 0.9
    return SequenceMatcher(None, na, nb).ratio()


def dedup_sections(sections: List[Dict[str, Any]]) -> tuple:
    """
    跨板块去重。

    返回 (sections, events)
    - sections: 去重后的板块（重复条目已移除）
    - events: 事件列表，每个事件包含代表条目和所有来源
    """
    # 收集所有条目及其位置
    all_items = []
    for sec_idx, sec in enumerate(sections):
        if sec.get("accent") == "hot":
            continue
        for item_idx, item in enumerate(sec.get("items", [])):
            all_items.append({
                "sec_idx": sec_idx,
                "item_idx": item_idx,
                "title": item.get("title", ""),
                "score": item.get("score", 0),
                "section_label": sec.get("label", ""),
                "item": item,
            })

    # 聚类：相似度高的归为一组
    groups = []  # 每组是 all_items 中的索引列表
    assigned = [False] * len(all_items)

    for i in range(len(all_items)):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, len(all_items)):
            if assigned[j]:
                continue
            # 和组内任一条目相似就加入
            for k in group:
                if _similarity(all_items[i]["title"], all_items[j]["title"]) >= SIMILARITY_THRESHOLD:
                    group.append(j)
                    assigned[j] = True
                    break
        groups.append(group)

    # 构建事件列表
    events = []
    items_to_remove = set()  # (sec_idx, item_idx) 要从板块中移除的

    for group in groups:
        if len(group) <= 1:
            continue

        # 按分数排序，保留最高的
        group_items = [all_items[i] for i in group]
        group_items.sort(key=lambda x: x["score"], reverse=True)
        rep = group_items[0]
        sources = [{
            "id": gi["item"].get("id", ""),
            "title": gi["title"],
            "section": gi["section_label"],
            "score": gi["score"],
            "source": gi["item"].get("source", ""),
            "url": gi["item"].get("url", ""),
        } for gi in group_items]

        # 保留代表条目，移除其他；代表条目记录其他报道，前端详情里可逐条跳转
        for gi in group_items[1:]:
            items_to_remove.add((gi["sec_idx"], gi["item_idx"]))
        rep["item"]["related"] = sources[1:]

        events.append({
            "id": rep["item"].get("id", ""),
            "title": rep["title"],
            "url": rep["item"].get("url", ""),
            "score": rep["score"],
            "section": rep["section_label"],
            "source_count": len(group),
            "sources": sources,
        })

    # 从板块中移除重复条目
    for sec_idx, sec in enumerate(sections):
        if sec.get("accent") == "hot":
            continue
        sec["items"] = [
            item for item_idx, item in enumerate(sec.get("items", []))
            if (sec_idx, item_idx) not in items_to_remove
        ]

    # 按来源数排序事件
    events.sort(key=lambda x: (x["source_count"], x["score"]), reverse=True)

    removed = len(items_to_remove)
    if removed > 0:
        print(f"  [去重] 合并 {removed} 条重复，生成 {len(events)} 个事件组")

    return sections, events


def add_events_to_data(data: dict) -> dict:
    """在 data 中添加 events 字段，并在板块中移除重复条目。"""
    sections = data.get("sections", [])
    sections, events = dedup_sections(sections)
    data["sections"] = sections
    if events:
        data["events"] = events
    return data
