"""学习空间蓝图：空间与空间内容的 CRUD、预览。

包含空间相关的工具函数（空间/内容归一化、序列化、预览鉴权）与 9 个接口。
对 server 模块的共享函数（身份解析、存储读写、通用工具）通过 ``_server()``
延迟获取，保持与测试 patch 的兼容，同时规避循环依赖。
"""
from __future__ import annotations

import base64
import io
import re
import uuid

import requests
from flask import Blueprint, Response, jsonify, request
from itsdangerous import BadData, SignatureExpired
from werkzeug.datastructures import FileStorage

from ..config import (
    LEARNING_CONTENT_MAX_CHARS,
    LEARNING_CONTENT_PREVIEW_CHARS,
    SPACE_MAX_FILE_BYTES,
    SPACE_MAX_ITEM_COUNT,
    SPACE_PREVIEW_SIGNATURE_QUERY_PARAM,
    SPACE_PREVIEW_TOKEN_TTL_SECONDS,
)
from ..services.document_ingest import (
    extract_knowledge_points,
    extract_text_from_learning_asset,
    is_noise_knowledge_title,
    looks_like_binary_text,
    normalize_text_preview,
    split_text_into_chunks,
)
from ..services.ocr_service import extract_text_from_image as extract_text_from_image_service
from ..utils.http import (
    error_response,
    get_request_id,
    normalize_request_user_id,
    success_payload,
)
from .auth import extract_bearer_token

spaces_bp = Blueprint("spaces", __name__, url_prefix="/api/spaces")


def _server():
    """延迟获取 server 模块，保持共享函数与测试 patch 的兼容。"""
    from .. import server
    return server


# ===== 空间工具函数 =====

def sync_material_knowledge(s, user_id, items):
    """把资料知识点并入知识库（供图谱、题库练习、仪表盘共用）。"""
    concepts = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        for point in normalize_knowledge_point_list(item.get("knowledgePoints")):
            title = str(point.get("title") or "").strip()
            if 2 <= len(title) <= 16 and not is_noise_knowledge_title(title):
                concepts.append(title)
        for topic in s.normalize_topic_list(item.get("topics")):
            topic_text = str(topic or "").strip()
            if 2 <= len(topic_text) <= 12 and not is_noise_knowledge_title(topic_text):
                concepts.append(topic_text)

    if not concepts or not hasattr(s, "register_material_concepts"):
        return {"added": 0, "concepts": []}
    try:
        return s.register_material_concepts(user_id, concepts)
    except Exception:
        return {"added": 0, "concepts": []}


