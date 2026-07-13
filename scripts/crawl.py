
# -*- coding: utf-8 -*-
"""
生蚝AI知识库 - 增强版自动构建脚本

功能：
1. 读取 data/raw/ 下的 PDF、DOCX、TXT、MD、CSV、XLSX 文件
2. 自动文本清洗
3. 自动分段 chunk
4. 自动分类
5. 自动生成摘要
6. 保留来源文件名、页码/行号等信息
7. 合并少量内置基础知识
8. 输出 knowledge_base.json，供前端 index.html 使用

推荐目录：
data/raw/牡蛎种质标准.pdf
data/raw/牡蛎养殖规程.docx
data/raw/三倍体牡蛎论文.pdf
data/raw/牡蛎专利说明书.txt
"""

import os
import re
import csv
import json
import hashlib
from datetime import datetime
from pathlib import Path

RAW_DIR = Path("data/raw")
OUTPUT_FILE = Path("knowledge_base.json")

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".xlsx",
}

CATEGORY_RULES = {
    "种质标准": [
        "种质", "标准", "GB/T", "SC/T", "地方标准", "行业标准", "品种", "良种",
        "太平洋牡蛎", "长牡蛎", "香港牡蛎", "近江牡蛎", "种质资源"
    ],
    "养殖规程": [
        "养殖", "规程", "技术规范", "筏式", "吊养", "滩涂", "苗种", "育苗",
        "采苗", "附着基", "盐度", "温度", "密度", "投饵", "水质", "病害", "敌害"
    ],
    "专利文献": [
        "专利", "发明", "实用新型", "权利要求", "说明书", "申请号", "公开号",
        "一种", "装置", "方法", "系统"
    ],
    "学术论文": [
        "摘要", "关键词", "研究", "试验", "实验", "结果", "讨论", "参考文献",
        "DOI", "Journal", "基金项目"
    ],
    "遗传育种": [
        "三倍体", "四倍体", "二倍体", "育种", "家系", "选育", "杂交", "遗传",
        "分子标记", "SNP", "微卫星", "基因组", "倍性"
    ],
    "病害防控": [
        "病害", "弧菌", "死亡", "夏季死亡", "寄生虫", "防控", "免疫", "抗病",
        "病原", "感染"
    ],
}


def clean_text(text: str) -> str:
    """清洗文本"""
    if not text:
        return ""
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"第\s*\d+\s*页\s*共\s*\d+\s*页", "", text)
    return text.strip()


