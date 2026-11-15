"""认证蓝图：注册 / 登录 / 会话 / 注销 / 删号。

包含认证相关的工具函数（账号/会话归一化与校验）与 5 个认证接口。

依赖说明：认证逻辑所需的存储层函数（get_auth_user / upsert_auth_user /
append_user_event 等）在 server 模块命名空间中定义或重导出，测试通过
patch server 模块来隔离存储。因此本模块通过 ``_server()`` 延迟获取这些
函数，避免直接 import 导致 patch 失效，同时规避 server -> 蓝图 -> server
的循环依赖。
"""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from ..config import (
    AUTH_TOKEN_TTL_DAYS,
    AUTH_TOUCH_INTERVAL_SECONDS,
    GUEST_USER_ID_PATTERN,
)
from ..utils.http import (
    error_response,
    get_request_id,
    iso_now,
    normalize_request_user_id,
    success_payload,
    utcnow,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _server():
    """延迟获取 server 模块，保持存储函数与测试 patch 的兼容。"""
    from .. import server
    return server


# ===== 认证工具函数 =====

def normalize_auth_username(value):
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.@-]{2,31}", text):
        return ""
    return text


def normalize_display_name(value, fallback="同学"):
    text = str(value or "").strip()
    if not text:
        text = str(fallback or "同学").strip() or "同学"
    return text[:24]


def normalize_auth_locale(value):
    locale = str(value or "").strip().upper()
    return "EN" if locale == "EN" else "CN"


def normalize_guest_binding_user_id(value, target_username=""):
    guest_user_id = str(value or "").strip()
    target_user_id = str(target_username or "").strip()
    if not guest_user_id or guest_user_id == target_user_id:
        return ""
    if guest_user_id == "default_user":
        return ""
    if not GUEST_USER_ID_PATTERN.fullmatch(guest_user_id):
        return ""
    if _server().get_auth_user(guest_user_id):
        return ""
    return guest_user_id