def normalize_space_name(value, fallback="新空间"):
    text = str(value or "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return (text or fallback or "新空间")[:40]


def normalize_knowledge_point_list(raw_points, limit=8):
    """统一知识点结构，兼容历史数据里字符串形式的知识点。"""
    points = []
    seen = set()
    for raw in raw_points if isinstance(raw_points, list) else []:
        if len(points) >= max(1, int(limit or 8)):
            break
        if isinstance(raw, str):
            point = {"title": raw.strip(), "detail": raw.strip(), "weight": 0.3}
        elif isinstance(raw, dict):
            title = str(raw.get("title") or raw.get("name") or "").strip()[:40]
            detail = str(raw.get("detail") or raw.get("content") or title).strip()[:240]
            try:
                weight = round(float(raw.get("weight") or 0.3), 3)
            except Exception:
                weight = 0.3
            point = {"title": title, "detail": detail, "weight": weight}
        else:
            continue
        key = (point["title"] or point["detail"]).strip().lower()
        if not key or key in seen:
            continue
        if is_noise_knowledge_title(point["title"]):
            continue
        seen.add(key)
        points.append(point)
    return points


def summarize_space_item(name, kind, mime, size, source, content, has_file):
    kind_text = str(kind or "document").strip() or "document"
    mime_text = str(mime or "").strip() or "unknown"
    size_kb = max(1, round(max(0, int(size or 0)) / 1024))
    source_text = str(source or "space").strip() or "space"
    lines = [
        f"类型: {kind_text}",
        f"MIME: {mime_text}",
        f"大小: {size_kb} KB",
        f"来源: {source_text}",
    ]

    plain = re.sub(r"\s+", " ", str(content or "")).strip()
    if plain:
        excerpt = plain[:180]
        if len(plain) > 180:
            excerpt += "..."
        lines.append(f"内容摘要: {excerpt}")
    elif has_file:
        lines.append(f"已保存云端原始文件，可直接预览分析《{str(name or '未命名文件').strip() or '未命名文件'}》。")
    else:
        lines.append("当前条目已保存，可直接在空间中查看。")
    return "\n".join(lines)


def decode_space_data_url(data_url):
    raw = str(data_url or "").strip()
    if not raw or not raw.startswith("data:") or "," not in raw:
        return b"", ""

    header, payload = raw.split(",", 1)
    mime = header[5:].split(";")[0].strip() or "application/octet-stream"

    if ";base64" in header:
        try:
            return base64.b64decode(payload), mime
        except Exception:
            return b"", mime

    try:
        return requests.utils.unquote(payload).encode("utf-8"), mime
    except Exception:
        return payload.encode("utf-8"), mime


def build_space_item_fingerprint(item):
    if not isinstance(item, dict):
        return ""

    comparable = {
        "name": str(item.get("name") or ""),
        "kind": str(item.get("kind") or ""),
        "mime": str(item.get("mime") or ""),
        "size": int(item.get("size") or 0),
        "source": str(item.get("source") or ""),
        "content": str(item.get("content") or ""),
        "summary": str(item.get("summary") or ""),
        "audioDataUrl": str(item.get("audioDataUrl") or ""),
        "fileDataUrl": str(item.get("fileDataUrl") or ""),
    }
    return _server().stable_json_key(comparable)


def create_space_record(name):
    ts = _server().now_ms()
    return {
        "id": f"space_{ts}_{uuid.uuid4().hex[:6]}",
        "name": normalize_space_name(name, "新空间"),
        "description": "",
        "createdAt": ts,
        "updatedAt": ts,
        "items": [],
    }


def is_image_space_item(name, mime, kind):
    lower_name = str(name or "").strip().lower()
    mime_text = str(mime or "").strip().lower()
    kind_text = str(kind or "").strip().lower()
    return (
        kind_text in {"image", "photo", "picture"}
        or mime_text.startswith("image/")
        or lower_name.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"))
    )


def build_content_sentence_points(body, limit=6):
    """OCR 图片里的文字常常是整句，没有“术语定义”结构，这里直接取关键句作为知识点。"""
    points = []
    for sentence in re.split(r"[。！？；!?;\n]+|(?<=\.)\s+", str(body or "")):
        sentence = str(sentence or "").strip(" \t\r\n·-—")
        if not (12 <= len(sentence) <= 120):
            continue
        if is_noise_knowledge_title(sentence):
            continue
        title = sentence if len(sentence) <= 28 else sentence[:26] + "…"
        points.append({"title": title, "detail": sentence, "weight": 0.15})
        if len(points) >= max(1, int(limit or 6)):
            break
    return points


def build_space_item_learning_metadata(name, content, summary="", topics=None, allow_sentence_fallback=False):
    s = _server()
    body = s.clamp_text(content or "", LEARNING_CONTENT_MAX_CHARS)
    if looks_like_binary_text(body):
        # 二进制文件被强行解码后的乱码不参与主题与知识点抽取
        body = ""
    chunks = split_text_into_chunks(body, chunk_size=720, overlap=120, max_chunks=24) if body else []
    knowledge_points = extract_knowledge_points(body, limit=8) if body else []
    if not knowledge_points and allow_sentence_fallback and len(body.strip()) >= 20:
        knowledge_points = build_content_sentence_points(body, limit=6)

    merged_topics = [
        topic for topic in s.normalize_topic_list(topics)
        if not is_noise_knowledge_title(topic)
    ]
    if not merged_topics and knowledge_points:
        # 优先用抽取到的知识点标题作为主题，避免规则兜底把长句切碎成碎片
        merged_topics = s.normalize_topic_list([
            point.get("title")
            for point in knowledge_points
            if 2 <= len(str(point.get("title") or "").strip()) <= 12
            and not is_noise_knowledge_title(point.get("title"))
        ])[:6]
    if not merged_topics:
        # 只用正文/摘要推断主题：文件名（如“屏幕截图”“IMG_001”）不是学习内容
        seed_parts = []
        if body:
            seed_parts.append(body[:4000])
        elif summary and not str(summary or "").startswith(("类型:", "文件名:")):
            seed_parts.append(str(summary or "")[:1000])
        seed_text = "\n".join(part for part in seed_parts if str(part or "").strip()).strip()
        if seed_text:
            merged_topics = s.normalize_topic_list(s.detect_concepts_from_text(seed_text))[:6]

    if not knowledge_points and merged_topics:
        knowledge_points = [
            {"title": str(topic or "").strip(), "detail": str(topic or "").strip(), "weight": 0.3}
            for topic in merged_topics[:6]
            if str(topic or "").strip()
        ]
    return {
        "contentPreview": normalize_text_preview(body, 220),
        "contentLength": len(body),
        "textChunkCount": len(chunks),
        "topics": merged_topics[:6],
        "knowledgePoints": knowledge_points[:8],
        "knowledgePointCount": len(knowledge_points[:8]),
        "retrievalReady": bool(body and chunks),
    }


def normalize_space_item_input(raw_item, index_offset=0):
    if not isinstance(raw_item, dict):
        return None

    s = _server()
    file_data_url = str(raw_item.get("fileDataUrl") or "")
    audio_data_url = str(raw_item.get("audioDataUrl") or "")
    primary_data_url = audio_data_url or file_data_url
    decoded_bytes, decoded_mime = decode_space_data_url(primary_data_url)
    if decoded_bytes and len(decoded_bytes) > SPACE_MAX_FILE_BYTES:
        raise ValueError(f"单个文件不能超过 {max(1, SPACE_MAX_FILE_BYTES // 1024 // 1024)} MB")

    ts = s.now_ms() + max(0, int(index_offset or 0))
    mime = str(raw_item.get("mime") or decoded_mime or "").strip()
    kind = str(raw_item.get("kind") or "document").strip() or "document"
    extracted = extract_text_from_learning_asset(
        name=str(raw_item.get("name") or ""),
        mime=mime,
        content=str(raw_item.get("content") or ""),
        summary=str(raw_item.get("summary") or ""),
        file_bytes=decoded_bytes,
    )
    text_extract_method = str(extracted.get("method") or "")
    extracted_text = str(extracted.get("text") or "")
    if text_extract_method == "summary_only":
        # 只有文件元信息（类型/大小/文件名）不算正文，图片需要继续走 OCR
        extracted_text = ""
        text_extract_method = "empty"
    content = s.clamp_text(extracted_text or raw_item.get("content") or "", LEARNING_CONTENT_MAX_CHARS)
    text_extract_warnings = extracted.get("warnings", []) if isinstance(extracted.get("warnings", []), list) else []
    ocr_provider = ""
    ocr_fallback_used = False
    ocr_error_code = ""

    if decoded_bytes and is_image_space_item(raw_item.get("name"), mime, kind) and not content:
        ocr_result = s.extract_text_from_image_service(
            FileStorage(
                stream=io.BytesIO(decoded_bytes),
                filename=str(raw_item.get("name") or "学习图片"),
                content_type=mime or "application/octet-stream",
            )
        )
        ocr_text = s.clamp_text((ocr_result or {}).get("text") or "", LEARNING_CONTENT_MAX_CHARS)
        ocr_synthetic = bool((ocr_result or {}).get("synthetic", False))
        if ocr_text and not ocr_synthetic:
            content = ocr_text
            text_extract_method = "image_ocr"
        elif ocr_synthetic:
            # 离线兜底的占位文案不代表真实识别结果，不写入正文与知识点
            text_extract_warnings = list(text_extract_warnings) + ["image_ocr_unavailable"]
        ocr_provider = str((ocr_result or {}).get("provider") or "").strip()
        ocr_fallback_used = bool((ocr_result or {}).get("fallback_used", False))
        ocr_error_code = str((ocr_result or {}).get("error_code") or "").strip()
        if ocr_error_code:
            text_extract_warnings = list(text_extract_warnings) + [ocr_error_code]

    summary = s.clamp_text(raw_item.get("summary"), 4000).strip()
    size = int(raw_item.get("size") or 0)
    if decoded_bytes:
        size = max(size, len(decoded_bytes))
    elif content:
        size = max(size, len(content.encode("utf-8")))

    item = {
        "id": f"item_{ts}_{uuid.uuid4().hex[:6]}",
        "name": s.clamp_text(raw_item.get("name") or "未命名文件", 180).strip() or "未命名文件",
        "kind": kind,
        "mime": mime,
        "size": max(0, size),
        "source": s.clamp_text(raw_item.get("source") or "space_upload", 64).strip(),
        "content": content,
        "summary": summary,
        "audioDataUrl": audio_data_url if kind == "audio" or mime.startswith("audio/") else "",
        "fileDataUrl": file_data_url or (audio_data_url if kind == "audio" or mime.startswith("audio/") else ""),
        "addedAt": ts,
        "updatedAt": ts,
        "textExtractMethod": text_extract_method,
        "textExtractWarnings": text_extract_warnings,
        "ocrProvider": ocr_provider,
        "ocrFallbackUsed": ocr_fallback_used,
        "ocrErrorCode": ocr_error_code,
    }
    if not item["summary"]:
        item["summary"] = summarize_space_item(
            name=item["name"],
            kind=item["kind"],
            mime=item["mime"],
            size=item["size"],
            source=item["source"],
            content=item["content"],
            has_file=bool(item["fileDataUrl"] or item["audioDataUrl"]),
        )
    item.update(
        build_space_item_learning_metadata(
            name=item.get("name"),
            content=item.get("content"),
            summary=item.get("summary"),
            topics=raw_item.get("topics"),
            allow_sentence_fallback=text_extract_method.startswith("image_ocr"),
        )
    )
    return item


def find_space_by_id(space_payload, space_id):
    for space in (space_payload or {}).get("spaces", []):
        if str((space or {}).get("id") or "").strip() == str(space_id or "").strip():
            return space
    return None


def find_space_item(space_payload, item_id):
    target_id = str(item_id or "").strip()
    if not target_id:
        return None, None

    for space in (space_payload or {}).get("spaces", []):
        items = space.get("items", []) if isinstance(space, dict) else []
        for item in items if isinstance(items, list) else []:
            if str((item or {}).get("id") or "").strip() == target_id:
                return space, item
    return None, None


def merge_space_item_lists(existing_items, incoming_items):
    s = _server()
    merged = [
        s.deep_copy_data(item, {})
        for item in existing_items if isinstance(item, dict)
    ]
    id_map = {
        str(item.get("id") or "").strip(): idx
        for idx, item in enumerate(merged)
        if str(item.get("id") or "").strip()
    }
    fingerprints = {
        build_space_item_fingerprint(item)
        for item in merged
        if build_space_item_fingerprint(item)
    }
    added_count = 0

    for raw_item in incoming_items if isinstance(incoming_items, list) else []:
        if not isinstance(raw_item, dict):
            continue
        payload = s.deep_copy_data(raw_item, {})
        item_id = str(payload.get("id") or "").strip()
        fingerprint = build_space_item_fingerprint(payload)

        if item_id and item_id in id_map:
            idx = id_map[item_id]
            current = merged[idx]
            current_updated = int(current.get("updatedAt") or current.get("addedAt") or 0)
            incoming_updated = int(payload.get("updatedAt") or payload.get("addedAt") or 0)
            if incoming_updated >= current_updated:
                merged[idx] = payload
            continue

        if fingerprint and fingerprint in fingerprints:
            continue

        merged.append(payload)
        if item_id:
            id_map[item_id] = len(merged) - 1
        if fingerprint:
            fingerprints.add(fingerprint)
        added_count += 1

    merged.sort(key=lambda item: int(item.get("addedAt") or 0), reverse=True)
    return merged[:SPACE_MAX_ITEM_COUNT], added_count


def merge_space_payloads(existing_payload, incoming_payload):
    s = _server()
    current = s.deep_copy_data(existing_payload or {}, {"activeEntrySpaceId": "", "spaces": []})
    incoming = s.deep_copy_data(incoming_payload or {}, {"activeEntrySpaceId": "", "spaces": []})
    current_spaces = current.get("spaces", []) if isinstance(current.get("spaces"), list) else []
    incoming_spaces = incoming.get("spaces", []) if isinstance(incoming.get("spaces"), list) else []

    merged_spaces = [
        s.deep_copy_data(space, {})
        for space in current_spaces if isinstance(space, dict)
    ]
    space_map = {
        str(space.get("id") or "").strip(): idx
        for idx, space in enumerate(merged_spaces)
        if str(space.get("id") or "").strip()
    }

    added_spaces = 0
    added_items = 0

    for raw_space in incoming_spaces:
        if not isinstance(raw_space, dict):
            continue

        payload = s.deep_copy_data(raw_space, {})
        space_id = str(payload.get("id") or "").strip()
        if not space_id:
            continue

        if space_id in space_map:
            idx = space_map[space_id]
            target_space = merged_spaces[idx]
            merged_items, item_added = merge_space_item_lists(
                target_space.get("items", []),
                payload.get("items", []),
            )
            target_space["items"] = merged_items
            target_space["name"] = normalize_space_name(target_space.get("name") or payload.get("name"), "新空间")
            target_space["description"] = str(target_space.get("description") or payload.get("description") or "").strip()
            target_space["updatedAt"] = max(
                int(target_space.get("updatedAt") or target_space.get("createdAt") or 0),
                int(payload.get("updatedAt") or payload.get("createdAt") or 0),
            )
            added_items += item_added
            continue

        new_space = s.deep_copy_data(payload, {})
        new_space["name"] = normalize_space_name(new_space.get("name"), "新空间")
        new_space["description"] = str(new_space.get("description") or "").strip()
        new_space["items"] = (new_space.get("items", []) if isinstance(new_space.get("items"), list) else [])[:SPACE_MAX_ITEM_COUNT]
        merged_spaces.append(new_space)
        space_map[space_id] = len(merged_spaces) - 1
        added_spaces += 1
        added_items += len(new_space.get("items", []))

    valid_ids = [str(space.get("id") or "").strip() for space in merged_spaces if str(space.get("id") or "").strip()]
    active_space_id = str(current.get("activeEntrySpaceId") or "").strip()
    if active_space_id not in valid_ids:
        incoming_active = str(incoming.get("activeEntrySpaceId") or "").strip()
        active_space_id = incoming_active if incoming_active in valid_ids else (valid_ids[0] if valid_ids else "")

    merged_spaces.sort(key=lambda space: int(space.get("createdAt") or 0), reverse=True)
    return {
        "activeEntrySpaceId": active_space_id,
        "spaces": merged_spaces,
    }, {
        "spaces": added_spaces,
        "items": added_items,
    }


def serialize_space_item(item, user_id):
    s = _server()
    preview_available = bool(
        str(item.get("audioDataUrl") or "").strip()
        or str(item.get("fileDataUrl") or "").strip()
        or str(item.get("content") or "").strip()
    )
    preview_signature = s.create_space_preview_token(user_id, item.get("id")) if preview_available else ""
    preview_url = s.build_api_absolute_url(
        f"/api/spaces/items/{requests.utils.quote(str(item.get('id') or ''), safe='')}/preview",
        {
            SPACE_PREVIEW_SIGNATURE_QUERY_PARAM: preview_signature or None,
        },
    ) if preview_available else ""
    knowledge_points = normalize_knowledge_point_list(item.get("knowledgePoints"))

    return {
        "id": str(item.get("id") or "").strip(),
        "name": str(item.get("name") or "未命名文件"),
        "kind": str(item.get("kind") or "document"),
        "mime": str(item.get("mime") or ""),
        "size": int(item.get("size") or 0),
        "source": str(item.get("source") or ""),
        "content": str(item.get("content") or ""),
        "summary": str(item.get("summary") or ""),
        "contentPreview": str(item.get("contentPreview") or normalize_text_preview(item.get("content") or "", 220)),
        "contentLength": int(item.get("contentLength") or len(str(item.get("content") or ""))),
        "textExtractMethod": str(item.get("textExtractMethod") or ""),
        "textExtractWarnings": item.get("textExtractWarnings", []) if isinstance(item.get("textExtractWarnings", []), list) else [],
        "textChunkCount": int(item.get("textChunkCount") or 0),
        "topics": s.normalize_topic_list(item.get("topics"))[:6],
        "knowledgePoints": knowledge_points,
        "knowledgePointCount": len(knowledge_points),
        "retrievalReady": bool(item.get("retrievalReady", bool(str(item.get("content") or "").strip()))),
        "ocrProvider": str(item.get("ocrProvider") or ""),
        "ocrFallbackUsed": bool(item.get("ocrFallbackUsed", False)),
        "ocrErrorCode": str(item.get("ocrErrorCode") or ""),
        "addedAt": int(item.get("addedAt") or s.now_ms()),
        "updatedAt": int(item.get("updatedAt") or item.get("addedAt") or s.now_ms()),
        "previewUrl": preview_url,
        "previewAvailable": preview_available,
    }


def serialize_space(space, user_id):
    items = [
        serialize_space_item(item, user_id)
        for item in (space.get("items", []) if isinstance(space.get("items"), list) else [])
        if isinstance(item, dict)
    ]
    items.sort(key=lambda item: int(item.get("addedAt") or 0), reverse=True)
    return {
        "id": str(space.get("id") or "").strip(),
        "name": normalize_space_name(space.get("name"), "新空间"),
        "description": str(space.get("description") or "").strip(),
        "createdAt": int(space.get("createdAt") or _server().now_ms()),
        "updatedAt": int(space.get("updatedAt") or space.get("createdAt") or _server().now_ms()),
        "items": items[:SPACE_MAX_ITEM_COUNT],
        "itemCount": len(items),
    }


def resolve_space_preview_user_id(item_id):
    s = _server()
    if extract_bearer_token():
        identity, auth_error = s.resolve_current_request_identity(allow_guest=False, touch_session=True)
        if auth_error:
            return None, auth_error
        return str((identity or {}).get("user_id") or "").strip(), None

    preview_signature = str(request.args.get(SPACE_PREVIEW_SIGNATURE_QUERY_PARAM, "") or "").strip()
    if not preview_signature:
        return None, error_response(
            get_request_id(),
            401,
            "AUTH_REQUIRED",
            "预览链接已失效，请重新打开内容详情后再试",
        )

    try:
        payload = s.get_space_preview_token_serializer().loads(
            preview_signature,
            max_age=SPACE_PREVIEW_TOKEN_TTL_SECONDS,
        )
    except SignatureExpired:
        return None, error_response(
            get_request_id(),
            401,
            "PREVIEW_TOKEN_EXPIRED",
            "预览链接已过期，请重新打开内容详情后再试",
        )
    except BadData:
        return None, error_response(
            get_request_id(),
            401,
            "PREVIEW_TOKEN_INVALID",
            "预览链接无效，请重新打开内容详情后再试",
        )

    preview_item_id = str((payload or {}).get("item_id") or "").strip()
    preview_user_id = normalize_request_user_id((payload or {}).get("user_id"), fallback="")
    if preview_item_id != str(item_id or "").strip() or not preview_user_id:
        return None, error_response(
            get_request_id(),
            401,
            "PREVIEW_TOKEN_INVALID",
            "预览链接无效，请重新打开内容详情后再试",
        )
    return preview_user_id, None


# ===== 空间路由 =====

@spaces_bp.route("", methods=["GET"])
def get_spaces():
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_current_request_user_id_from_args()
    if auth_error:
        return auth_error

    payload = s.get_user_space_payload(user_id)
    spaces = [
        serialize_space(space, user_id)
        for space in (payload.get("spaces", []) if isinstance(payload.get("spaces"), list) else [])
        if isinstance(space, dict)
    ]
    spaces.sort(key=lambda item: int(item.get("createdAt") or 0), reverse=True)

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        spaces=spaces,
        count=len(spaces),
        activeEntrySpaceId=str(payload.get("activeEntrySpaceId") or ""),
        storage=s.get_storage_info(),
        error_code="",
        error_message="",
    ))


