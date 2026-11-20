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
import threading
import time
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from ..config import (
    AUTH_TOKEN_TTL_DAYS,
    AUTH_TOUCH_INTERVAL_SECONDS,
    GUEST_USER_ID_PATTERN,
)
from ..services import auth_credentials
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


# ===== 密码强度与登录防护 =====

PASSWORD_MIN_LENGTH = 8
_LOGIN_LOCK_THRESHOLD = 5
_LOGIN_LOCK_SECONDS = 10 * 60

_login_failures = {}
_login_failures_lock = threading.Lock()


def validate_password_strength(password):
    """注册 / 改密 / 重置时使用；登录不做校验，以兼容历史账号。"""
    text = str(password or "")
    if len(text) < PASSWORD_MIN_LENGTH:
        return f"密码长度至少需要 {PASSWORD_MIN_LENGTH} 位"
    if not re.search(r"[A-Za-z]", text):
        return "密码需要包含字母"
    if not re.search(r"\d", text):
        return "密码需要包含数字"
    return ""


def check_login_locked(username):
    """返回 (是否锁定, 剩余秒数)。"""
    key = str(username or "").strip()
    if not key:
        return False, 0
    with _login_failures_lock:
        record = _login_failures.get(key)
        if not record:
            return False, 0
        remaining = float(record.get("locked_until") or 0) - time.time()
        return (True, remaining) if remaining > 0 else (False, 0)


def record_login_failure(username):
    key = str(username or "").strip()
    if not key:
        return
    with _login_failures_lock:
        record = _login_failures.setdefault(key, {"count": 0, "locked_until": 0.0})
        record["count"] = int(record.get("count") or 0) + 1
        if record["count"] >= _LOGIN_LOCK_THRESHOLD:
            record["locked_until"] = time.time() + _LOGIN_LOCK_SECONDS
            record["count"] = 0


def clear_login_failures(username):
    key = str(username or "").strip()
    if not key:
        return
    with _login_failures_lock:
        _login_failures.pop(key, None)


def reset_login_state():
    """测试辅助：清空账号锁定计数。"""
    with _login_failures_lock:
        _login_failures.clear()


def bind_guest_learning_data(guest_user_id, target_user_id, empty_message):
    """把访客期间的学习数据真实迁移到账号。

    历史上这里返回的是硬编码的空壳结果，导致「游客绑定」只有名目没有实际行为。
    现在直接调用 server 的合并实现，并在无可迁移数据时给出说明。
    """
    server = _server()
    normalized_guest = normalize_guest_binding_user_id(guest_user_id, target_user_id)
    empty_summary = {
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
        "message": empty_message,
    }
    if not normalized_guest:
        return empty_summary

    summary = server.bind_guest_user_data_to_auth_user(normalized_guest, target_user_id)
    if not summary.get("message"):
        summary["message"] = "已继承访客期间的学习数据" if summary.get("migrated") else "访客数据为空，无需迁移"
    return summary


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
        "bio": str(user.get("bio") or "")[:500],
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

    strength_error = validate_password_strength(password)
    if strength_error:
        return error_response(request_id, 400, "WEAK_PASSWORD", strength_error)

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
    binding = bind_guest_learning_data(
        data.get("guest_user_id"),
        username,
        "新账号默认不自动继承访客数据",
    )
    recovery_code = auth_credentials.issue(username)
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
        recovery_code=recovery_code,
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

    locked, remaining = check_login_locked(username)
    if locked:
        minutes = int(remaining // 60) + 1
        return error_response(
            request_id,
            429,
            "AUTH_LOCKED",
            f"该账号连续登录失败次数过多，请 {minutes} 分钟后再试",
        )

    user = server.get_auth_user(username)
    if not user or not check_password_hash(str(user.get("password_hash") or ""), password):
        record_login_failure(username)
        locked_now, remaining_now = check_login_locked(username)
        if locked_now:
            return error_response(
                request_id,
                429,
                "AUTH_LOCKED",
                "连续登录失败次数过多，该账号已锁定 10 分钟",
            )
        return error_response(request_id, 401, "AUTH_INVALID_CREDENTIALS", "账号或密码错误")

    clear_login_failures(username)
    user["last_login_at"] = iso_now()
    user["updated_at"] = iso_now()
    saved_user = server.upsert_auth_user(user)
    session_bundle = create_auth_session_payload(saved_user)

    # 登录默认不合并访客数据：公共设备上前一位访客的进度不应污染账号。
    # 只有前端明确提示并取得用户确认后，才带 adopt_guest_data=true 触发迁移。
    adopt_guest = data.get("adopt_guest_data") is True
    binding = bind_guest_learning_data(
        data.get("guest_user_id") if adopt_guest else "",
        username,
        "已开启访客数据继承，但没有可迁移的数据" if adopt_guest else "登录后默认使用账号自己的学习数据",
    )
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


@auth_bp.route("/profile", methods=["PUT", "POST"])
def update_auth_profile_api():
    """修改当前账号的昵称与界面语言。"""
    server = _server()
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=False)
    if not auth_context:
        return error_response(request_id, 401, "AUTH_REQUIRED", "当前登录状态已失效，请重新登录")

    data = request.get_json(silent=True) or {}
    user = auth_context["user"]
    username = str(user.get("username") or "")
    changed = False

    if "display_name" in data:
        display_name = normalize_display_name(
            data.get("display_name"),
            fallback=user.get("display_name") or username,
        )
        existing = server.get_auth_user_by_display_name(display_name)
        if existing and str(existing.get("username") or "") != username:
            return error_response(
                request_id,
                409,
                "AUTH_DISPLAY_NAME_EXISTS",
                "该昵称已被使用，请更换一个昵称",
            )
        if display_name != str(user.get("display_name") or ""):
            user["display_name"] = display_name
            changed = True

    if "bio" in data:
        bio = str(data.get("bio") or "").strip()[:500]
        if bio != str(user.get("bio") or ""):
            user["bio"] = bio
            changed = True

    if "locale" in data:
        locale = normalize_auth_locale(data.get("locale"))
        if locale != str(user.get("locale") or ""):
            user["locale"] = locale
            changed = True

    if changed:
        user["updated_at"] = iso_now()
        user = server.upsert_auth_user(user)

    return jsonify(success_payload(
        request_id,
        message="资料已更新" if changed else "没有需要更新的内容",
        user=build_public_auth_user(user),
        error_code="",
        error_message="",
    ))


