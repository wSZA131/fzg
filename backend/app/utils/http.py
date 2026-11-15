"""HTTP / 通用工具函数：请求 ID、响应封装、时间与身份归一化。

这些函数被多个路由模块共享，不依赖应用级全局状态（app、celery_client、
neo4j_store 等），可被任意模块安全导入，避免蓝图与 server 之间的循环依赖。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from flask import jsonify, request


def get_request_id():
    """获取或生成请求追踪ID。"""
    req_id = (request.headers.get("X-Request-Id", "") or "").strip()
    if req_id:
        return req_id

    req_id = (request.args.get("request_id", "") or "").strip()
    if req_id:
        return req_id

    body = request.get_json(silent=True) or {}
    req_id = str(body.get("request_id", "") or "").strip()
    if req_id:
        return req_id

    return str(uuid.uuid4())


def success_payload(request_id, message="", **data):
    payload = {
        "success": True,
        "request_id": request_id,
    }
    if message:
        payload["message"] = message
    payload.update(data)
    return payload


def error_response(request_id, status_code, error_code, error_message, **data):
    payload = {
        "success": False,
        "request_id": request_id,
        "error_code": error_code,
        "error_message": error_message,
        "message": error_message,
    }
    payload.update(data)
    return jsonify(payload), status_code


def utcnow():
    return datetime.utcnow()


def iso_now():
    return utcnow().isoformat()


def normalize_request_user_id(value, fallback=""):
    text = str(value or "").strip()
    if text:
        return text
    return str(fallback or "").strip()