@spaces_bp.route("", methods=["POST"])
def create_space():
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_current_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    payload = s.get_user_space_payload(user_id)
    fallback_name = f"新空间 {len(payload.get('spaces', []) if isinstance(payload.get('spaces'), list) else []) + 1}"
    space = create_space_record(normalize_space_name(data.get("name"), fallback_name))
    payload["spaces"] = [space] + (payload.get("spaces", []) if isinstance(payload.get("spaces"), list) else [])
    payload["activeEntrySpaceId"] = space["id"]
    s.set_user_space_payload(user_id, payload)

    return jsonify(success_payload(
        request_id,
        message="空间创建成功",
        user_id=user_id,
        space=serialize_space(space, user_id),
        count=len(payload.get("spaces", [])),
        error_code="",
        error_message="",
    ))


@spaces_bp.route("/<space_id>", methods=["PUT", "POST"])
def update_space(space_id):
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_current_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    payload = s.get_user_space_payload(user_id)
    space = find_space_by_id(payload, space_id)
    if not space:
        return error_response(request_id, 404, "SPACE_NOT_FOUND", "目标空间不存在，请刷新后重试")

    updates = {}
    if "name" in data:
        current_name = normalize_space_name(space.get("name"), "新空间")
        updates["name"] = normalize_space_name(data.get("name"), current_name)
    if "description" in data:
        updates["description"] = s.clamp_text(data.get("description"), 800).strip()

    if not updates:
        return error_response(request_id, 400, "INVALID_INPUT", "没有可更新的空间信息")

    space.update(updates)
    space["updatedAt"] = s.now_ms()
    s.set_user_space_payload(user_id, payload)

    return jsonify(success_payload(
        request_id,
        message="空间更新成功",
        user_id=user_id,
        space=serialize_space(space, user_id),
        error_code="",
        error_message="",
    ))


