"""应用配置：集中管理路径常量、.env 加载与环境变量派生配置。

所有配置在模块导入时求值一次。模块会先加载本地 .env 文件（仅填充尚未
设置的环境变量），再统一派生各配置项，从而保证 secret_key / CORS / AI 等
所有配置都能读到 .env 中的值（修复原先部分配置在 .env 加载前就求值的问题）。
该模块不依赖 Flask 应用上下文，可被任意模块安全导入。
"""
from __future__ import annotations

import os
import re
import secrets

# ---- 路径（不依赖 .env，需在 _load_env_files 之前定义） ----
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DATA_DIR = os.path.join(BACKEND_DIR, "data")
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)


def _load_env_files() -> None:
    """读取本地 .env 文件，仅填充尚未设置的环境变量。失败时不影响启动。"""
    candidates = [
        os.path.join(BACKEND_DIR, "config", ".env"),
        os.path.join(BACKEND_DIR, ".env"),
        os.path.join(PROJECT_ROOT, ".env"),
    ]

    for env_path in candidates:
        if not os.path.exists(env_path):
            continue

        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue

                    if line.startswith("export "):
                        line = line[len("export "):].strip()

                    key, value = line.split("=", 1)
                    key = key.strip()

                    value = value.strip()
                    if value and not (value.startswith('"') or value.startswith("'")) and " #" in value:
                        value = value.split(" #", 1)[0].rstrip()
                    value = value.strip().strip('"').strip("'")

                    if key and not os.getenv(key):
                        os.environ[key] = value
        except Exception:
            # .env 加载失败时不影响服务启动
            continue


_load_env_files()

# ---- 签名密钥（会话签名 / Cookie 序列化） ----
SIGNING_SECRET = (
    os.getenv("APP_SIGNING_SECRET")
    or os.getenv("SECRET_KEY")
    or os.getenv("FLASK_SECRET_KEY")
    or secrets.token_hex(32)
)

# ---- CORS 白名单：默认只放行本地开发端口，线上通过 CORS_ALLOWED_ORIGINS 显式配置 ----
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
] or [
    "http://127.0.0.1:5000",
    "http://localhost:5000",
    "http://127.0.0.1:5501",
    "http://localhost:5501",
]

# ---- 认证与会话 ----
AUTH_TOKEN_TTL_DAYS = max(1, int(os.getenv("AUTH_TOKEN_TTL_DAYS", "14")))
AUTH_TOUCH_INTERVAL_SECONDS = 300
AUTH_BINDABLE_EVENT_SUFFIXES = (
    "content",
    "diagnosis",
    "behavior",
    "qa",
    "question_draw",
    "question_answer",
)
GUEST_USER_ID_PATTERN = re.compile(r"^guest_[a-z0-9]{8,40}$")
GUEST_SESSION_COOKIE_NAME = os.getenv("GUEST_SESSION_COOKIE_NAME", "fangzhigong_guest_session")
GUEST_SESSION_COOKIE_SALT = "fangzhigong-guest-session-v1"

# ---- 学习空间 ----
SPACE_PREVIEW_TOKEN_SALT = "fangzhigong-space-preview-v1"
SPACE_PREVIEW_SIGNATURE_QUERY_PARAM = "preview_signature"
SPACE_PREVIEW_TOKEN_TTL_SECONDS = max(60, int(os.getenv("SPACE_PREVIEW_TOKEN_TTL_SECONDS", "900")))
SPACE_MAX_ITEM_COUNT = max(20, int(os.getenv("SPACE_MAX_ITEM_COUNT", "200")))
SPACE_MAX_FILE_BYTES = max(1024, int(os.getenv("SPACE_MAX_FILE_BYTES", "10485760")))
LEARNING_CONTENT_MAX_CHARS = max(2000, int(os.getenv("LEARNING_CONTENT_MAX_CHARS", "120000")))
LEARNING_CONTENT_PREVIEW_CHARS = max(160, int(os.getenv("LEARNING_CONTENT_PREVIEW_CHARS", "500")))
LOCAL_DEMO_FALLBACK_ENABLED = str(os.getenv("LOCAL_DEMO_FALLBACK_ENABLED", "true")).strip().lower() == "true"

# ---- 大模型（MaaS / 通义千问 / DeepSeek） ----
AI_PROVIDER = os.getenv("AI_PROVIDER", "qwen").lower()
USE_REAL_AI = os.getenv("USE_REAL_AI", "true").lower() == "true"
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_API_URL = os.getenv(
    "QWEN_API_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
)
QWEN_MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "qwen-plus")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")

# ---- OCR / 知识图谱 ----
OCR_PROVIDER = os.getenv("OCR_PROVIDER", "mock").lower()  # mock|qwen_vl
QWEN_VL_MODEL_NAME = os.getenv("QWEN_VL_MODEL_NAME", "qwen-vl-plus")
GRAPH_PRIMARY = os.getenv("GRAPH_PRIMARY", "auto").strip().lower()  # auto|neo4j|json
GRAPH_SYNC_MODE = os.getenv("GRAPH_SYNC_MODE", "auto").strip().lower()  # auto|sync|async
RELATION_MIN_SCORE = float(os.getenv("RELATION_MIN_SCORE", "0.45"))
