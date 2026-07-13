
# -*- coding: utf-8 -*-
"""
生蚝AI知识库 - 自动联网抓取 + 可选本地资料增强版

功能：
1. 自动从公开搜索源检索牡蛎/生蚝相关网页
2. 自动抓取公开网页正文
3. 自动抓取 Crossref 公开论文题录/摘要
4. 自动抓取 Semantic Scholar 公开论文题录/摘要
5. 如 data/raw/ 下有 PDF、DOCX、TXT、MD、CSV、XLSX，也一并解析
6. 自动分段、去重、分类、摘要
7. 输出 knowledge_base.json，供 GitHub Pages 前端读取

说明：
- 不自动下载受版权限制的 PDF 全文
- 不抓取需要登录、验证码、付费的数据
- 主要保存公开网页正文、题录、摘要、链接
"""

import os
import re
import csv
import json
import time
import hashlib
import urllib.parse
from pathlib import Path
from datetime import datetime
from html import unescape

import requests
from bs4 import BeautifulSoup

RAW_DIR = Path("data/raw")
OUTPUT_FILE = Path("knowledge_base.json")

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

MAX_SEARCH_RESULTS_PER_QUERY = 8
MAX_WEB_PAGES_TOTAL = 60
REQUEST_SLEEP = 1.2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OysterKnowledgeBot/2.0; +https://github.com/)"
}

KEYWORDS = [
    "牡蛎 养殖 技术",
    "生蚝 养殖 技术",
    "太平洋牡蛎 种质 标准",
    "长牡蛎 种质 标准",
    "牡蛎 苗种 培育",
    "牡蛎 筏式 吊养",
    "牡蛎 滩涂 养殖",
    "牡蛎 三倍体 育种",
    "牡蛎 病害 防控",
    "牡蛎 夏季死亡",
    "牡蛎 专利 方法",
    "牡蛎 论文 摘要",
]

ENGLISH_KEYWORDS = [
    "Crassostrea gigas aquaculture",
    "Pacific oyster breeding",
    "triploid oyster breeding",
    "oyster seed production",
    "oyster disease control",
]

PREFERRED_DOMAINS = [
    "moa.gov.cn",
    "cnfm.com.cn",
    "ysfri.ac.cn",
    "qdio.ac.cn",
    "cafs.ac.cn",
    "std.samr.gov.cn",
    "samr.gov.cn",
    "cnipa.gov.cn",
    "patents.google.com",
    "xueshu.baidu.com",
    "scholar.google.com",
    "semanticscholar.org",
    "crossref.org",
    "fao.org",
]

SUPPORTED_SUFFIXES = {
    ".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx"
}

CATEGORY_RULES = {
    "种质标准": [
        "种质", "标准", "GB/T", "SC/T", "地方标准", "行业标准", "品种", "良种",
        "太平洋牡蛎", "长牡蛎", "香港牡蛎", "近江牡蛎", "种质资源"
    ],
    "养殖规程": [
        "养殖", "规程", "技术规范", "筏式", "吊养", "滩涂", "苗种", "育苗",
        "采苗", "附着基", "盐度", "温度", "密度", "投饵", "水质", "敌害"
    ],
    "专利文献": [
        "专利", "发明", "实用新型", "权利要求", "说明书", "申请号", "公开号",
        "一种", "装置", "方法", "系统", "patent"
    ],
    "学术论文": [
        "摘要", "关键词", "研究", "试验", "实验", "结果", "讨论", "参考文献",
        "DOI", "Journal", "Abstract", "article", "paper"
    ],
    "遗传育种": [
        "三倍体", "四倍体", "二倍体", "育种", "家系", "选育", "杂交", "遗传",
        "分子标记", "SNP", "微卫星", "基因组", "倍性", "triploid", "breeding"
    ],
    "病害防控": [
        "病害", "弧菌", "死亡", "夏季死亡", "寄生虫", "防控", "免疫", "抗病",
        "病原", "感染", "disease", "mortality", "Vibrio"
    ],
}