@spaces_bp.route("/<space_id>", methods=["DELETE"])
def delete_space(space_id):
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_current_request_user_id_from_args()
    if auth_error:
        return auth_error

    payload = s.get_user_space_payload(user_id)
    spaces = payload.get("spaces", []) if isinstance(payload.get("spaces"), list) else []
    target_index = -1
    removed_space = None

    for idx, space in enumerate(spaces):
        if str((space or {}).get("id") or "").strip() == str(space_id or "").strip():
            target_index = idx
            removed_space = space
            break

    if target_index < 0 or not isinstance(removed_space, dict):
        return error_response(request_id, 404, "SPACE_NOT_FOUND", "空间不存在或已被删除")

    spaces.pop(target_index)
    active_space_id = str(payload.get("activeEntrySpaceId") or "").strip()
    if active_space_id == str(removed_space.get("id") or "").strip():
        payload["activeEntrySpaceId"] = str((spaces[0] or {}).get("id") or "").strip() if spaces else ""
    payload["spaces"] = spaces
    s.set_user_space_payload(user_id, payload)
    s.invalidate_user_kb_cache(user_id)

    removed_items = removed_space.get("items", []) if isinstance(removed_space.get("items"), list) else []
    return jsonify(success_payload(
        request_id,
        message="空间已删除",
        user_id=user_id,
        deleted=True,
        spaceId=str(removed_space.get("id") or ""),
        deletedItemCount=len(removed_items),
        count=len(spaces),
        error_code="",
        error_message="",
    ))


