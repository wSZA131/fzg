"""账号恢复凭证（恢复码）存储。

为什么不放进 auth_users 表：项目没有迁移框架，为一次性凭证改动主体表
需要同时改 ORM、SQL 建表与 JSON 仓储；恢复码属于低频、可重建的旁路数据，
单独落一个 JSON 文件风险更低，JSON / SQL 两种仓储下行为也一致。

安全约束：
- 只存哈希，不存明文；接口在签发时返回一次明文，之后无法再取回；
- 校验失败累计 5 次锁定 15 分钟，避免离线爆破 8 位码空间；
- 使用 secrets.compare_digest 做恒定时间比较。
"""

import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone

from ..config import BACKEND_DATA_DIR

_FILE_PATH = os.path.join(BACKEND_DATA_DIR, "auth_credentials.json")
_LOCK = threading.Lock()

# 去掉形近字符（I/O/0/1），降低用户手抄出错概率
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_GROUP_SIZE = 4
_GROUP_COUNT = 2

MAX_VERIFY_FAILURES = 5
VERIFY_LOCK_SECONDS = 15 * 60


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _normalize_username(username):
    return str(username or "").strip().lower()


def _normalize_code(code):
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def _hash_code(username, code):
    # 以账号作为盐，避免不同账号的同码互相命中
    payload = f"{_normalize_username(username)}::{_normalize_code(code)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_all():
    try:
        with open(_FILE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_all(data):
    os.makedirs(os.path.dirname(_FILE_PATH), exist_ok=True)
    tmp_path = _FILE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, _FILE_PATH)


def generate_code():
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_SIZE))
        for _ in range(_GROUP_COUNT)
    ]
    return "-".join(groups)


def issue(username):
    """签发或重发恢复码，返回明文；旧恢复码立即失效。"""
    key = _normalize_username(username)
    if not key:
        return ""

    code = generate_code()
    with _LOCK:
        data = _read_all()
        record = data.get(key) if isinstance(data.get(key), dict) else {}
        record.update(
            {
                "recovery_code_hash": _hash_code(key, code),
                "issued_at": _now_iso(),
                "updated_at": _now_iso(),
                "failed_attempts": 0,
                "locked_until": 0,
            }
        )
        data[key] = record
        _write_all(data)
    return code


def has_code(username):
    with _LOCK:
        record = _read_all().get(_normalize_username(username))
    return bool(isinstance(record, dict) and record.get("recovery_code_hash"))


def verify(username, code):
    """校验恢复码，返回 (是否通过, 提示语)。"""
    key = _normalize_username(username)
    if not key:
        return False, "请输入账号"
    if not _normalize_code(code):
        return False, "请输入恢复码"

    with _LOCK:
        data = _read_all()
        record = data.get(key)
        if not isinstance(record, dict) or not record.get("recovery_code_hash"):
            return False, "该账号未设置恢复码，请联系管理员重置密码"

        now = time.time()
        locked_until = float(record.get("locked_until") or 0)
        if locked_until > now:
            minutes = int((locked_until - now) // 60) + 1
            return False, f"尝试次数过多，请 {minutes} 分钟后再试"

        if secrets.compare_digest(str(record["recovery_code_hash"]), _hash_code(key, code)):
            record["failed_attempts"] = 0
            record["locked_until"] = 0
            record["updated_at"] = _now_iso()
            data[key] = record
            _write_all(data)
            return True, ""

        failures = int(record.get("failed_attempts") or 0) + 1
        if failures >= MAX_VERIFY_FAILURES:
            record["failed_attempts"] = 0
            record["locked_until"] = now + VERIFY_LOCK_SECONDS
            data[key] = record
            _write_all(data)
            return False, "恢复码错误次数过多，已锁定 15 分钟"

        record["failed_attempts"] = failures
        data[key] = record
        _write_all(data)
        return False, f"恢复码不正确，还可尝试 {MAX_VERIFY_FAILURES - failures} 次"


def clear(username):
    key = _normalize_username(username)
    with _LOCK:
        data = _read_all()
        if key in data:
            data.pop(key, None)
            _write_all(data)