def safe_get(url, params=None, timeout=18):
    for i in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
            if resp.status_code == 200:
                if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                    resp.encoding = resp.apparent_encoding
                return resp
            print(f"  ⚠️ HTTP {resp.status_code}: {url}")
        except Exception as e:
            print(f"  ⚠️ 请求失败 第{i+1}次：{url}，原因：{e}")
        time.sleep(1.5)
    return None


def clean_text(text):
    if not text:
        return ""
    text = unescape(text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    text = re.sub(r"分享到.*", "", text)
    text = re.sub(r"责任编辑[:：].*", "", text)
    text = re.sub(r"打印本页.*", "", text)
    return text.strip()


def make_id(text):
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def classify_text(title, content):
    full_text = f"{title} {content}"
    scores = {}
    for category, words in CATEGORY_RULES.items():
        score = 0
        for word in words:
            if word.lower() in full_text.lower():
                score += 1
        scores[category] = score
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "综合资料"


def summarize_text(text, max_len=220):
    text = clean_text(text)
    if len(text) <= max_len:
        return text

    sentences = re.split(r"[。！？；\n.!?;]", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 12]

    keywords = [
        "目的", "方法", "结果", "结论", "规定", "要求", "适用于",
        "牡蛎", "生蚝", "太平洋牡蛎", "三倍体", "养殖", "育苗", "种质",
        "专利", "标准", "规程", "oyster", "aquaculture", "breeding"
    ]

    scored = []
    for s in sentences:
        score = sum(1 for kw in keywords if kw.lower() in s.lower())
        scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [s for score, s in scored[:3] if score > 0]

    if not selected:
        selected = sentences[:3]

    summary = "。".join(selected)
    return summary[:max_len]


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = clean_text(text)
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []
    current = ""

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue

        if len(current) + len(p) + 1 <= chunk_size:
            current += "\n" + p
        else:
            if current.strip():
                chunks.append(current.strip())

            if len(p) > chunk_size:
                start = 0
                while start < len(p):
                    end = start + chunk_size
                    chunks.append(p[start:end])
                    next_start = end - overlap
                    if next_start <= start:
                        next_start = end
                    start = next_start
            else:
                tail = current[-overlap:] if len(current) > overlap else current
                current = tail + "\n" + p

    if current.strip():
        chunks.append(current.strip())

    return chunks


def create_doc(title, content, source, url="", date="", file_name="", chunk_index=1):
    title = clean_text(title)[:180] or "未命名资料"
    content = clean_text(content)

    return {
        "id": make_id(f"{title}-{source}-{url}-{chunk_index}-{content[:80]}"),
        "title": title,
        "file_name": file_name,
        "category": classify_text(title, content),
        "source": source,
        "content": content,
        "summary": summarize_text(content),
        "date": date,
        "url": url,
        "chunk_index": chunk_index,
        "content_length": len(content)
    }


# ---------------------------------------------------------
# 搜索引擎：DuckDuckGo HTML
# ---------------------------------------------------------
def search_duckduckgo(query, max_results=MAX_SEARCH_RESULTS_PER_QUERY):
    print(f"🔎 DuckDuckGo 搜索：{query}")
    urls = []
    search_url = "https://duckduckgo.com/html/"
    resp = safe_get(search_url, params={"q": query})
    if not resp:
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.select("a.result__a")

    for a in links:
        href = a.get("href", "")
        if not href:
            continue

        real_url = href
        if "uddg=" in href:
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs:
                real_url = qs["uddg"][0]

        if real_url.startswith("http") and not is_bad_url(real_url):
            urls.append(real_url)

        if len(urls) >= max_results:
            break

    time.sleep(REQUEST_SLEEP)
    return urls


# ---------------------------------------------------------
# 搜索引擎：Bing 页面解析
# ---------------------------------------------------------
def search_bing(query, max_results=MAX_SEARCH_RESULTS_PER_QUERY):
    print(f"🔎 Bing 搜索：{query}")
    urls = []
    resp = safe_get("https://www.bing.com/search", params={"q": query})
    if not resp:
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for item in soup.select("li.b_algo h2 a"):
        href = item.get("href", "")
        if href.startswith("http") and not is_bad_url(href):
            urls.append(href)
        if len(urls) >= max_results:
            break

    time.sleep(REQUEST_SLEEP)
    return urls


def is_bad_url(url):
    bad_suffixes = [
        ".jpg", ".jpeg", ".png", ".gif", ".zip", ".rar", ".mp4", ".mp3"
    ]
    lower = url.lower()
    if any(lower.endswith(s) for s in bad_suffixes):
        return True
    if "javascript:" in lower:
        return True
    if "login" in lower or "passport" in lower:
        return True
    return False


def collect_web_urls():
    print("🌐 开始自动联网检索公开网页...")
    all_urls = []

    for kw in KEYWORDS:
        query = kw + " site:moa.gov.cn OR site:cnfm.com.cn OR site:cafs.ac.cn OR site:qdio.ac.cn"
        all_urls.extend(search_duckduckgo(query))
        all_urls.extend(search_bing(query))

    for kw in KEYWORDS:
        all_urls.extend(search_duckduckgo(kw))
        all_urls.extend(search_bing(kw))

    # 去重
    seen = set()
    unique = []
    for url in all_urls:
        normalized = url.split("#")[0]
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)

    # 优先政府、科研、专利域名
    def priority(u):
        score = 0
        for domain in PREFERRED_DOMAINS:
            if domain in u:
                score += 10
        if "牡蛎" in urllib.parse.unquote(u) or "生蚝" in urllib.parse.unquote(u):
            score += 5
        return score

    unique.sort(key=priority, reverse=True)
    selected = unique[:MAX_WEB_PAGES_TOTAL]
    print(f"  ✅ 收集到候选网页 {len(unique)} 个，选取 {len(selected)} 个")
    return selected