@spaces_bp.route("/<space_id>/items", methods=["POST"])
def create_space_items(space_id):
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_current_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return error_response(request_id, 400, "INVALID_INPUT", "请至少提交一个空间内容条目")

    payload = s.get_user_space_payload(user_id)
    space = find_space_by_id(payload, space_id)
    if not space:
        return error_response(request_id, 404, "SPACE_NOT_FOUND", "目标空间不存在，请刷新后重试")

    created_items = []
    try:
        for index, raw_item in enumerate(raw_items):
            item = normalize_space_item_input(raw_item, index)
            if item:
                created_items.append(item)
    except ValueError as exc:
        return error_response(request_id, 400, "INVALID_INPUT", str(exc))

    if not created_items:
        return error_response(request_id, 400, "INVALID_INPUT", "没有可保存的有效内容")

    previous_items = space.get("items", []) if isinstance(space.get("items"), list) else []
    space["items"] = (created_items + previous_items)[:SPACE_MAX_ITEM_COUNT]
    space["updatedAt"] = s.now_ms()
    payload["activeEntrySpaceId"] = str(space.get("id") or "").strip()
    s.set_user_space_payload(user_id, payload)
    s.invalidate_user_kb_cache(user_id)
    knowledge_sync = sync_material_knowledge(s, user_id, created_items)

    return jsonify(success_payload(
        request_id,
        message="空间内容保存成功",
        user_id=user_id,
        createdCount=len(created_items),
        knowledgeSync=knowledge_sync,
        items=[serialize_space_item(item, user_id) for item in created_items],
        space=serialize_space(space, user_id),
        error_code="",
        error_message="",
    ))


