import html
import io
import json
import os
import re
import zipfile
from typing import Dict, List


_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_XML_NAMESPACE_PATTERN = re.compile(r"\{[^}]+\}")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_PDF_TEXT_PATTERN = re.compile(rb"\(([^()]{1,240})\)\s*Tj")
_PDF_ARRAY_TEXT_PATTERN = re.compile(rb"\[(.*?)\]\s*TJ", re.DOTALL)
_PDF_ARRAY_SEGMENT_PATTERN = re.compile(rb"\(([^()]*)\)")
_PRINTABLE_STRING_PATTERN = re.compile(rb"[\x20-\x7e]{4,}")
_METADATA_ONLY_PREFIXES = ("文件名:", "MIME:", "大小:", "类型:", "来源:")
_TEXT_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".csv",
    ".tsv",
    ".log",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".html",
    ".htm",
    ".xml",
    ".yaml",
    ".yml",
}


_KNOWLEDGE_TITLE_BLOCKLIST = {
    "文件名", "文件", "大小", "类型", "来源", "图片", "截图", "屏幕截图", "屏幕快照",
    "文档", "音频", "视频", "链接", "笔记", "内容", "摘要", "说明", "备注", "预览",
    "mime", "image", "photo", "video", "audio", "document", "file", "screenshot",
    "png", "jpg", "jpeg", "webp", "gif", "bmp", "pdf", "txt", "md", "docx", "xlsx", "pptx",
}


def is_noise_knowledge_title(title) -> bool:
    """过滤“文件名/大小/类型/屏幕截图”这类文件元信息，它们不是知识点。"""
    text = str(title or "").strip().strip("：: ").lower()
    if not text:
        return True
    if text in _KNOWLEDGE_TITLE_BLOCKLIST:
        return True
    if text.startswith(("文件名", "文件：", "类型", "大小", "来源", "mime", "mime:")):
        return True
    if re.search(r"\.(png|jpe?g|webp|gif|bmp|pdf|docx?|xlsx?|pptx?|txt|md)$", text):
        return True
    if re.match(r"^(屏幕截图|截图|屏幕快照|screenshot|screen shot|img[_-]?\d|image|photo|scan)", text):
        return True
    return False


def looks_like_binary_text(text) -> bool:
    """判断一段文本是否是二进制文件被强行解码后的乱码。

    图片、压缩包等文件按文本解码会产生大量控制字符，这类内容不应进入
    知识点抽取与知识库，否则会污染主题、图谱和题库。
    """
    sample = str(text or "")[:4000]
    if not sample:
        return False
    if "\x00" in sample:
        return True
    abnormal = 0
    for char in sample:
        code = ord(char)
        if code < 32 and char not in "\n\r\t":
            abnormal += 1
        elif 0xE000 <= code <= 0xF8FF:
            abnormal += 1
    return (abnormal / max(1, len(sample))) > 0.02


def is_git_lfs_pointer_bytes(raw_bytes: bytes) -> bool:
    return bool(raw_bytes and raw_bytes.startswith(_LFS_POINTER_PREFIX))


def is_git_lfs_pointer_file(path: str) -> bool:
    target = str(path or "").strip()
    if not target or not os.path.exists(target) or not os.path.isfile(target):
        return False
    try:
        with open(target, "rb") as file_obj:
            return is_git_lfs_pointer_bytes(file_obj.read(256))
    except Exception:
        return False


def normalize_text_preview(text: str, limit: int = 220) -> str:
    compact = _WHITESPACE_PATTERN.sub(" ", str(text or "")).strip()
    if len(compact) <= int(limit or 220):
        return compact
    return compact[: max(1, int(limit or 220))] + "..."


def _normalize_whitespace(text: str) -> str:
    lines = []
    for raw_line in str(text or "").replace("\r", "\n").split("\n"):
        cleaned = _WHITESPACE_PATTERN.sub(" ", raw_line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines).strip()