# ---------------------------------------------------------
# 网页正文抽取
# ---------------------------------------------------------
def extract_page_content(url):
    resp = safe_get(url)
    if not resp:
        return None

    content_type = resp.headers.get("Content-Type", "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)

    candidates = []

    selectors = [
        "article",
        ".article",
        ".content",
        ".main",
        ".TRS_Editor",
        ".Custom_UnionStyle",
        "#content",
        "#main",
        ".detail",
        ".news_content",
    ]

    for sel in selectors:
        for node in soup.select(sel):
            text = node.get_text("\n", strip=True)
            if len(text) > 300:
                candidates.append(text)

    if not candidates:
        body = soup.body
        if body:
            candidates.append(body.get_text("\n", strip=True))

    if not candidates:
        return None

    text = max(candidates, key=len)
    text = clean_text(text)

    if len(text) < 180:
        return None

    # 过滤明显无关页面
    relevance_terms = ["牡蛎", "生蚝", "oyster", "Crassostrea", "贝类", "水产", "养殖"]
    if not any(t.lower() in (title + text).lower() for t in relevance_terms):
        return None

    date = extract_date(text + " " + url)

    return {
        "title": title[:180] or url,
        "content": text,
        "url": url,
        "date": date,
        "source": get_domain(url)
    }


def extract_date(text):
    patterns = [
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{4}/\d{1,2}/\d{1,2}",
        r"\d{4}年\d{1,2}月\d{1,2}日",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return ""


def get_domain(url):
    try:
        return urllib.parse.urlparse(url).netloc
    except Exception:
        return url


def crawl_public_web_pages():
    urls = collect_web_urls()
    docs = []

    print("📄 开始抓取公开网页正文...")
    for idx, url in enumerate(urls, start=1):
        print(f"  [{idx}/{len(urls)}] {url}")
        item = extract_page_content(url)
        if not item:
            continue

        chunks = chunk_text(item["content"])
        for i, chunk in enumerate(chunks, start=1):
            docs.append(create_doc(
                title=item["title"] if len(chunks) == 1 else f"{item['title']} - 片段{i}",
                content=chunk,
                source=f"公开网页：{item['source']}",
                url=item["url"],
                date=item["date"],
                chunk_index=i
            ))

        time.sleep(REQUEST_SLEEP)

    print(f"  ✅ 公开网页生成知识片段 {len(docs)} 条")
    return docs


# ---------------------------------------------------------
# Crossref 公开论文题录/摘要
# ---------------------------------------------------------
def crawl_crossref():
    print("📚 抓取 Crossref 公开论文题录/摘要...")
    docs = []

    queries = ENGLISH_KEYWORDS + [
        "oyster aquaculture China",
        "Crassostrea gigas triploid",
        "oyster breeding disease mortality"
    ]

    for q in queries:
        url = "https://api.crossref.org/works"
        params = {
            "query": q,
            "rows": 8,
            "select": "title,abstract,DOI,published-print,published-online,container-title,URL"
        }

        resp = safe_get(url, params=params)
        if not resp:
            continue

        try:
            data = resp.json()
            items = data.get("message", {}).get("items", [])
        except Exception:
            items = []

        for item in items:
            title_list = item.get("title") or []
            title = title_list[0] if title_list else q

            abstract = item.get("abstract", "")
            abstract = re.sub(r"<[^>]+>", "", abstract)
            abstract = clean_text(abstract)

            container = ""
            if item.get("container-title"):
                container = item["container-title"][0]

            doi = item.get("DOI", "")
            item_url = item.get("URL", "")

            if not abstract:
                abstract = f"题名：{title}。期刊/来源：{container}。DOI：{doi}。该记录来自 Crossref 开放题录，未提供摘要全文。"

            if not is_relevant_oyster(title + " " + abstract):
                continue

            content = f"标题：{title}\n期刊/来源：{container}\nDOI：{doi}\n摘要/题录：{abstract}"

            docs.append(create_doc(
                title=title,
                content=content,
                source="Crossref公开论文题录",
                url=item_url,
                date="",
                chunk_index=1
            ))

        time.sleep(REQUEST_SLEEP)

    print(f"  ✅ Crossref 生成知识片段 {len(docs)} 条")
    return docs


# ---------------------------------------------------------
# Semantic Scholar 公开论文题录/摘要
# ---------------------------------------------------------
def crawl_semantic_scholar():
    print("📚 抓取 Semantic Scholar 公开论文题录/摘要...")
    docs = []

    queries = ENGLISH_KEYWORDS + [
        "Crassostrea gigas oyster aquaculture",
        "triploid oyster Crassostrea gigas",
        "Pacific oyster disease mortality"
    ]

    for q in queries:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": q,
            "limit": 8,
            "fields": "title,abstract,year,authors,url,venue"
        }

        resp = safe_get(url, params=params)
        if not resp:
            continue

        try:
            data = resp.json()
            items = data.get("data", [])
        except Exception:
            items = []

        for item in items:
            title = item.get("title", q)
            abstract = clean_text(item.get("abstract", "") or "")
            year = str(item.get("year") or "")
            venue = item.get("venue") or ""
            item_url = item.get("url") or ""

            authors = item.get("authors") or []
            author_names = ", ".join([a.get("name", "") for a in authors[:5]])

            if not abstract:
                abstract = f"题名：{title}。年份：{year}。来源：{venue}。作者：{author_names}。该记录来自 Semantic Scholar 开放题录，未提供摘要全文。"

            if not is_relevant_oyster(title + " " + abstract):
                continue

            content = f"标题：{title}\n作者：{author_names}\n年份：{year}\n来源：{venue}\n摘要/题录：{abstract}"

            docs.append(create_doc(
                title=title,
                content=content,
                source="Semantic Scholar公开论文题录",
                url=item_url,
                date=year,
                chunk_index=1
            ))

        time.sleep(REQUEST_SLEEP)

    print(f"  ✅ Semantic Scholar 生成知识片段 {len(docs)} 条")
    return docs


def is_relevant_oyster(text):
    terms = [
        "oyster", "Crassostrea", "牡蛎", "生蚝", "Pacific oyster",
        "triploid oyster", "shellfish"
    ]
    low = text.lower()
    return any(t.lower() in low for t in terms)


# ---------------------------------------------------------
# 可选：解析 data/raw
# ---------------------------------------------------------
def read_pdf(path):
    items = []
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                text = clean_text(text)
                if text:
                    items.append((text, f"第{i}页"))
    except Exception as e:
        print(f"  ⚠️ PDF解析失败：{path.name}，原因：{e}")
    return items


def read_docx(path):
    items = []
    try:
        import docx
        doc = docx.Document(str(path))
        paragraphs = []
        for p in doc.paragraphs:
            if p.text.strip():
                paragraphs.append(p.text.strip())

        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)

        text = clean_text("\n".join(paragraphs))
        if text:
            items.append((text, "全文"))
    except Exception as e:
        print(f"  ⚠️ DOCX解析失败：{path.name}，原因：{e}")
    return items