def hash_session_token(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def build_public_auth_user(user):
    if not isinstance(user, dict):
        return {
            "user_id": "",
            "username": "",
            "display_name": "同学",
            "locale": "CN",
        }

    username = str(user.get("username") or "").strip()
    return {
        "user_id": username,
        "username": username,
        "display_name": normalize_display_name(user.get("display_name"), fallback=username or "同学"),
        "locale": normalize_auth_locale(user.get("locale")),
        "created_at": str(user.get("created_at") or "").strip(),
        "updated_at": str(user.get("updated_at") or "").strip(),
        "last_login_at": str(user.get("last_login_at") or "").strip(),
    }


def create_auth_session_payload(user):
    now = utcnow()
    expires_at = now + timedelta(days=AUTH_TOKEN_TTL_DAYS)
    raw_token = secrets.token_urlsafe(32)
    session_data = {
        "session_id": uuid.uuid4().hex,
        "username": str(user.get("username") or "").strip(),
        "token_hash": hash_session_token(raw_token),
        "expires_at": expires_at.isoformat(),
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "revoked_at": None,
    }
    _server().upsert_auth_session(session_data)
    return {
        "token": raw_token,
        "expires_at": session_data["expires_at"],
        "session_id": session_data["session_id"],
    }


def extract_bearer_token():
    auth_header = (request.headers.get("Authorization", "") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    return ""


def resolve_auth_context(touch=False):
    server = _server()
    token = extract_bearer_token()
    if not token:
        return None

    token_hash = hash_session_token(token)
    session_data = server.get_auth_session_by_token_hash(token_hash)
    if not session_data:
        return None

    if session_data.get("revoked_at"):
        return None

    expires_at = session_data.get("expires_at")
    try:
        expires_dt = datetime.fromisoformat(expires_at) if expires_at else None
    except Exception:
        expires_dt = None

    if not expires_dt or expires_dt <= utcnow():
        server.revoke_auth_session(token_hash, iso_now())
        return None

    user = server.get_auth_user(session_data.get("username", ""))
    if not user:
        return None

    if touch:
        last_seen = session_data.get("last_seen_at")
        try:
            last_seen_dt = datetime.fromisoformat(last_seen) if last_seen else None
        except Exception:
            last_seen_dt = None
        if (not last_seen_dt) or ((utcnow() - last_seen_dt).total_seconds() >= AUTH_TOUCH_INTERVAL_SECONDS):
            server.touch_auth_session(token_hash, iso_now())

    return {
        "token": token,
        "token_hash": token_hash,
        "session": session_data,
        "user": user,
    }


def require_auth_context():
    auth_context = resolve_auth_context(touch=True)
    if auth_context:
        return auth_context, None

    return None, error_response(
        get_request_id(),
        401,
        "AUTH_REQUIRED",
        "请先登录后再访问",
    )


def build_auth_register_binding_summary(target_user_id):
    return {
        "guest_user_id": "",
        "user_id": normalize_request_user_id(target_user_id, fallback=""),
        "migrated": False,
        "plans": 0,
        "spaces": 0,
        "space_items": 0,
        "concepts": 0,
        "relations": 0,
        "knowledge_updated": False,
        "events": 0,
        "message": "新账号默认不自动继承访客数据",
    }


def build_auth_login_binding_summary(target_user_id):
    return {
        "guest_user_id": "",
        "user_id": normalize_request_user_id(target_user_id, fallback=""),
        "migrated": False,
        "plans": 0,
        "spaces": 0,
        "space_items": 0,
        "concepts": 0,
        "relations": 0,
        "knowledge_updated": False,
        "events": 0,
        "message": "登录后默认使用账号自己的学习数据",
    }


def append_auth_login_behavior(user_id, source):
    user_key = str(user_id or "").strip()
    if not user_key:
        return

    _server().append_user_event(user_key, "behavior", {
        "id": str(uuid.uuid4()),
        "user_id": user_key,
        "timestamp": datetime.now().isoformat(),
        "type": "auth_login",
        "behavior_type": "auth_login",
        "page": "auth",
        "target": "",
        "label": "账号登录",
        "title": "auth_login",
        "source": str(source or "auth").strip() or "auth",
        "duration_seconds": 0.0,
        "meta": {},
    })


# ===== 认证路由 =====

@auth_bp.route("/register", methods=["POST"])
def register_auth_user_api():
    """注册账号并创建登录会话。"""
    server = _server()
    request_id = get_request_id()
    data = request.get_json(silent=True) or {}
    username = normalize_auth_username(data.get("username"))
    password = str(data.get("password") or "")
    display_name = normalize_display_name(data.get("display_name"), fallback=username or "同学")
    locale = normalize_auth_locale(data.get("locale"))

    if not username:
        return error_response(request_id, 400, "INVALID_INPUT", "账号格式不正确，请使用 3-32 位字母、数字或 . _ @ -")
    if len(password) < 6:
        return error_response(request_id, 400, "INVALID_INPUT", "密码长度至少需要 6 位")
    if server.get_auth_user(username):
        return error_response(request_id, 409, "AUTH_USER_EXISTS", "该账号已存在，请直接登录")
    if server.get_auth_user_by_display_name(display_name):
        return error_response(request_id, 409, "AUTH_DISPLAY_NAME_EXISTS", "该昵称已被使用，请更换一个昵称")

    now = iso_now()
    user = {
        "username": username,
        "display_name": display_name,
        "password_hash": generate_password_hash(password),
        "locale": locale,
        "created_at": now,
        "updated_at": now,
        "last_login_at": now,
    }
    saved_user = server.upsert_auth_user(user)
    session_bundle = create_auth_session_payload(saved_user)
    binding = build_auth_register_binding_summary(username)
    append_auth_login_behavior(username, "auth_register")

    return jsonify(success_payload(
        request_id,
        message="注册成功",
        auth={
            "authenticated": True,
            "user": build_public_auth_user(saved_user),
            "token": session_bundle["token"],
            "expires_at": session_bundle["expires_at"],
            "session_id": session_bundle["session_id"],
        },
        binding=binding,
        error_code="",
        error_message="",
    ))


@auth_bp.route("/login", methods=["POST"])
def login_auth_user_api():
    """账号登录并签发 Bearer token。"""
    server = _server()
    request_id = get_request_id()
    data = request.get_json(silent=True) or {}
    username = normalize_auth_username(data.get("username"))
    password = str(data.get("password") or "")

    if not username or not password:
        return error_response(request_id, 400, "INVALID_INPUT", "请输入账号和密码")

    user = server.get_auth_user(username)
    if not user or not check_password_hash(str(user.get("password_hash") or ""), password):
        return error_response(request_id, 401, "AUTH_INVALID_CREDENTIALS", "账号或密码错误")

    user["last_login_at"] = iso_now()
    user["updated_at"] = iso_now()
    saved_user = server.upsert_auth_user(user)
    session_bundle = create_auth_session_payload(saved_user)
    binding = build_auth_login_binding_summary(username)
    append_auth_login_behavior(username, "auth_login")

    return jsonify(success_payload(
        request_id,
        message="登录成功",
        auth={
            "authenticated": True,
            "user": build_public_auth_user(saved_user),
            "token": session_bundle["token"],
            "expires_at": session_bundle["expires_at"],
            "session_id": session_bundle["session_id"],
        },
        binding=binding,
        error_code="",
        error_message="",
    ))


@auth_bp.route("/me", methods=["GET"])
def current_auth_user_api():
    """获取当前登录用户信息。"""
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=True)
    if not auth_context:
        return error_response(request_id, 401, "AUTH_REQUIRED", "当前登录状态已失效，请重新登录")

    return jsonify(success_payload(
        request_id,
        auth={
            "authenticated": True,
            "user": build_public_auth_user(auth_context["user"]),
            "expires_at": auth_context["session"].get("expires_at"),
            "session_id": auth_context["session"].get("session_id"),
        },
        error_code="",
        error_message="",
    ))


@auth_bp.route("/logout", methods=["POST"])
def logout_auth_user_api():
    """退出当前登录会话。"""
    server = _server()
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=False)
    if auth_context:
        server.revoke_auth_session(auth_context["token_hash"], iso_now())

    return jsonify(success_payload(
        request_id,
        message="已退出登录",
        logged_out=True,
        error_code="",
        error_message="",
    ))


