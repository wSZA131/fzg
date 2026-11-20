# syntax=docker/dockerfile:1
# 坊知工 FZG - 单镜像同时提供 Flask API 与前端静态页面（端口 5000）
# 构建上下文为仓库根目录：docker build -f deploy/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8

# 国内网络默认走华为云镜像；海外环境可用 --build-arg 覆盖
ARG PIP_INDEX_URL=https://repo.huaweicloud.com/repository/pypi/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG HF_ENDPOINT=https://hf-mirror.com
ARG PREFETCH_EMBEDDING_MODEL=true
# 低内存机型（≤2 GB）用 --build-arg LITE_MODE=true：
# 跳过 torch 与 BGE 模型，镜像约 400 MB，运行内存约 700-900 MB，
# 检索退化为 TF-IDF + FAISS，仍可覆盖完整知识库。
ARG LITE_MODE=false

WORKDIR /app

# libgomp1：faiss / torch / onnxruntime 运行时依赖
# libglib2.0-0：本地 OCR（opencv）运行时依赖
# curl：容器健康检查
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖，利用构建缓存
COPY backend/requirements.txt backend/requirements.txt
COPY backend/requirements.lite.txt backend/requirements.lite.txt
RUN if [ "${LITE_MODE}" = "true" ]; then \
        echo "[build] LITE_MODE: 跳过 torch，检索走 TF-IDF + FAISS"; \
        pip install --index-url "${PIP_INDEX_URL}" -r backend/requirements.lite.txt; \
    else \
        pip install --index-url "${TORCH_INDEX_URL}" torch \
        && pip install --index-url "${PIP_INDEX_URL}" -r backend/requirements.txt; \
    fi

# 预下载中文向量模型，避免容器首次启动时联网拉取（离线演示必需）
ENV HF_ENDPOINT=${HF_ENDPOINT} \
    SENTENCE_TRANSFORMERS_HOME=/opt/models \
    HF_HOME=/opt/models/hf
RUN if [ "${PREFETCH_EMBEDDING_MODEL}" = "true" ] && [ "${LITE_MODE}" != "true" ]; then \
        python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"; \
    fi

# 代码与前端资源（knowledge base 制品通过 Git LFS 管理，构建前需 git lfs pull）
COPY backend ./backend
COPY frontend ./frontend

# 运行期可写的目录：知识库制品、用户状态、日志
RUN mkdir -p /app/backend/data /app/backend/logs /app/backend/run \
    && useradd -m -u 10001 fzg \
    && chown -R fzg:fzg /app

USER fzg
WORKDIR /app/backend

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
    CMD curl -fsS http://127.0.0.1:5000/health >/dev/null || exit 1

CMD ["python", "-m", "app.server"]
