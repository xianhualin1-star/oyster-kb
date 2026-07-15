
# -*- coding: utf-8 -*-
"""
生蚝 AI 知识库：每日增量构建脚本

- 不包含任何内置基础知识
- 保留旧 knowledge_base.json 中的历史资料
- 每次只追加新检索到且不重复的资料
- 使用 SerpAPI 获取公开检索结果的标题、摘要片段和 URL
- 不绕过知网、谷歌学术、万方、维普的登录、验证码或付费墙
"""

import os
import re
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import requests

OUTPUT = Path("knowledge_base.json")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()

QUERIES = [
    "牡蛎 种质 标准",
    "太平洋牡蛎 种质资源",
    "长牡蛎 养殖技术",
    "牡蛎 良种选育 三倍体",
    "牡蛎 人工育苗 苗种繁育",
    "牡蛎 筏式吊养 养殖规程",
    "牡蛎 病害防控 夏季死亡 弧菌",
    "牡蛎 国家标准 行业标准 地方标准",
    "牡蛎 专利 养殖 方法",
    "牡蛎 论文 摘要",
]

SCHOLAR_QUERIES = [
    "牡蛎 种质资源 论文",
    "太平洋牡蛎 三倍体 育种 论文",
    "牡蛎 人工育苗 论文",
    "牡蛎 病害防控 论文",
    "Crassostrea gigas aquaculture breeding",
]

CATEGORY_RULES = {
    "种质标准": ["种质", "标准", "GB/", "SC/", "DB", "品种", "良种", "种质资源"],
    "养殖规程": ["养殖", "规程", "育苗", "苗种", "筏式", "吊养", "滩涂", "水质"],
    "遗传育种": ["三倍体", "四倍体", "育种", "遗传", "基因", "杂交", "选育"],
    "病害防控": ["病害", "弧菌", "死亡", "病原", "防控", "免疫"],
    "专利文献": ["专利", "申请号", "公开号", "权利要求", "发明"],
    "学术论文": ["论文", "摘要", "期刊", "研究", "article", "abstract", "journal"],
}


def clean(value):
    value = str(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def make_id(title, url, content):
    raw = f"{title}|{url}|{content[:300]}".lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def domain(url):
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def classify(title, text):
    full = f"{title} {text}".lower()
    best, score = "综合资料", 0
    for category, words in CATEGORY_RULES.items():
        current = sum(1 for word in words if word.lower() in full)
        if current > score:
            best, score = category, current
    return best


def read_old_kb():
    if not OUTPUT.exists():
        return [], {}
    try:
        with open(OUTPUT, "r", encoding="utf-8") as f:
            data = json.load(f)
        docs = data.get("documents", [])
        return docs, data
    except Exception:
        return [], {}


def serpapi(params):
    if not SERPAPI_KEY:
        return None

    params["api_key"] = SERPAPI_KEY
    try:
        r = requests.get("https://serpapi.com/search.json", params=params, timeout=25)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("SerpAPI 请求失败：", e)
        return None


def create_doc(title, snippet, url, source, date=""):
    title = clean(title)[:250]
    snippet = clean(snippet)
    url = clean(url)

    content = f"标题：{title}\n来源：{source}\n摘要/检索片段：{snippet}\nURL：{url}"
    return {
        "id": make_id(title, url, snippet),
        "title": title,
        "category": classify(title, snippet),
        "source": source,
        "source_type": "search_result",
        "has_url": bool(url.startswith("http")),
        "url": url,
        "domain": domain(url),
        "date": clean(date),
        "content": content,
        "summary": snippet[:500],
        "content_length": len(content),
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def google_search_docs():
    docs = []

    for query in QUERIES:
        print("Google 搜索：", query)
        data = serpapi({
            "engine": "google",
            "q": query,
            "hl": "zh-cn",
            "num": 10,
        })
        if not data:
            continue

        for item in data.get("organic_results", []):
            title = item.get("title", "")
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            if title and link and snippet:
                docs.append(create_doc(
                    title, snippet, link,
                    source=f"SerpAPI Google公开检索：{domain(link)}"
                ))
        time.sleep(1)

    return docs


def scholar_docs():
    docs = []

    for query in SCHOLAR_QUERIES:
        print("Google Scholar 搜索：", query)
        data = serpapi({
            "engine": "google_scholar",
            "q": query,
            "hl": "zh-cn",
            "num": 10,
        })
        if not data:
            continue

        for item in data.get("organic_results", []):
            title = item.get("title", "")
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            publication = item.get("publication_info", {}).get("summary", "")
            combined = clean(f"{publication} {snippet}")

            if title and link:
                docs.append(create_doc(
                    title, combined, link,
                    source="SerpAPI Google Scholar公开题录/摘要"
                ))
        time.sleep(1)

    return docs


def merge_incrementally(old_docs, new_docs):
    seen = set()
    merged = []

    for doc in old_docs:
        key = (
            doc.get("url", "").strip().lower()
            or doc.get("id", "")
            or make_id(doc.get("title", ""), "", doc.get("content", ""))
        )
        if key not in seen:
            seen.add(key)
            merged.append(doc)

    added = 0
    for doc in new_docs:
        key = doc.get("url", "").strip().lower() or doc["id"]
        if key not in seen:
            seen.add(key)
            merged.append(doc)
            added += 1

    return merged, added


def main():
    old_docs, old_meta = read_old_kb()
    print(f"历史资料：{len(old_docs)} 条")

    if not SERPAPI_KEY:
        print("未设置 SERPAPI_KEY：保留旧文献库，不新增联网资料。")
        new_docs = []
    else:
        new_docs = google_search_docs() + scholar_docs()

    merged, newly_added = merge_incrementally(old_docs, new_docs)

    categories = {}
    sources = {}
    for doc in merged:
        categories[doc.get("category", "综合资料")] = categories.get(doc.get("category", "综合资料"), 0) + 1
        sources[doc.get("source", "未知来源")] = sources.get(doc.get("source", "未知来源"), 0) + 1

    data = {
        "name": "生蚝AI知识库",
        "version": "5.0-incremental-no-builtin",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(merged),
        "newly_added": newly_added,
        "url_count": sum(1 for d in merged if d.get("url")),
        "categories": categories,
        "sources": sources,
        "documents": merged,
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"本次候选：{len(new_docs)} 条")
    print(f"本次新增：{newly_added} 条")
    print(f"累计资料：{len(merged)} 条")


if __name__ == "__main__":
    main()