def read_txt_md(path):
    items = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        text = clean_text(text)
        if text:
            items.append((text, "全文"))
    except Exception as e:
        print(f"  ⚠️ 文本解析失败：{path.name}，原因：{e}")
    return items


def read_csv_file(path):
    items = []
    try:
        rows_text = []
        with open(path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            for idx, row in enumerate(reader, start=1):
                row_text = " | ".join([cell.strip() for cell in row if cell.strip()])
                if row_text:
                    rows_text.append(f"第{idx}行：{row_text}")
        text = clean_text("\n".join(rows_text))
        if text:
            items.append((text, "CSV全文"))
    except Exception as e:
        print(f"  ⚠️ CSV解析失败：{path.name}，原因：{e}")
    return items


def read_xlsx_file(path):
    items = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True)
        for sheet in wb.worksheets:
            rows_text = []
            for idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if values:
                    rows_text.append(f"第{idx}行：{' | '.join(values)}")
            text = clean_text("\n".join(rows_text))
            if text:
                items.append((text, f"工作表：{sheet.title}"))
    except Exception as e:
        print(f"  ⚠️ Excel解析失败：{path.name}，原因：{e}")
    return items


def read_file(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix == ".docx":
        return read_docx(path)
    if suffix in [".txt", ".md"]:
        return read_txt_md(path)
    if suffix == ".csv":
        return read_csv_file(path)
    if suffix == ".xlsx":
        return read_xlsx_file(path)
    return []


def build_docs_from_raw_files():
    print("📁 检查 data/raw 本地资料...")
    docs = []

    if not RAW_DIR.exists():
        print("  ℹ️ 未发现 data/raw，跳过本地资料解析")
        return docs

    files = [
        p for p in RAW_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    ]

    if not files:
        print("  ℹ️ data/raw 没有可解析文件")
        return docs

    print(f"  ✅ 发现本地资料 {len(files)} 个")

    for path in files:
        print(f"  📄 解析：{path}")
        items = read_file(path)

        for text, locator in items:
            chunks = chunk_text(text)
            for i, chunk in enumerate(chunks, start=1):
                title = f"{path.stem} - 片段{i}"
                docs.append(create_doc(
                    title=title,
                    content=chunk,
                    source=f"本地资料：{path.as_posix()} {locator}",
                    url="",
                    file_name=path.name,
                    chunk_index=i
                ))

    print(f"  ✅ 本地资料生成知识片段 {len(docs)} 条")
    return docs


# ---------------------------------------------------------
# 内置基础知识
# ---------------------------------------------------------
def builtin_base_docs():
    base = [
        {
            "title": "GB/T 24860-2010 太平洋牡蛎",
            "category_hint": "种质标准",
            "source": "内置基础知识",
            "content": "GB/T 24860-2010规定了太平洋牡蛎的种质要求，包括分类地位、主要形态构造、生长与繁殖特性、遗传学特征、检测方法和判定规则。该标准适用于太平洋牡蛎原种和良种的种质检测与鉴定。"
        },
        {
            "title": "SC/T 2071-2015 长牡蛎",
            "category_hint": "种质标准",
            "source": "内置基础知识",
            "content": "SC/T 2071-2015规定了长牡蛎的种质技术要求，包括外部形态、可量性状、可数性状、生长性能、繁殖性能及遗传多样性检测要求，可用于长牡蛎种质资源保存和良种选育评价。"
        },
        {
            "title": "牡蛎筏式吊养技术要点",
            "category_hint": "养殖规程",
            "source": "内置基础知识",
            "content": "牡蛎筏式吊养应选择水流通畅、饵料生物丰富、风浪适中、污染较少的海区。养殖过程中应合理控制吊养密度，定期清除附着生物，依据水温、盐度和饵料条件调整养殖水层。"
        },
        {
            "title": "牡蛎苗种培育水质管理",
            "category_hint": "养殖规程",
            "source": "内置基础知识",
            "content": "牡蛎幼虫培育需保持稳定水质，适宜水温一般为24至28摄氏度，盐度多控制在20至30之间。培育期间应合理投喂单胞藻，及时换水并监测氨氮、溶解氧和pH。"
        },
        {
            "title": "三倍体牡蛎育种技术",
            "category_hint": "遗传育种",
            "source": "内置基础知识",
            "content": "三倍体牡蛎可通过化学诱导、物理休克或四倍体与二倍体杂交获得。三倍体牡蛎通常具有生长快、肥满度高、繁殖季品质稳定等特点，是牡蛎良种选育和规模化养殖的重要方向。"
        },
        {
            "title": "牡蛎夏季死亡与病害防控",
            "category_hint": "病害防控",
            "source": "内置基础知识",
            "content": "牡蛎夏季死亡通常与高温、低氧、病原感染、养殖密度过高和环境胁迫有关。防控措施包括降低养殖密度、优化养殖水层、加强水质监测、减少机械损伤并开展苗种健康检测。"
        },
    ]

    docs = []
    for idx, item in enumerate(base, start=1):
        doc = create_doc(
            title=item["title"],
            content=item["content"],
            source=item["source"],
            chunk_index=idx
        )
        doc["category"] = item["category_hint"]
        docs.append(doc)

    return docs


def deduplicate_docs(docs):
    seen = set()
    unique = []

    for doc in docs:
        title = doc.get("title", "")
        content = doc.get("content", "")
        url = doc.get("url", "")

        key = make_id((url or title) + content[:300])
        if key in seen:
            continue

        seen.add(key)
        unique.append(doc)

    return unique


def limit_docs(docs, max_docs=350):
    # 优先保留本地资料、政府/科研网页、较长内容
    def score(doc):
        s = 0
        src = doc.get("source", "")
        url = doc.get("url", "")

        if "本地资料" in src:
            s += 100
        for d in PREFERRED_DOMAINS:
            if d in url or d in src:
                s += 30
        if "Crossref" in src or "Semantic" in src:
            s += 15
        s += min(doc.get("content_length", 0) / 100, 20)
        return s

    docs.sort(key=score, reverse=True)
    return docs[:max_docs]


def main():
    print("=" * 70)
    print("🦪 生蚝AI知识库 - 自动联网抓取 + 可选本地资料构建")
    print(f"⏰ 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    docs = []

    # 1. 自动联网抓取公开网页
    try:
        docs.extend(crawl_public_web_pages())
    except Exception as e:
        print(f"⚠️ 公开网页抓取整体异常：{e}")

    # 2. 抓取开放论文题录/摘要
    try:
        docs.extend(crawl_crossref())
    except Exception as e:
        print(f"⚠️ Crossref 抓取异常：{e}")

    try:
        docs.extend(crawl_semantic_scholar())
    except Exception as e:
        print(f"⚠️ Semantic Scholar 抓取异常：{e}")

    # 3. 可选本地资料
    try:
        docs.extend(build_docs_from_raw_files())
    except Exception as e:
        print(f"⚠️ 本地资料解析异常：{e}")

    # 4. 内置基础知识兜底
    docs.extend(builtin_base_docs())

    # 5. 去重和限制体积
    docs = deduplicate_docs(docs)
    docs = limit_docs(docs, max_docs=350)

    category_count = {}
    source_count = {}

    for doc in docs:
        category = doc.get("category", "未分类")
        source = doc.get("source", "未知来源")
        category_count[category] = category_count.get(category, 0) + 1
        source_count[source] = source_count.get(source, 0) + 1

    output = {
        "name": "生蚝AI知识库",
        "version": "3.0-auto-web",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(docs),
        "categories": category_count,
        "sources": source_count,
        "documents": docs
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print(f"✅ 构建完成，共生成 {len(docs)} 条知识片段")
    print("📊 分类统计：")
    for k, v in category_count.items():
        print(f"  - {k}: {v}")
    print(f"📁 输出文件：{OUTPUT_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