@spaces_bp.route("/items/<item_id>", methods=["GET"])
def get_space_item_detail(item_id):
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_current_request_user_id_from_args()
    if auth_error:
        return auth_error

    payload = s.get_user_space_payload(user_id)
    space, item = find_space_item(payload, item_id)
    if not item or not space:
        return error_response(request_id, 404, "SPACE_ITEM_NOT_FOUND", "空间内容不存在或已被删除")

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        item=serialize_space_item(item, user_id),
        space={
            "id": str(space.get("id") or "").strip(),
            "name": normalize_space_name(space.get("name"), "新空间"),
        },
        error_code="",
        error_message="",
    ))


@spaces_bp.route("/items/<item_id>", methods=["PUT", "POST"])
def update_space_item(item_id):
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_current_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    payload = s.get_user_space_payload(user_id)
    space, item = find_space_item(payload, item_id)
    if not item or not space:
        return error_response(request_id, 404, "SPACE_ITEM_NOT_FOUND", "空间内容不存在或已被删除")

    target_space_id = str(data.get("targetSpaceId") or data.get("target_space_id") or "").strip()
    move_target_space = None
    if target_space_id and target_space_id != str(space.get("id") or "").strip():
        move_target_space = find_space_by_id(payload, target_space_id)
        if not move_target_space:
            return error_response(request_id, 404, "SPACE_NOT_FOUND", "目标空间不存在，请刷新后重试")

    updates = {}
    if "name" in data:
        updates["name"] = s.clamp_text(data.get("name") or "未命名文件", 180).strip() or "未命名文件"
    if "content" in data:
        updates["content"] = s.clamp_text(data.get("content"), 120000)
    if "summary" in data:
        updates["summary"] = s.clamp_text(data.get("summary"), 4000).strip()

    if not updates and not move_target_space:
        return error_response(request_id, 400, "INVALID_INPUT", "没有可更新的内容")

    item.update(updates)
    item["updatedAt"] = s.now_ms()
    if "content" in updates:
        item["textExtractMethod"] = "manual_edit"
        item["textExtractWarnings"] = []
        item["ocrErrorCode"] = ""
    if "content" in updates and "summary" not in updates:
        item["summary"] = summarize_space_item(
            name=item.get("name"),
            kind=item.get("kind"),
            mime=item.get("mime"),
            size=item.get("size"),
            source=item.get("source"),
            content=item.get("content"),
            has_file=bool(item.get("fileDataUrl") or item.get("audioDataUrl")),
        )
    if {"name", "content", "summary"} & set(updates.keys()):
        item.update(
            build_space_item_learning_metadata(
                name=item.get("name"),
                content=item.get("content"),
                summary=item.get("summary"),
                topics=item.get("topics"),
            )
        )
    space["updatedAt"] = item["updatedAt"]
    if move_target_space and move_target_space is not space:
        source_items = space.get("items", []) if isinstance(space.get("items"), list) else []
        target_items = move_target_space.get("items", []) if isinstance(move_target_space.get("items"), list) else []
        space["items"] = [
            existing for existing in source_items
            if str((existing or {}).get("id") or "").strip() != str(item.get("id") or "").strip()
        ]
        move_target_space["items"] = [item] + [
            existing for existing in target_items
            if str((existing or {}).get("id") or "").strip() != str(item.get("id") or "").strip()
        ]
        if len(move_target_space["items"]) > SPACE_MAX_ITEM_COUNT:
            move_target_space["items"] = move_target_space["items"][:SPACE_MAX_ITEM_COUNT]
        move_target_space["updatedAt"] = item["updatedAt"]
    s.set_user_space_payload(user_id, payload)
    s.invalidate_user_kb_cache(user_id)
    knowledge_sync = sync_material_knowledge(s, user_id, [item])

    return jsonify(success_payload(
        request_id,
        message="空间内容更新成功" if not move_target_space else "空间内容已移动",
        user_id=user_id,
        knowledgeSync=knowledge_sync,
        item=serialize_space_item(item, user_id),
        space=serialize_space(move_target_space or space, user_id),
        sourceSpace=serialize_space(space, user_id),
        error_code="",
        error_message="",
    ))


