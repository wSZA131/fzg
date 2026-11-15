"""开放学习资源适配器。

只接入公开、可合法调用的官方 API，不抓取商业站点页面：
- Wikipedia / MediaWiki API
- Wikibooks / MediaWiki API
- OpenStax CMS API
- Oak National Academy Curriculum API（配置 OAK_API_KEY 后启用）
- SerpApi Google Play Books（配置 SERPAPI_API_KEY 后启用）
- YouTube Data API v3（配置 YOUTUBE_API_KEY 后启用）

返回统一的资源结构，交给推荐引擎做排序、去重和解释。
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List
from urllib.parse import quote

import requests


logger = logging.getLogger(__name__)

WIKIPEDIA_LANGUAGES = [
    item.strip()
    for item in os.getenv("WIKIPEDIA_LANGUAGES", "zh").split(",")
    if item.strip()
]
OPEN_TEXTBOOKS_ENABLED = str(os.getenv("OPEN_TEXTBOOKS_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
OPENSTAX_ENABLED = str(os.getenv("OPENSTAX_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
OPEN_RESOURCE_TIMEOUT_SECONDS = max(0.8, float(os.getenv("OPEN_RESOURCE_TIMEOUT_SECONDS", "1.8")))
OPEN_RESOURCE_CACHE_TTL_SECONDS = max(600, int(os.getenv("OPEN_RESOURCE_CACHE_TTL_SECONDS", "21600")))
OPENSTAX_CATALOG_TTL_SECONDS = max(3600, int(os.getenv("OPENSTAX_CATALOG_TTL_SECONDS", "86400")))
OPEN_RESOURCE_MAX_QUERIES = max(1, min(6, int(os.getenv("OPEN_RESOURCE_MAX_QUERIES", "4"))))
OPEN_RESOURCE_CACHE: Dict[str, Any] = {}
CACHE_LOCK = threading.RLock()
MEDIAWIKI_SEMAPHORE = threading.Semaphore(2)
OPENSTAX_CATALOG_URL = "https://openstax.org/apps/cms/api/v2/pages/"
OAK_API_URL = "https://open-api.thenational.academy/api/v1/search/lessons"
OAK_LESSON_URL = "https://www.thenational.academy/teachers/lessons"
SERPAPI_URL = "https://serpapi.com/search.json"
SERPAPI_ALLOWED_ENGINES = {
    "google_scholar",
    "google_books",
    "google_videos",
    "google_play_books",
}
SERPAPI_DEFAULT_ENGINES = "google_scholar,google_books,google_videos,google_play_books"
OAK_QUERY_ALIASES = {
    "导数": ["differentiation", "calculus"],
    "微分": ["differentiation", "calculus"],
    "积分": ["integration", "calculus"],
    "极限": ["limits", "calculus"],
    "函数": ["functions", "algebra"],
    "代数": ["algebra"],
    "几何": ["geometry"],
    "三角": ["trigonometry"],
    "统计": ["statistics"],
    "概率": ["probability", "statistics"],
    "物理": ["physics"],
    "力学": ["forces", "physics"],
    "化学": ["chemistry"],
    "生物": ["biology"],
    "英语": ["english"],
    "历史": ["history"],
    "地理": ["geography"],
    "计算机": ["computing"],
    "编程": ["computing", "programming"],
    "数据": ["data", "computing"],
}
OPENSTAX_QUERY_ALIASES = {
    "微积分": ["calculus", "derivative", "integral"],
    "导数": ["calculus", "derivative", "differentiation"],
    "微分": ["calculus", "derivative", "differential"],
    "积分": ["calculus", "integral", "integration"],
    "极限": ["calculus", "limit", "limits"],
    "函数": ["algebra", "function", "functions"],
    "代数": ["algebra"],
    "线性代数": ["linear algebra"],
    "几何": ["geometry", "trigonometry"],
    "三角": ["trigonometry"],
    "统计": ["statistics"],
    "概率": ["statistics", "probability"],
    "物理": ["physics", "mechanics"],
    "力学": ["physics", "mechanics"],
    "电磁": ["physics", "electromagnetism"],
    "化学": ["chemistry"],
    "有机化学": ["organic chemistry", "chemistry"],
    "生物": ["biology"],
    "经济": ["economics"],
    "微观经济": ["microeconomics", "economics"],
    "宏观经济": ["macroeconomics", "economics"],
    "会计": ["accounting"],
    "心理": ["psychology"],
    "计算机": ["computer science"],
    "编程": ["computer science", "programming"],
    "数据结构": ["computer science", "data structures"],
    "美国政治": ["american government", "political science"],
}
USER_AGENT = os.getenv(
    "OPEN_RESOURCE_USER_AGENT",
    "FangZhiGong/1.0 (learning recommendation; contact: local-app)",
)


def _cache_get(key: str):
    now = time.time()
    with CACHE_LOCK:
        entry = OPEN_RESOURCE_CACHE.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at <= now:
            OPEN_RESOURCE_CACHE.pop(key, None)
            return None
        return value


def _cache_set(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    ttl = max(60, int(ttl_seconds or OPEN_RESOURCE_CACHE_TTL_SECONDS))
    with CACHE_LOCK:
        OPEN_RESOURCE_CACHE[key] = (time.time() + ttl, value)


def _youtube_api_key() -> str:
    # server.py 会先导入本模块，再读取 .env；因此 Key 必须在调用时读取，
    # 不能在模块导入时缓存成常量。
    return os.getenv("YOUTUBE_API_KEY", "").strip()


def _oak_api_key() -> str:
    return os.getenv("OAK_API_KEY", "").strip()


def _serpapi_api_key() -> str:
    return os.getenv("SERPAPI_API_KEY", "").strip()


def _serpapi_engines() -> List[str]:
    raw = os.getenv("SERPAPI_ENGINES", SERPAPI_DEFAULT_ENGINES)
    engines = []
    for item in str(raw or "").split(","):
        engine = item.strip().lower()
        if engine in SERPAPI_ALLOWED_ENGINES and engine not in engines:
            engines.append(engine)
    return engines


def _serpapi_max_queries() -> int:
    try:
        value = int(os.getenv("SERPAPI_MAX_QUERIES", "2"))
    except (TypeError, ValueError):
        value = 2
    return max(1, min(4, value))


def _clean_query(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:80]


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:14]
    return f"{prefix}-{digest}"


def _http_get_json(
    url: str,
    params: Dict[str, Any],
    timeout: float | None = None,
    headers: Dict[str, str] | None = None,
) -> Any:
    is_mediawiki = "wikipedia.org" in url or "wikibooks.org" in url
    effective_timeout = max(0.8, float(timeout or OPEN_RESOURCE_TIMEOUT_SECONDS))
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    response = None
    for attempt in range(2):
        try:
            if is_mediawiki:
                with MEDIAWIKI_SEMAPHORE:
                    response = requests.get(
                        url,
                        params=params,
                        headers=request_headers,
                        timeout=effective_timeout,
                    )
            else:
                response = requests.get(
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=effective_timeout,
                )
        except Exception:
            if attempt == 0:
                time.sleep(0.25)
                continue
            raise

        if response.status_code == 429 and attempt == 0:
            retry_after = response.headers.get("Retry-After", "0.6")
            try:
                delay = max(0.25, min(1.2, float(retry_after)))
            except (TypeError, ValueError):
                delay = 0.6
            time.sleep(delay)
            continue
        break

    if response is None:
        return {}
    if response.status_code >= 400:
        logger.info("open resource request failed: %s %s", response.status_code, url)
        return {}
    payload = response.json()
    return payload if isinstance(payload, (dict, list)) else {}


def _normalize_mediawiki_result(
    page: Dict[str, Any],
    query: str,
    language: str,
    *,
    domain: str,
    provider: str,
    resource_kind: str,
    resource_type: str,
    source: str,
) -> Dict[str, Any]:
    page_id = str(page.get("pageid") or "").strip()
    title = str(page.get("title") or "").strip()
    extract = str(page.get("extract") or "").strip()
    full_url = str(page.get("fullurl") or "").strip()
    if not page_id or not title or not extract:
        return {}
    if not full_url:
        full_url = f"https://{language}.{domain}/wiki/{quote(title)}"

    thumbnail = page.get("thumbnail") if isinstance(page.get("thumbnail"), dict) else {}
    cover_url = str(thumbnail.get("source") or "").strip()
    char_count = len(extract)
    duration = max(3, min(18, int(char_count / 240) + 3))

    return {
        "id": _stable_id(provider.lower(), f"{language}:{page_id}"),
        "title": title,
        "concept": query,
        "resource_kind": resource_kind,
        "resource_type": resource_type,
        "provider": provider,
        "difficulty": "medium",
        "duration_minutes": duration,
        "cover_url": cover_url,
        "action": {
            "type": "external_course",
            "concept": query,
            "url": full_url,
            "provider": provider,
        },
        "tags": [query, language, "百科" if resource_kind == "open_article" else "教材"],
        "learning_styles": ["visual", "auditory"],
        "quality_score": 0.78 if resource_kind == "open_article" else 0.74,
        "source": source,
        "summary": extract[:320],
    }


def _search_mediawiki(
    query: str,
    limit: int,
    *,
    domain: str,
    provider: str,
    resource_kind: str,
    resource_type: str,
    source: str,
    languages: List[str],
) -> List[Dict[str, Any]]:
    cleaned_query = _clean_query(query)
    if not cleaned_query:
        return []

    cache_key = f"{source}:{cleaned_query}:{limit}:{','.join(languages)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    results = []
    for language in languages:
        try:
            payload = _http_get_json(
                f"https://{language}.{domain}/w/api.php",
                {
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": cleaned_query,
                    "gsrlimit": max(1, min(10, int(limit))),
                    "gsrnamespace": 0,
                    "prop": "extracts|pageimages|info",
                    "exintro": 1,
                    "explaintext": 1,
                    "exsentences": 3,
                    "piprop": "thumbnail",
                    "pithumbsize": 640,
                    "inprop": "url",
                    "redirects": 1,
                },
            )
        except Exception as error:
            logger.info("%s search failed for %s/%s: %s", provider, language, cleaned_query, error)
            continue

        pages = ((payload.get("query") or {}).get("pages") or {})
        if not isinstance(pages, dict):
            continue
        ordered = sorted(
            [item for item in pages.values() if isinstance(item, dict)],
            key=lambda item: int(item.get("index") or 0),
        )
        for page in ordered:
            normalized = _normalize_mediawiki_result(
                page,
                cleaned_query,
                language,
                domain=domain,
                provider=provider,
                resource_kind=resource_kind,
                resource_type=resource_type,
                source=source,
            )
            if normalized:
                results.append(normalized)
        if results:
            break

    results = results[: max(0, int(limit))]
    _cache_set(cache_key, results)
    return results


def search_wikipedia(query: str, limit: int = 2) -> List[Dict[str, Any]]:
    return _search_mediawiki(
        query,
        limit,
        domain="wikipedia.org",
        provider="Wikipedia",
        resource_kind="open_article",
        resource_type="拓展阅读",
        source="open_wikipedia",
        languages=WIKIPEDIA_LANGUAGES,
    )


def search_wikibooks(query: str, limit: int = 1) -> List[Dict[str, Any]]:
    if not OPEN_TEXTBOOKS_ENABLED:
        return []
    return _search_mediawiki(
        query,
        limit,
        domain="wikibooks.org",
        provider="Wikibooks",
        resource_kind="open_textbook",
        resource_type="开放教材",
        source="open_wikibooks",
        languages=WIKIPEDIA_LANGUAGES,
    )


def _strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _load_openstax_catalog() -> List[Dict[str, Any]]:
    cached = _cache_get("openstax:catalog")
    if cached is not None:
        return list(cached)

    try:
        payload = _http_get_json(
            OPENSTAX_CATALOG_URL,
            {
                "type": "books.Book",
                "fields": "title,description,cover_url",
                "limit": 200,
            },
            timeout=max(3.0, OPEN_RESOURCE_TIMEOUT_SECONDS + 1.5),
        )
    except Exception as error:
        logger.info("openstax catalog failed: %s", error)
        return []

    rows = payload.get("items") if isinstance(payload.get("items"), list) else []
    books = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        title = str(row.get("title") or "").strip()
        slug = str(meta.get("slug") or "").strip()
        url = str(meta.get("html_url") or "").strip()
        if not url and slug:
            url = f"https://openstax.org/details/books/{quote(slug)}"
        if not title or not url:
            continue
        books.append({
            "title": title,
            "slug": slug,
            "url": url,
            "cover_url": str(row.get("cover_url") or "").strip(),
            "description": _strip_html(row.get("description")),
        })
    _cache_set("openstax:catalog", books, OPENSTAX_CATALOG_TTL_SECONDS)
    return books


def _openstax_search_terms(query: str) -> List[str]:
    terms = []
    seen = set()

    def add(term: Any) -> None:
        text = str(term or "").strip().lower()
        if len(text) < 2 or text in seen:
            return
        seen.add(text)
        terms.append(text)

    for alias in OPENSTAX_QUERY_ALIASES.get(query, []):
        add(alias)
    if re.search(r"[a-zA-Z]", query):
        add(query)
    return terms


def search_openstax(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    cleaned_query = _clean_query(query)
    if not cleaned_query or not OPENSTAX_ENABLED:
        return []

    cache_key = f"openstax:search:{cleaned_query}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    terms = _openstax_search_terms(cleaned_query)
    if not terms:
        _cache_set(cache_key, [])
        return []

    catalog = _load_openstax_catalog()
    scored = []
    for book in catalog:
        title = str(book.get("title") or "")
        description = str(book.get("description") or "")
        title_lower = title.lower()
        description_lower = description.lower()
        score = 0
        for term in terms:
            if term in title_lower:
                score += 4
            elif term in description_lower:
                score += 1
        if score <= 0:
            continue
        scored.append((score, title, book))
    scored.sort(key=lambda row: (-row[0], row[1]))

    results = []
    for score, title, book in scored[: max(1, min(8, int(limit)))]:
        slug = str(book.get("slug") or "").strip()
        result_id = _stable_id("openstax", slug or str(book.get("url") or title))
        results.append({
            "id": result_id,
            "title": title,
            "concept": cleaned_query,
            "resource_kind": "open_textbook",
            "resource_type": "开放教材",
            "provider": "OpenStax",
            "difficulty": "medium",
            "duration_minutes": 20,
            "cover_url": str(book.get("cover_url") or "").strip(),
            "action": {
                "type": "external_course",
                "concept": cleaned_query,
                "url": str(book.get("url") or "").strip(),
                "provider": "OpenStax",
            },
            "tags": [cleaned_query, "教材", "OpenStax"],
            "learning_styles": ["visual", "auditory"],
            "quality_score": 0.84,
            "source": "open_openstax",
            "summary": str(book.get("description") or "")[:320],
        })
    _cache_set(cache_key, results)
    return results


def _oak_search_terms(query: str) -> List[str]:
    terms = []
    seen = set()

    def add(value: Any) -> None:
        text = str(value or "").strip().lower()
        if len(text) < 2 or text in seen:
            return
        seen.add(text)
        terms.append(text)

    for alias in OAK_QUERY_ALIASES.get(query, []):
        add(alias)
    if re.search(r"[a-zA-Z]", query):
        add(query)
    return terms


def _normalize_oak_result(row: Dict[str, Any], query: str) -> Dict[str, Any]:
    slug = str(row.get("lessonSlug") or "").strip()
    title = str(row.get("lessonTitle") or "").strip()
    if not slug or not title:
        return {}

    units = row.get("units") if isinstance(row.get("units"), list) else []
    unit = units[0] if units and isinstance(units[0], dict) else {}
    unit_title = str(unit.get("unitTitle") or "").strip()
    subject = str(unit.get("subjectSlug") or "").strip()
    key_stage = str(unit.get("keyStageSlug") or "").strip()
    url = str(row.get("oakUrl") or "").strip() or f"{OAK_LESSON_URL}/{quote(slug)}"
    similarity = max(0.0, min(1.0, float(row.get("similarity") or 0)))
    quality = min(0.82, 0.72 + similarity * 0.25)

    return {
        "id": _stable_id("oak", slug),
        "title": title,
        "concept": query,
        "resource_kind": "open_lesson",
        "resource_type": "课程资源",
        "provider": "Oak National Academy",
        "difficulty": "medium",
        "duration_minutes": 0,
        "cover_url": "",
        "action": {
            "type": "external_course",
            "concept": query,
            "url": url,
            "provider": "Oak National Academy",
        },
        "tags": [query, "课程", subject, key_stage],
        "learning_styles": ["visual", "auditory"],
        "quality_score": quality,
        "source": "open_oak",
        "summary": " · ".join(part for part in (unit_title, subject, key_stage) if part)[:320],
    }


def search_oak(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    cleaned_query = _clean_query(query)
    api_key = _oak_api_key()
    if not cleaned_query or not api_key:
        return []

    cache_key = f"oak:{cleaned_query}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    results = []
    seen_ids = set()
    for term in _oak_search_terms(cleaned_query)[:2]:
        try:
            payload = _http_get_json(
                OAK_API_URL,
                {"q": term},
                timeout=3.0,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        except Exception as error:
            logger.info("oak search failed for %s: %s", term, error)
            continue

        rows = payload if isinstance(payload, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = _normalize_oak_result(row, cleaned_query)
            if not normalized:
                continue
            resource_id = normalized["id"]
            if resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            results.append(normalized)
        if len(results) >= limit:
            break

    results = results[: max(0, int(limit))]
    _cache_set(cache_key, results)
    return results


def _iter_google_play_book_items(node: Any):
    if isinstance(node, dict):
        title = str(node.get("title") or "").strip()
        link = str(node.get("link") or "").strip()
        product_id = str(node.get("product_id") or "").strip()
        if (
            title
            and link
            and product_id
            and "play.google.com/store/books/details" in link
            and "/series" not in link
        ):
            yield node
        for value in node.values():
            yield from _iter_google_play_book_items(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_google_play_book_items(value)


def _normalize_google_play_book(row: Dict[str, Any], query: str) -> Dict[str, Any]:
    product_id = str(row.get("product_id") or "").strip()
    title = str(row.get("title") or "").strip()
    link = str(row.get("link") or "").strip()
    if not product_id or not title or not link:
        return {}

    author = str(row.get("author") or "").strip()
    category = str(row.get("category") or "").strip()
    description = str(row.get("description") or "").strip()
    rating = row.get("rating")
    quality = 0.74
    try:
        quality = min(0.82, 0.70 + max(0.0, min(5.0, float(rating or 0))) * 0.02)
    except (TypeError, ValueError):
        pass

    return {
        "id": _stable_id("gplay", product_id),
        "title": title,
        "concept": query,
        "resource_kind": "external_book",
        "resource_type": "商业图书",
        "provider": "Google Play Books",
        "difficulty": "medium",
        "duration_minutes": 0,
        "cover_url": str(row.get("thumbnail") or "").strip(),
        "action": {
            "type": "external_course",
            "concept": query,
            "url": link,
            "provider": "Google Play Books",
        },
        "tags": [query, "图书", author, category],
        "learning_styles": ["visual", "auditory"],
        "quality_score": quality,
        "source": "open_google_play_books",
        "summary": description[:320],
    }


def search_google_play_books(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    cleaned_query = _clean_query(query)
    api_key = _serpapi_api_key()
    if not cleaned_query or not api_key:
        return []

    cache_key = f"google_play_books:{cleaned_query}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    try:
        payload = _http_get_json(
            SERPAPI_URL,
            {
                "engine": "google_play_books",
                "q": cleaned_query,
                "hl": "zh-CN",
                "gl": "us",
                "api_key": api_key,
            },
            timeout=3.2,
        )
    except Exception as error:
        logger.info("google play books search failed for %s: %s", cleaned_query, error)
        return []

    rows = list(_iter_google_play_book_items(payload)) if isinstance(payload, dict) else []
    results = []
    seen_ids = set()
    for row in rows:
        normalized = _normalize_google_play_book(row, cleaned_query)
        if not normalized:
            continue
        resource_id = normalized["id"]
        if resource_id in seen_ids:
            continue
        seen_ids.add(resource_id)
        results.append(normalized)
        if len(results) >= limit:
            break
    _cache_set(cache_key, results)
    return results


def _normalize_google_scholar_result(row: Dict[str, Any], query: str) -> Dict[str, Any]:
    title = str(row.get("title") or "").strip()
    link = str(row.get("link") or "").strip()
    result_id = str(row.get("result_id") or "").strip()
    if not title or not link:
        return {}
    publication_info = row.get("publication_info") if isinstance(row.get("publication_info"), dict) else {}
    publication = str(publication_info.get("summary") or "").strip()
    snippet = str(row.get("snippet") or "").strip()

    return {
        "id": _stable_id("scholar", result_id or link),
        "title": title,
        "concept": query,
        "resource_kind": "open_paper",
        "resource_type": "学术论文",
        "provider": "Google Scholar",
        "difficulty": "medium",
        "duration_minutes": 0,
        "cover_url": "",
        "action": {
            "type": "external_course",
            "concept": query,
            "url": link,
            "provider": "Google Scholar",
        },
        "tags": [query, "论文", publication],
        "learning_styles": ["visual"],
        "quality_score": 0.80,
        "source": "serpapi_google_scholar",
        "summary": (snippet or publication)[:320],
    }


def _normalize_google_books_result(row: Dict[str, Any], query: str) -> Dict[str, Any]:
    title = str(row.get("title") or "").strip()
    link = str(row.get("link") or "").strip()
    book_id = str(row.get("book_id") or "").strip()
    if not title or not link:
        return {}
    authors = []
    for author in row.get("authors") if isinstance(row.get("authors"), list) else []:
        if isinstance(author, dict) and str(author.get("name") or "").strip():
            authors.append(str(author["name"]).strip())
    author_text = "、".join(authors[:3])
    snippet = str(row.get("snippet") or "").strip()

    return {
        "id": _stable_id("gbooks", book_id or link),
        "title": title,
        "concept": query,
        "resource_kind": "external_book",
        "resource_type": "商业图书",
        "provider": "Google Books",
        "difficulty": "medium",
        "duration_minutes": 0,
        "cover_url": str(row.get("thumbnail") or "").strip(),
        "action": {
            "type": "external_course",
            "concept": query,
            "url": link,
            "provider": "Google Books",
        },
        "tags": [query, "图书", author_text, str(row.get("date") or "")],
        "learning_styles": ["visual"],
        "quality_score": 0.76,
        "source": "serpapi_google_books",
        "summary": snippet[:320],
    }


def _normalize_google_videos_result(row: Dict[str, Any], query: str) -> Dict[str, Any]:
    title = str(row.get("title") or "").strip()
    link = str(row.get("link") or "").strip()
    if not title or not link:
        return {}
    snippet = str(row.get("snippet") or "").strip()
    displayed_link = str(row.get("displayed_link") or "").strip()

    return {
        "id": _stable_id("gvideo", link),
        "title": title,
        "concept": query,
        "resource_kind": "open_video",
        "resource_type": "视频拓展",
        "provider": "Google Videos",
        "difficulty": "medium",
        "duration_minutes": 0,
        "cover_url": str(row.get("thumbnail") or "").strip(),
        "action": {
            "type": "external_course",
            "concept": query,
            "url": link,
            "provider": "Google Videos",
        },
        "tags": [query, "视频", displayed_link],
        "learning_styles": ["auditory", "visual"],
        "quality_score": 0.72,
        "source": "serpapi_google_videos",
        "summary": snippet[:320],
    }


def search_serpapi(query: str, engine: str, limit: int = 4) -> List[Dict[str, Any]]:
    cleaned_query = _clean_query(query)
    api_key = _serpapi_api_key()
    if not cleaned_query or not api_key or engine not in {
        "google_scholar",
        "google_books",
        "google_videos",
    }:
        return []

    cache_key = f"serpapi:{engine}:{cleaned_query}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    try:
        payload = _http_get_json(
            SERPAPI_URL,
            {
                "engine": engine,
                "q": cleaned_query,
                "hl": "zh-CN",
                "gl": "us",
                "api_key": api_key,
            },
            timeout=3.2,
        )
    except Exception as error:
        logger.info("serpapi %s search failed for %s: %s", engine, cleaned_query, error)
        return []

    if not isinstance(payload, dict):
        return []
    if engine == "google_videos":
        rows = payload.get("video_results") if isinstance(payload.get("video_results"), list) else []
        normalizer = _normalize_google_videos_result
    else:
        rows = payload.get("organic_results") if isinstance(payload.get("organic_results"), list) else []
        normalizer = _normalize_google_scholar_result if engine == "google_scholar" else _normalize_google_books_result

    results = []
    seen_ids = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = normalizer(row, cleaned_query)
        if not normalized:
            continue
        resource_id = normalized["id"]
        if resource_id in seen_ids:
            continue
        seen_ids.add(resource_id)
        results.append(normalized)
        if len(results) >= limit:
            break
    _cache_set(cache_key, results)
    return results


def _normalize_youtube_result(item: Dict[str, Any], query: str) -> Dict[str, Any]:
    snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
    video_id = str((item.get("id") or {}).get("videoId") or "").strip()
    title = str(snippet.get("title") or "").strip()
    description = str(snippet.get("description") or "").strip()
    if not video_id or not title:
        return {}

    thumbnails = snippet.get("thumbnails") if isinstance(snippet.get("thumbnails"), dict) else {}
    thumb = thumbnails.get("high") if isinstance(thumbnails.get("high"), dict) else thumbnails.get("medium")
    cover_url = str((thumb or {}).get("url") or "").strip() if isinstance(thumb, dict) else ""
    channel = str(snippet.get("channelTitle") or "YouTube").strip()

    return {
        "id": _stable_id("yt", video_id),
        "title": title,
        "concept": query,
        "resource_kind": "open_video",
        "resource_type": "视频拓展",
        "provider": f"YouTube · {channel}" if channel else "YouTube",
        "difficulty": "medium",
        "duration_minutes": 0,
        "cover_url": cover_url,
        "action": {
            "type": "external_course",
            "concept": query,
            "url": f"https://www.youtube.com/watch?v={quote(video_id)}",
            "provider": "YouTube",
        },
        "tags": [query, "视频", channel],
        "learning_styles": ["auditory", "visual"],
        "quality_score": 0.7,
        "source": "open_youtube",
        "summary": description[:260],
    }


def search_youtube(query: str, limit: int = 1) -> List[Dict[str, Any]]:
    cleaned_query = _clean_query(query)
    api_key = _youtube_api_key()
    if not cleaned_query or not api_key:
        return []

    cache_key = f"youtube:{cleaned_query}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    try:
        payload = _http_get_json(
            "https://www.googleapis.com/youtube/v3/search",
            {
                "part": "snippet",
                "type": "video",
                "q": cleaned_query,
                "maxResults": max(1, min(12, int(limit))),
                "key": api_key,
                "safeSearch": "strict",
                "videoEmbeddable": "true",
                "videoSyndicated": "true",
                "relevanceLanguage": "zh",
            },
        )
    except Exception as error:
        logger.info("youtube search failed for %s: %s", cleaned_query, error)
        return []

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        if str(snippet.get("liveBroadcastContent") or "none") != "none":
            continue
        normalized = _normalize_youtube_result(item, cleaned_query)
        if normalized:
            results.append(normalized)
    results = results[: max(0, int(limit))]
    _cache_set(cache_key, results)
    return results


def fetch_open_resources(
    concepts: Iterable[str],
    limit_per_concept: int = 2,
    max_queries: int = OPEN_RESOURCE_MAX_QUERIES,
) -> List[Dict[str, Any]]:
    """按知识点查询开放资源，返回去重后的资源列表。"""
    queries = []
    seen = set()
    source = concepts if isinstance(concepts, (list, tuple, set)) else [concepts]
    for concept in source:
        text = _clean_query(concept)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        queries.append(text)
        if len(queries) >= max_queries:
            break

    if not queries:
        return []

    youtube_enabled = bool(_youtube_api_key())
    oak_enabled = bool(_oak_api_key())
    serpapi_engines = _serpapi_engines() if _serpapi_api_key() else []
    serpapi_queries = queries[:min(len(queries), _serpapi_max_queries())]
    task_count = len(queries) * (
        1
        + (1 if OPEN_TEXTBOOKS_ENABLED else 0)
        + (1 if OPENSTAX_ENABLED else 0)
        + (1 if youtube_enabled else 0)
        + (1 if oak_enabled else 0)
    ) + len(serpapi_queries) * len(serpapi_engines)
    results = []
    with ThreadPoolExecutor(max_workers=min(12, max(1, task_count))) as executor:
        futures = []
        for query in queries:
            futures.append(executor.submit(search_wikipedia, query, min(10, max(6, limit_per_concept * 2))))
            if OPEN_TEXTBOOKS_ENABLED:
                futures.append(executor.submit(search_wikibooks, query, min(5, max(3, limit_per_concept))))
            if OPENSTAX_ENABLED:
                futures.append(executor.submit(search_openstax, query, min(5, max(3, limit_per_concept))))
            if youtube_enabled:
                futures.append(executor.submit(search_youtube, query, min(12, max(10, limit_per_concept * 3))))
            if oak_enabled:
                futures.append(executor.submit(search_oak, query, 5))
        for query in serpapi_queries:
            for engine in serpapi_engines:
                if engine == "google_play_books":
                    futures.append(executor.submit(search_google_play_books, query, 5))
                else:
                    futures.append(executor.submit(search_serpapi, query, engine, 4))

        for future in as_completed(futures):
            try:
                rows = future.result()
            except Exception as error:
                logger.info("open resource provider error: %s", error)
                continue
            if isinstance(rows, list):
                results.extend(rows)

    deduped = []
    seen_ids = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        resource_id = str(item.get("id") or "").strip()
        if not resource_id or resource_id in seen_ids:
            continue
        seen_ids.add(resource_id)
        deduped.append(item)

    query_order = {query: index for index, query in enumerate(queries)}
    deduped.sort(key=lambda item: (
        query_order.get(str(item.get("concept") or ""), len(query_order)),
        -float(item.get("quality_score") or 0),
        str(item.get("title") or ""),
    ))
    return deduped