@auth_bp.route("/account", methods=["DELETE"])
def delete_auth_user_account_api():
    """删除当前登录账号及其关联学习数据。"""
    server = _server()
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=False)
    if not auth_context:
        return error_response(request_id, 401, "AUTH_REQUIRED", "当前登录状态已失效，请重新登录")

    username = normalize_auth_username((auth_context.get("user") or {}).get("username"))
    if not username:
        return error_response(request_id, 400, "INVALID_INPUT", "当前账号信息不完整，无法删除")

    cleanup = server.delete_auth_user_account(username)
    if not cleanup.get("auth_user_deleted"):
        return error_response(request_id, 500, "AUTH_DELETE_FAILED", "删除账户失败，请稍后重试")

    graph_cleanup_attempted = bool(server.neo4j_store.ensure_connected())
    graph_deleted = False
    if graph_cleanup_attempted:
        try:
            graph_deleted = bool(server.neo4j_store.delete_user_graph(username))
        except Exception as exc:
            server.logger.exception("failed to delete neo4j user graph for %s: %s", username, exc)
            graph_deleted = False

    return jsonify(success_payload(
        request_id,
        message="账户已删除",
        deleted_account=True,
        user_id=username,
        cleanup={
            **cleanup,
            "graph_cleanup_attempted": graph_cleanup_attempted,
            "graph_deleted": graph_deleted,
        },
        error_code="",
        error_message="",
    ))