def make_id(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def classify_text(title: str, content: str) -> str:
    """根据标题和正文自动分类"""
    full_text = f"{title} {content}"
    scores = {}
    for category, words in CATEGORY_RULES.items():
        score = 0
        for word in words:
            if word.lower() in full_text.lower():
                score += 1
        scores[category] = score

    best_category = max(scores, key=scores.get)
    if scores[best_category] == 0:
        return "综合资料"
    return best_category


def summarize_text(text: str, max_len: int = 180) -> str:
    """简单抽取式摘要"""
    text = clean_text(text)
    if len(text) <= max_len:
        return text

    sentences = re.split(r"[。！？；\n]", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    important_keywords = [
        "目的", "方法", "结果", "结论", "规定", "要求", "适用于",
        "牡蛎", "生蚝", "太平洋牡蛎", "三倍体", "养殖", "育苗", "种质",
        "专利", "标准", "规程"
    ]

    scored = []
    for s in sentences:
        score = sum(1 for kw in important_keywords if kw in s)
        scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [s for _, s in scored[:3]]

    summary = "。".join(selected)
    if not summary:
        summary = text[:max_len]
    return summary[:max_len]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """按长度分段，保留重叠，提升检索命中率"""
    text = clean_text(text)
    if not text:
        return []

    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []
    current = ""

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue

        if len(current) + len(p) <= chunk_size:
            current += "\n" + p
        else:
            if current.strip():
                chunks.append(current.strip())

            if len(p) > chunk_size:
                start = 0
                while start < len(p):
                    end = start + chunk_size
                    chunks.append(p[start:end])
                    start = end - overlap
                    if start < 0:
                        start = 0
                    if start >= len(p):
                        break
                current = ""
            else:
                tail = current[-overlap:] if len(current) > overlap else current
                current = tail + "\n" + p

    if current.strip():
        chunks.append(current.strip())

    return chunks


def read_pdf(path: Path):
    """读取 PDF，返回 [(text, page_no)]"""
    items = []
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                text = clean_text(text)
                if text:
                    items.append((text, i))
    except Exception as e:
        print(f"  ⚠️ PDF解析失败：{path.name}，原因：{e}")
    return items


def read_docx(path: Path):
    """读取 DOCX"""
    items = []
    try:
        import docx
        doc = docx.Document(str(path))
        paragraphs = []
        for p in doc.paragraphs:
            if p.text.strip():
                paragraphs.append(p.text.strip())

        # 读取表格内容
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)

        text = clean_text("\n".join(paragraphs))
        if text:
            items.append((text, None))
    except Exception as e:
        print(f"  ⚠️ DOCX解析失败：{path.name}，原因：{e}")
    return items


def read_txt_md(path: Path):
    """读取 TXT / MD"""
    items = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        text = clean_text(text)
        if text:
            items.append((text, None))
    except Exception as e:
        print(f"  ⚠️ 文本解析失败：{path.name}，原因：{e}")
    return items


def read_csv_file(path: Path):
    """读取 CSV"""
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
            items.append((text, None))
    except Exception as e:
        print(f"  ⚠️ CSV解析失败：{path.name}，原因：{e}")
    return items


def read_xlsx_file(path: Path):
    """读取 Excel"""
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
                items.append((text, sheet.title))
    except Exception as e:
        print(f"  ⚠️ Excel解析失败：{path.name}，原因：{e}")
    return items


def read_file(path: Path):
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
    print("📁 正在读取 data/raw 目录资料...")
    docs = []

    if not RAW_DIR.exists():
        print("  ⚠️ 未发现 data/raw 目录，将只使用内置基础知识")
        return docs

    files = [
        p for p in RAW_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    ]

    if not files:
        print("  ⚠️ data/raw 目录没有可解析文件")
        return docs

    print(f"  ✅ 发现 {len(files)} 个文件")

    for path in files:
        print(f"  📄 解析：{path}")
        file_items = read_file(path)

        for text, locator in file_items:
            chunks = chunk_text(text)

            for idx, chunk in enumerate(chunks, start=1):
                title = path.stem
                category = classify_text(title, chunk)
                summary = summarize_text(chunk)

                if isinstance(locator, int):
                    source_detail = f"{path.as_posix()} 第{locator}页"
                elif isinstance(locator, str):
                    source_detail = f"{path.as_posix()} 工作表：{locator}"
                else:
                    source_detail = path.as_posix()

                doc = {
                    "id": make_id(f"{path.as_posix()}-{locator}-{idx}-{chunk[:50]}"),
                    "title": f"{title} - 片段{idx}",
                    "file_name": path.name,
                    "category": category,
                    "source": source_detail,
                    "content": chunk,
                    "summary": summary,
                    "date": "",
                    "url": "",
                    "chunk_index": idx,
                    "content_length": len(chunk)
                }
                docs.append(doc)

    print(f"  ✅ 本地资料生成知识片段 {len(docs)} 条")
    return docs


def builtin_base_docs():
    """内置基础知识，避免首次为空"""
    base = [
        {
            "title": "GB/T 24860-2010 太平洋牡蛎",
            "category": "种质标准",
            "source": "国家标准",
            "content": "GB/T 24860-2010规定了太平洋牡蛎的种质要求，包括分类地位、主要形态构造、生长与繁殖特性、遗传学特征、检测方法和判定规则。该标准适用于太平洋牡蛎原种和良种的种质检测与鉴定。",
        },
        {
            "title": "SC/T 2071-2015 长牡蛎",
            "category": "种质标准",
            "source": "水产行业标准",
            "content": "SC/T 2071-2015规定了长牡蛎的种质技术要求，包括外部形态、可量性状、可数性状、生长性能、繁殖性能及遗传多样性检测要求，可用于长牡蛎种质资源保存和良种选育评价。",
        },
        {
            "title": "牡蛎筏式吊养技术要点",
            "category": "养殖规程",
            "source": "技术资料",
            "content": "牡蛎筏式吊养应选择水流通畅、饵料生物丰富、风浪适中、污染较少的海区。养殖过程中应合理控制吊养密度，定期清除附着生物，依据水温、盐度和饵料条件调整养殖水层。",
        },
        {
            "title": "牡蛎苗种培育水质管理",
            "category": "养殖规程",
            "source": "技术资料",
            "content": "牡蛎幼虫培育需保持稳定水质，适宜水温一般为24至28摄氏度，盐度多控制在20至30之间。培育期间应合理投喂单胞藻，及时换水并监测氨氮、溶解氧和pH。",
        },
        {
            "title": "三倍体牡蛎育种技术",
            "category": "遗传育种",
            "source": "技术资料",
            "content": "三倍体牡蛎可通过化学诱导、物理休克或四倍体与二倍体杂交获得。三倍体牡蛎通常具有生长快、肥满度高、繁殖季品质稳定等特点，是牡蛎良种选育和规模化养殖的重要方向。",
        },
        {
            "title": "牡蛎夏季死亡与病害防控",
            "category": "病害防控",
            "source": "技术资料",
            "content": "牡蛎夏季死亡通常与高温、低氧、病原感染、养殖密度过高和环境胁迫有关。防控措施包括降低养殖密度、优化养殖水层、加强水质监测、减少机械损伤并开展苗种健康检测。",
        },
    ]

    docs = []
    for idx, item in enumerate(base, start=1):
        content = item["content"]
        docs.append({
            "id": make_id(item["title"] + content),
            "title": item["title"],
            "file_name": "",
            "category": item["category"],
            "source": item["source"],
            "content": content,
            "summary": summarize_text(content),
            "date": "",
            "url": "",
            "chunk_index": idx,
            "content_length": len(content)
        })
    return docs


def deduplicate_docs(docs):
    seen = set()
    unique = []
    for doc in docs:
        key = make_id(doc.get("title", "") + doc.get("content", "")[:300])
        if key not in seen:
            seen.add(key)
            unique.append(doc)
    return unique


def main():
    print("=" * 60)
    print("🦪 生蚝AI知识库 - 增强版构建开始")
    print(f"⏰ 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    docs = []
    docs.extend(build_docs_from_raw_files())
    docs.extend(builtin_base_docs())

    docs = deduplicate_docs(docs)

    category_count = {}
    for doc in docs:
        category = doc.get("category", "未分类")
        category_count[category] = category_count.get(category, 0) + 1

    output = {
        "name": "生蚝AI知识库",
        "version": "2.0",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(docs),
        "categories": category_count,
        "documents": docs
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"✅ 构建完成，共生成 {len(docs)} 条知识片段")
    print("📊 分类统计：")
    for k, v in category_count.items():
        print(f"  - {k}: {v}")
    print(f"📁 输出文件：{OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