def _decode_text_bytes(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""

    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1"):
        try:
            text = raw_bytes.decode(encoding)
            normalized = _normalize_whitespace(text)
            if normalized:
                return normalized
        except Exception:
            continue
    return ""


def _strip_html_tags(raw_html: str) -> str:
    text = re.sub(r"<(script|style)\b[\s\S]*?</\1>", " ", str(raw_html or ""), flags=re.IGNORECASE)
    text = _HTML_TAG_PATTERN.sub(" ", text)
    text = html.unescape(text)
    return _normalize_whitespace(text)


def _extract_docx_text(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""
    try:
        from xml.etree import ElementTree

        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
            document_xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(document_xml)
        fragments = []
        for element in root.iter():
            tag = _XML_NAMESPACE_PATTERN.sub("", str(element.tag or ""))
            if tag == "t":
                text = str(element.text or "").strip()
                if text:
                    fragments.append(text)
        return _normalize_whitespace(" ".join(fragments))
    except Exception:
        return ""


def _extract_xlsx_text(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
        fragments = []
        for sheet in workbook.worksheets:
            if sheet.title:
                fragments.append(f"[工作表]{sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                cells = [str(cell).strip() for cell in row if str(cell or "").strip()]
                if cells:
                    fragments.append(" | ".join(cells))
        return _normalize_whitespace("\n".join(fragments))
    except Exception:
        return ""


def _decode_pdf_fragment(raw_bytes: bytes) -> str:
    text = raw_bytes.decode("latin-1", errors="ignore")
    text = text.replace(r"\(", "(").replace(r"\)", ")").replace(r"\n", "\n").replace(r"\r", "")
    return _normalize_whitespace(text)


def _extract_pdf_text(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""

    fragments = []
    for match in _PDF_TEXT_PATTERN.findall(raw_bytes):
        decoded = _decode_pdf_fragment(match)
        if decoded:
            fragments.append(decoded)

    if not fragments:
        for block in _PDF_ARRAY_TEXT_PATTERN.findall(raw_bytes):
            parts = []
            for match in _PDF_ARRAY_SEGMENT_PATTERN.findall(block):
                decoded = _decode_pdf_fragment(match)
                if decoded:
                    parts.append(decoded)
            if parts:
                fragments.append(" ".join(parts))

    if not fragments:
        rough_strings = []
        for item in _PRINTABLE_STRING_PATTERN.findall(raw_bytes):
            decoded = _decode_pdf_fragment(item)
            if decoded and len(decoded) >= 8:
                rough_strings.append(decoded)
        fragments = rough_strings

    deduped = []
    seen = set()
    for fragment in fragments:
        key = fragment.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fragment)
        if len("\n".join(deduped)) >= 18000:
            break

    return _normalize_whitespace("\n".join(deduped))


def _looks_like_html(name: str, mime: str, text: str) -> bool:
    lower_name = str(name or "").lower()
    mime_text = str(mime or "").lower()
    raw = str(text or "")
    return (
        lower_name.endswith((".html", ".htm"))
        or "html" in mime_text
        or ("<html" in raw.lower() or "<body" in raw.lower())
    )


def _looks_like_json(name: str, mime: str, text: str) -> bool:
    lower_name = str(name or "").lower()
    mime_text = str(mime or "").lower()
    raw = str(text or "").strip()
    return (
        lower_name.endswith(".json")
        or "json" in mime_text
        or (raw.startswith("{") and raw.endswith("}"))
        or (raw.startswith("[") and raw.endswith("]"))
    )


def _format_json_for_text(raw: str) -> str:
    try:
        parsed = json.loads(raw)
        return _normalize_whitespace(json.dumps(parsed, ensure_ascii=False, indent=2))
    except Exception:
        return _normalize_whitespace(raw)


def _is_metadata_only_summary(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.startswith(_METADATA_ONLY_PREFIXES) for line in lines[:4])


def extract_text_from_learning_asset(
    *,
    name: str = "",
    mime: str = "",
    content: str = "",
    summary: str = "",
    file_bytes: bytes = b"",
) -> Dict[str, object]:
    provided_content = _normalize_whitespace(content)
    summary_text = _normalize_whitespace(summary)
    lower_name = str(name or "").lower()
    mime_text = str(mime or "").lower()

    extracted_text = ""
    method = "empty"
    warnings: List[str] = []

    if file_bytes and is_git_lfs_pointer_bytes(file_bytes):
        warnings.append("uploaded_file_is_git_lfs_pointer")

    if file_bytes:
        if lower_name.endswith(".docx") or "wordprocessingml.document" in mime_text:
            extracted_text = _extract_docx_text(file_bytes)
            method = "docx_xml" if extracted_text else method
        elif lower_name.endswith(".xlsx") or "spreadsheetml.sheet" in mime_text:
            extracted_text = _extract_xlsx_text(file_bytes)
            method = "xlsx_cells" if extracted_text else method
        elif lower_name.endswith(".pdf") or "pdf" in mime_text:
            extracted_text = _extract_pdf_text(file_bytes)
            method = "pdf_text" if extracted_text else method
        elif lower_name.endswith(tuple(_TEXT_FILE_EXTENSIONS)) or mime_text.startswith("text/") or mime_text in {
            "application/json",
            "application/xml",
            "text/csv",
            "text/tab-separated-values",
        }:
            decoded = _decode_text_bytes(file_bytes)
            if decoded:
                if _looks_like_html(lower_name, mime_text, decoded):
                    extracted_text = _strip_html_tags(decoded)
                    method = "html_text"
                elif _looks_like_json(lower_name, mime_text, decoded):
                    extracted_text = _format_json_for_text(decoded)
                    method = "json_text"
                else:
                    extracted_text = decoded
                    method = "text_decode"
        else:
            decoded = _decode_text_bytes(file_bytes[:12000])
            if decoded and len(decoded) >= 20 and not looks_like_binary_text(decoded):
                extracted_text = decoded
                method = "binary_best_effort"

    candidates = []
    if provided_content:
        candidates.append(("provided_content", provided_content))
    if extracted_text:
        candidates.append((method, extracted_text))
    if summary_text and not _is_metadata_only_summary(summary_text):
        candidates.append(("summary", summary_text))

    primary_method = "empty"
    primary_text = ""
    if candidates:
        primary_method, primary_text = max(candidates, key=lambda item: len(str(item[1] or "")))

    if primary_method == "summary" and extracted_text:
        primary_method = method or "file_extract"
        primary_text = extracted_text

    if not primary_text and summary_text and not _is_metadata_only_summary(summary_text):
        primary_text = summary_text
        primary_method = "summary_only"

    chunks = split_text_into_chunks(primary_text, chunk_size=720, overlap=120, max_chunks=24) if primary_text else []
    quality = "empty"
    if primary_text:
        if len(primary_text) >= 120 and len(chunks) >= 1:
            quality = "rich_text"
        elif len(primary_text) >= 24:
            quality = "light_text"
        else:
            quality = "minimal_text"

    return {
        "text": primary_text,
        "preview": normalize_text_preview(primary_text, 220),
        "method": primary_method,
        "warnings": warnings,
        "content_length": len(primary_text),
        "chunk_count": len(chunks),
        "quality": quality,
    }


_KNOWLEDGE_CONNECTORS = (
    "是指",
    "指的是",
    "定义为",
    "称为",
    "叫做",
    "又称",
    "简称",
    "包括",
    "分为",
    "组成",
    "构成",
    "性质",
    "特点",
    "特征",
    "原理",
    "定理",
    "定律",
    "公式",
    "定义",
    "方法",
    "步骤",
    "作用",
    "意义",
    "区别",
    "联系",
    "条件",
    "结论",
)
_KNOWLEDGE_NOISE_PREFIXES = _METADATA_ONLY_PREFIXES + (
    "说明:",
    "说明：",
    "工作表",
    "总页数",
    "作者",
    "目录",
    "例题",
    "例 ",
    "练习",
    "习题",
    "作业",
    "思考题",
    "参考答案",
    "答案",
    "解析",
    "参考文献",
    "版权",
)
_KNOWLEDGE_HEADING_PATTERN = re.compile(
    r"^(?:#{1,6}\s*|[一二三四五六七八九十]+[、.．]|\d+[、.．)]|第[一二三四五六七八九十百\d]+[章节讲部分]|[（(][一二三四五六七八九十\d]+[）)])"
)
_KNOWLEDGE_SPLIT_PATTERN = re.compile(r"(?<=[。！？；!?;])|(?<=\.)\s+(?=[A-Z0-9])|\n+")
_KNOWLEDGE_TITLE_PATTERN = re.compile(
    r"^(?P<title>[^，。；：:、,;!?！？]{2,24}?)(?:是指|指的是|定义为|称为|叫做|又称|简称|是|包括|分为|由|:|：)"
)


_LATIN_DEFINITION_PATTERN = re.compile(
    r"^(?P<title>[A-Za-z][A-Za-z0-9\-' ]{1,60}?)\s+"
    r"(?:is|are|refers to|means|is defined as|are defined as|denotes|stands for)\s+\S",
    re.IGNORECASE,
)
_LATIN_COLON_PATTERN = re.compile(r"^(?P<title>[A-Za-z][A-Za-z0-9\-' ]{1,60}?)\s*[:：]\s+\S")


def _is_latin_heavy(text: str) -> bool:
    letters = [char for char in str(text or "") if char.isalpha()]
    if not letters:
        return False
    ascii_letters = sum(1 for char in letters if char.isascii())
    return (ascii_letters / len(letters)) > 0.7


_LATIN_TITLE_STOPWORDS = {
    "the", "a", "an", "this", "that", "these", "those", "it", "there", "you", "we", "i",
    "each", "every", "some", "all", "which", "what", "who", "how", "when", "where",
    "answer", "answers", "identify", "choose", "mark", "marking", "read", "following",
    "statement", "statements", "question", "questions", "paragraph", "paragraphs",
    "information", "sheet", "letter", "letters", "more", "than", "once",
}


def _latin_knowledge_title(text: str) -> str:
    """英文资料只保留“术语 + 定义”形式的知识点，避免把整句说明当知识点。"""
    body = str(text or "").strip()
    match = _LATIN_DEFINITION_PATTERN.match(body) or _LATIN_COLON_PATTERN.match(body)
    if not match:
        return ""
    title = re.sub(r"^(the|a|an)\s+", "", match.group("title").strip(), flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" ,.;:-")
    words = title.split()
    if not words or len(words) > 4:
        return ""
    if any(word.lower() in _LATIN_TITLE_STOPWORDS for word in words):
        return ""
    if len(words) > 1:
        # 多词术语要求每个词首字母大写（如 Newton's Second Law）
        if not all(word[0].isupper() for word in words if word[0].isalpha()):
            return ""
    else:
        word = words[0]
        if not word[0].isupper() or len(word) < 4:
            return ""
    return " ".join(words)[:48]


def _clean_knowledge_candidate(text: str) -> str:
    cleaned = _WHITESPACE_PATTERN.sub(" ", str(text or "")).strip()
    cleaned = cleaned.strip("#*>-· \t")
    cleaned = cleaned.strip("“”\"'")
    return cleaned.strip()


def _knowledge_candidate_key(text: str) -> str:
    return re.sub(r"[\s，。；：、,.!?;:（）()【】\[\]“”\"'‘’]", "", str(text or "")).lower()


def _looks_like_knowledge_heading(text: str) -> bool:
    return bool(_KNOWLEDGE_HEADING_PATTERN.match(str(text or "").strip()))


def _score_knowledge_candidate(text: str) -> int:
    raw = str(text or "").strip()
    if not raw or re.fullmatch(r"[\d\s\W_]+", raw):
        return -1

    score = 0
    if any(token in raw for token in _KNOWLEDGE_CONNECTORS):
        score += 3
    if _looks_like_knowledge_heading(raw):
        score += 2
    if 10 <= len(raw) <= 80:
        score += 2
    elif len(raw) <= 140:
        score += 1
    if re.search(r"[A-Za-z]{2,}", raw):
        score += 1
    if re.search(r"[=＝≤≥≠∞∑√∫]", raw):
        score += 1
    if raw.endswith(("。", "！", "？", "；", ".", "!", "?", ";")):
        score += 1
    return score


def _build_knowledge_title(text: str) -> str:
    raw = str(text or "").strip()
    heading_match = _KNOWLEDGE_HEADING_PATTERN.match(raw)
    body = raw[heading_match.end():].strip() if heading_match else raw
    if not body:
        body = raw

    title_match = _KNOWLEDGE_TITLE_PATTERN.match(body)
    if title_match:
        title = title_match.group("title").strip()
        if 2 <= len(title) <= 24:
            return title

    compact = re.split(r"[，,。；;：:！!？?]", body)[0].strip()
    if 2 <= len(compact) <= 24:
        return compact
    return (compact or body)[:20].strip()


def _knowledge_title_for_candidate(text: str) -> str:
    candidate = str(text or "").strip()
    if not candidate:
        return ""
    if _is_latin_heavy(candidate):
        return _latin_knowledge_title(candidate)
    return _build_knowledge_title(candidate)


def extract_knowledge_points(text: str, limit: int = 8) -> List[Dict[str, str]]:
    """从学习资料正文中抽取可复用的知识点（标题 + 原文依据）。

    采用规则抽取，保证上传链路稳定、可离线运行；抽取结果会随条目一起持久化，
    供题库练习、学习仪表盘等模块复用，而不仅限于问答检索。
    """
    normalized = _normalize_whitespace(text)
    if not normalized:
        return []
    if looks_like_binary_text(normalized):
        return []

    try:
        max_points = max(1, min(20, int(limit or 8)))
    except Exception:
        max_points = 8

    raw_parts = [part.strip() for part in _KNOWLEDGE_SPLIT_PATTERN.split(normalized) if part.strip()]
    candidates = []
    seen_keys = set()

    for index, part in enumerate(raw_parts):
        candidate = _clean_knowledge_candidate(part)
        if not candidate:
            continue
        if any(candidate.startswith(prefix) for prefix in _KNOWLEDGE_NOISE_PREFIXES):
            continue
        if len(candidate) < 6 or len(candidate) > 160:
            continue
        key = _knowledge_candidate_key(candidate)
        if not key or key in seen_keys:
            continue
        score = _score_knowledge_candidate(candidate)
        if score <= 0:
            continue
        title = _knowledge_title_for_candidate(candidate)
        if _is_latin_heavy(candidate) and not title:
            continue
        if is_noise_knowledge_title(title):
            continue
        seen_keys.add(key)
        candidates.append({
            "index": index,
            "score": score,
            "title": title,
            "detail": candidate,
        })

    if not candidates:
        for index, part in enumerate(raw_parts[:6]):
            candidate = _clean_knowledge_candidate(part)
            if not candidate:
                continue
            if any(candidate.startswith(prefix) for prefix in _KNOWLEDGE_NOISE_PREFIXES):
                continue
            if len(candidate) < 6 or len(candidate) > 160:
                continue
            key = _knowledge_candidate_key(candidate)
            if not key or key in seen_keys:
                continue
            title = _knowledge_title_for_candidate(candidate)
            if _is_latin_heavy(candidate) and not title:
                continue
            if is_noise_knowledge_title(title):
                continue
            seen_keys.add(key)
            candidates.append({
                "index": index,
                "score": 1,
                "title": title,
                "detail": candidate,
            })

    candidates.sort(key=lambda item: (-int(item["score"]), int(item["index"])))
    picked = candidates[:max_points]
    picked.sort(key=lambda item: int(item["index"]))

    points = []
    for item in picked:
        title = str(item["title"] or "").strip()
        detail = str(item["detail"] or "").strip()
        if not title and not detail:
            continue
        points.append({
            "title": title or detail[:20],
            "detail": detail,
            "weight": round(min(1.0, max(0.02, float(item["score"]) / 9.0)), 3),
        })
    return points


def split_text_into_chunks(
    text: str,
    *,
    chunk_size: int = 700,
    overlap: int = 120,
    max_chunks: int = 48,
) -> List[str]:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return []

    size = max(120, int(chunk_size or 700))
    overlap_size = max(0, min(size // 2, int(overlap or 120)))
    limit = max(1, int(max_chunks or 48))

    if len(normalized) <= size:
        return [normalized]

    segments = []
    buffer = ""
    pieces = [piece.strip() for piece in re.split(r"(?<=[。！？；.!?;])|\n+", normalized) if piece.strip()]
    for piece in pieces:
        candidate = f"{buffer}{piece}" if buffer else piece
        if len(candidate) <= size:
            buffer = candidate + ("\n" if len(candidate) < size else "")
            continue
        if buffer:
            segments.append(buffer.strip())
            if len(segments) >= limit:
                return segments
            tail = buffer[-overlap_size:] if overlap_size else ""
            buffer = f"{tail}{piece}".strip()
        else:
            start = 0
            while start < len(piece):
                end = min(len(piece), start + size)
                chunk = piece[start:end].strip()
                if chunk:
                    segments.append(chunk)
                    if len(segments) >= limit:
                        return segments
                if end >= len(piece):
                    buffer = ""
                    break
                start = max(end - overlap_size, start + 1)

    if buffer.strip() and len(segments) < limit:
        segments.append(buffer.strip())

    return segments[:limit]