# ===== 密码与凭证管理 =====

@auth_bp.route("/change-password", methods=["POST"])
def change_password_api():
    """修改密码，成功后撤销该账号的其他登录会话。"""
    server = _server()
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=False)
    if not auth_context:
        return error_response(request_id, 401, "AUTH_REQUIRED", "当前登录状态已失效，请重新登录")

    data = request.get_json(silent=True) or {}
    old_password = str(data.get("old_password") or "")
    new_password = str(data.get("new_password") or "")
    if not old_password or not new_password:
        return error_response(request_id, 400, "INVALID_INPUT", "请填写当前密码和新密码")

    user = auth_context["user"]
    if not check_password_hash(str(user.get("password_hash") or ""), old_password):
        return error_response(request_id, 401, "AUTH_INVALID_CREDENTIALS", "当前密码不正确")

    strength_error = validate_password_strength(new_password)
    if strength_error:
        return error_response(request_id, 400, "WEAK_PASSWORD", strength_error)
    if old_password == new_password:
        return error_response(request_id, 400, "INVALID_INPUT", "新密码不能与当前密码相同")

    user["password_hash"] = generate_password_hash(new_password)
    user["updated_at"] = iso_now()
    server.upsert_auth_user(user)

    revoked = server.revoke_other_auth_sessions(
        str(user.get("username") or ""),
        auth_context["token_hash"],
        iso_now(),
    )

    return jsonify(success_payload(
        request_id,
        message="密码已更新，其他设备需重新登录",
        revoked_sessions=revoked,
        error_code="",
        error_message="",
    ))


@auth_bp.route("/recovery/issue", methods=["POST"])
def issue_recovery_code_api():
    """签发或重发恢复码；旧恢复码立即失效。"""
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=False)
    if not auth_context:
        return error_response(request_id, 401, "AUTH_REQUIRED", "请先登录后再生成恢复码")

    username = str((auth_context.get("user") or {}).get("username") or "")
    code = auth_credentials.issue(username)
    if not code:
        return error_response(request_id, 500, "RECOVERY_ISSUE_FAILED", "生成恢复码失败，请稍后重试")

    return jsonify(success_payload(
        request_id,
        message="恢复码已生成，旧恢复码立即失效",
        recovery_code=code,
        error_code="",
        error_message="",
    ))