@spaces_bp.route("/items/<item_id>", methods=["DELETE"])
def delete_space_item(item_id):
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_current_request_user_id_from_args()
    if auth_error:
        return auth_error

    payload = s.get_user_space_payload(user_id)
    space, item = find_space_item(payload, item_id)
    if not item or not space:
        return error_response(request_id, 404, "SPACE_ITEM_NOT_FOUND", "空间内容不存在或已被删除")

    items = space.get("items", []) if isinstance(space.get("items"), list) else []
    target_item_id = str(item.get("id") or "").strip()
    space["items"] = [
        existing for existing in items
        if str((existing or {}).get("id") or "").strip() != target_item_id
    ]
    space["updatedAt"] = s.now_ms()
    s.set_user_space_payload(user_id, payload)
    s.invalidate_user_kb_cache(user_id)

    return jsonify(success_payload(
        request_id,
        message="空间内容已删除",
        user_id=user_id,
        deleted=True,
        itemId=target_item_id,
        spaceId=str(space.get("id") or "").strip(),
        space=serialize_space(space, user_id),
        error_code="",
        error_message="",
    ))


@spaces_bp.route("/items/<item_id>/preview", methods=["GET"])
def preview_space_item(item_id):
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = resolve_space_preview_user_id(item_id)
    if auth_error:
        return auth_error

    payload = s.get_user_space_payload(user_id)
    _, item = find_space_item(payload, item_id)
    if not item:
        return error_response(request_id, 404, "SPACE_ITEM_NOT_FOUND", "空间内容不存在或已被删除")

    data_url = str(item.get("audioDataUrl") or item.get("fileDataUrl") or "").strip()
    file_bytes = b""
    mime = str(item.get("mime") or "").strip()

    if data_url:
        file_bytes, decoded_mime = decode_space_data_url(data_url)
        mime = mime or decoded_mime or "application/octet-stream"
        if file_bytes:
            safe_name = requests.utils.quote(str(item.get("name") or "preview"), safe="")
            headers = {
                "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}",
                "Cache-Control": "private, max-age=600",
                "X-Request-Id": request_id,
            }
            return Response(file_bytes, mimetype=mime, headers=headers)

    text_content = str(item.get("content") or "")
    if text_content:
        safe_name = requests.utils.quote(str(item.get("name") or "preview.txt"), safe="")
        headers = {
            "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}",
            "Cache-Control": "private, max-age=600",
            "X-Request-Id": request_id,
        }
        return Response(text_content, content_type="text/plain; charset=utf-8", headers=headers)

    return error_response(request_id, 404, "SPACE_PREVIEW_NOT_AVAILABLE", "当前内容暂无可预览的原始文件")