@auth_bp.route("/recovery/reset", methods=["POST"])
def reset_password_with_recovery_api():
    """凭恢复码重置密码，无需登录。重置后旧会话全部失效。"""
    server = _server()
    request_id = get_request_id()
    data = request.get_json(silent=True) or {}
    username = normalize_auth_username(data.get("username"))
    recovery_code = str(data.get("recovery_code") or "")
    new_password = str(data.get("new_password") or "")

    if not username:
        return error_response(request_id, 400, "INVALID_INPUT", "请输入账号")

    strength_error = validate_password_strength(new_password)
    if strength_error:
        return error_response(request_id, 400, "WEAK_PASSWORD", strength_error)

    user = server.get_auth_user(username)
    if not user:
        # 不区分「账号不存在」与「恢复码错误」，避免账号枚举
        return error_response(request_id, 400, "RECOVERY_FAILED", "账号或恢复码不正确")

    ok, message = auth_credentials.verify(username, recovery_code)
    if not ok:
        return error_response(request_id, 400, "RECOVERY_FAILED", message)

    user["password_hash"] = generate_password_hash(new_password)
    user["updated_at"] = iso_now()
    server.upsert_auth_user(user)

    revoked = server.revoke_other_auth_sessions(username, "", iso_now())
    new_code = auth_credentials.issue(username)
    clear_login_failures(username)

    return jsonify(success_payload(
        request_id,
        message="密码已重置，请使用新密码登录",
        revoked_sessions=revoked,
        recovery_code=new_code,
        error_code="",
        error_message="",
    ))


# ===== 登录设备管理 =====

def _is_session_active(item, now):
    if not isinstance(item, dict):
        return False
    if item.get("revoked_at"):
        return False
    expires_at = item.get("expires_at")
    if not expires_at:
        return True
    try:
        return datetime.fromisoformat(expires_at) > now
    except Exception:
        return True


@auth_bp.route("/sessions", methods=["GET"])
def list_auth_sessions_api():
    """列出当前账号的活跃登录设备。"""
    server = _server()
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=False)
    if not auth_context:
        return error_response(request_id, 401, "AUTH_REQUIRED", "请先登录后再查看登录设备")

    username = str((auth_context.get("user") or {}).get("username") or "")
    current_hash = auth_context["token_hash"]
    now = utcnow()

    sessions = []
    for item in server.list_auth_sessions(username) or []:
        if not _is_session_active(item, now):
            continue
        sessions.append({
            "session_id": item.get("session_id"),
            "created_at": item.get("created_at"),
            "last_seen_at": item.get("last_seen_at"),
            "expires_at": item.get("expires_at"),
            "current": str(item.get("token_hash") or "") == current_hash,
        })

    sessions.sort(key=lambda row: str(row.get("last_seen_at") or ""), reverse=True)

    return jsonify(success_payload(
        request_id,
        message="",
        sessions=sessions,
        total=len(sessions),
        error_code="",
        error_message="",
    ))


@auth_bp.route("/sessions/revoke", methods=["POST"])
def revoke_auth_sessions_api():
    """退出指定设备，或一次性退出其他所有设备。"""
    server = _server()
    request_id = get_request_id()
    auth_context = resolve_auth_context(touch=False)
    if not auth_context:
        return error_response(request_id, 401, "AUTH_REQUIRED", "请先登录后再操作")

    data = request.get_json(silent=True) or {}
    username = str((auth_context.get("user") or {}).get("username") or "")
    current_hash = auth_context["token_hash"]

    if data.get("all_others"):
        revoked = server.revoke_other_auth_sessions(username, current_hash, iso_now())
        return jsonify(success_payload(
            request_id,
            message=f"已退出其他 {revoked} 个设备",
            revoked=revoked,
            error_code="",
            error_message="",
        ))

    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        return error_response(request_id, 400, "INVALID_INPUT", "请选择要退出的设备")

    target = None
    for item in server.list_auth_sessions(username) or []:
        if str(item.get("session_id") or "") == session_id:
            target = item
            break

    if not target:
        return error_response(request_id, 404, "SESSION_NOT_FOUND", "该设备不存在或已退出")
    if str(target.get("token_hash") or "") == current_hash:
        return error_response(request_id, 400, "INVALID_INPUT", "退出当前设备请使用退出登录")

    server.revoke_auth_session(str(target.get("token_hash") or ""), iso_now())

    return jsonify(success_payload(
        request_id,
        message="该设备已退出",
        revoked=1,
        error_code="",
        error_message="",
    ))