@spaces_bp.route("/knowledge-points", methods=["GET"])
def list_space_knowledge_points():
    """汇总空间条目抽取出的知识点，供题库练习、学习仪表盘等模块复用。"""
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_current_request_user_id_from_args()
    if auth_error:
        return auth_error

    limit = max(1, min(200, int(request.args.get("limit", 60) or 60)))
    space_id_filter = str(request.args.get("space_id") or "").strip()
    payload = s.get_user_space_payload(user_id)

    points = []
    seen = set()
    legacy_budget = 40
    item_total = 0
    text_ready_total = 0
    for space in (payload.get("spaces", []) if isinstance(payload.get("spaces"), list) else []):
        if not isinstance(space, dict):
            continue
        space_id = str(space.get("id") or "").strip()
        if space_id_filter and space_id != space_id_filter:
            continue
        space_name = normalize_space_name(space.get("name"), "未命名空间")
        for item in (space.get("items", []) if isinstance(space.get("items"), list) else []):
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or "").strip().lower() == "folder":
                continue
            item_total += 1
            item_body = str(item.get("content") or "")
            if len(item_body.strip()) >= 20 and not looks_like_binary_text(item_body):
                text_ready_total += 1
            item_points = normalize_knowledge_point_list(item.get("knowledgePoints"))
            if not item_points:
                item_points = [
                    {"title": topic, "detail": topic, "weight": 0.3}
                    for topic in s.normalize_topic_list(item.get("topics"))[:6]
                    if not is_noise_knowledge_title(topic)
                ]
            if not item_points and legacy_budget > 0:
                # 兼容知识点字段上线前已上传的资料：按正文实时抽取
                legacy_budget -= 1
                legacy_text = str(item.get("content") or "")[:4000]
                item_points = extract_knowledge_points(legacy_text, limit=6) if len(legacy_text.strip()) >= 20 else []
                if not item_points and str(item.get("textExtractMethod") or "").startswith("image_ocr"):
                    item_points = build_content_sentence_points(legacy_text, limit=4)
            for index, point in enumerate(item_points):
                title = str(point.get("title") or "").strip()
                detail = str(point.get("detail") or title).strip()
                key = (title or detail).strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                points.append({
                    "id": f"{item.get('id') or ''}#{index}",
                    "title": title or detail[:20],
                    "detail": detail,
                    "weight": point.get("weight", 0.3),
                    "itemId": str(item.get("id") or "").strip(),
                    "itemName": str(item.get("name") or "未命名文件"),
                    "itemKind": str(item.get("kind") or "document"),
                    "spaceId": space_id,
                    "spaceName": space_name,
                    "addedAt": int(item.get("addedAt") or 0),
                    "extractMethod": str(item.get("textExtractMethod") or ""),
                })

    points.sort(key=lambda entry: int(entry.get("addedAt") or 0), reverse=True)
    return jsonify(success_payload(
        request_id,
        message="知识点汇总完成",
        user_id=user_id,
        total=len(points),
        item_total=item_total,
        text_ready=text_ready_total,
        points=points[:limit],
        error_code="",
        error_message="",
    ))


@spaces_bp.route("/search", methods=["GET"])
def search_space_items():
    """跨空间搜索资料条目。

    此前页面上没有任何检索入口，资料一旦变多只能靠肉眼翻。这里按标题、
    摘要与正文做包含匹配；不读取 fileDataUrl，避免把 base64 正文当文本搜。
    """
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_current_request_user_id_from_args()
    if auth_error:
        return auth_error

    query = str(request.args.get("q") or "").strip()[:60]
    if not query:
        return error_response(request_id, 400, "INVALID_INPUT", "请输入搜索关键词")

    try:
        limit = int(request.args.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = min(50, max(1, limit))

    payload = s.get_user_space_payload(user_id) or {}
    spaces = payload.get("spaces") if isinstance(payload.get("spaces"), list) else []
    needle = query.lower()

    results = []
    for space in spaces:
        if not isinstance(space, dict):
            continue

        space_id = str(space.get("id") or "")
        space_name = str(space.get("name") or "未命名空间")
        items = space.get("items") if isinstance(space.get("items"), list) else []

        for item in items:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name") or "")
            summary = str(item.get("summary") or "")
            content = str(item.get("content") or "")
            tags = item.get("tags") if isinstance(item.get("tags"), list) else []

            haystack = " ".join(
                [name, summary, content[:4000]] + [str(tag) for tag in tags if tag]
            ).lower()
            if needle not in haystack:
                continue

            hit_source = content or summary or name
            hit_index = hit_source.lower().find(needle)
            if hit_index >= 0:
                start = max(0, hit_index - 40)
                snippet = hit_source[start:start + 160]
            else:
                snippet = (summary or content or name)[:160]

            results.append({
                "space_id": space_id,
                "space_name": space_name,
                "item_id": str(item.get("id") or ""),
                "name": name,
                "kind": str(item.get("kind") or ""),
                "snippet": snippet.strip(),
                "updated_at": str(item.get("updatedAt") or item.get("updated_at") or ""),
            })

    results.sort(key=lambda row: row.get("updated_at") or "", reverse=True)

    return jsonify(success_payload(
        request_id,
        query=query,
        count=len(results),
        results=results[:limit],
        error_code="",
        error_message="",
    ))
