#!/usr/bin/env bash
# 坊知工 FZG 一键部署（华为云 ECS / 任意 Docker 主机）
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
cd "$DEPLOY_DIR"

info()  { printf '\033[32m[info]\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
fail()  { printf '\033[31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    fail "未找到 docker compose，请先安装 Docker Engine 与 Compose 插件"
  fi
}

command -v docker >/dev/null 2>&1 || fail "未安装 Docker，请先执行华为云 ECS 的 Docker 安装脚本"
docker info >/dev/null 2>&1 || fail "Docker 守护进程不可用（尝试 sudo systemctl start docker）"

# 1) 环境变量文件
if [[ ! -f .env ]]; then
  cp .env.example .env
  secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))' 2>/dev/null || openssl rand -hex 32)"
  sed -i.bak "s|^FLASK_SECRET_KEY=.*|FLASK_SECRET_KEY=${secret}|" .env && rm -f .env.bak
  warn "已由 .env.example 生成 deploy/.env，并写入随机 FLASK_SECRET_KEY"
  warn "请填写 QWEN_API_KEY（MaaS 密钥）及 DATABASE_URL / REDIS_URL / NEO4J_* 后重新执行本脚本"
  exit 0
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

# 2) 知识库制品检查（Git LFS 指针会导致 RAG 能力降级）
if grep -rqs "git-lfs.github.com/spec/v1" "$ROOT_DIR/backend/data/pro_kb" 2>/dev/null; then
  fail "backend/data/pro_kb 仍是 Git LFS 指针文件。请先在仓库根目录执行：git lfs install && git lfs pull"
fi
[[ -s "$ROOT_DIR/backend/data/pro_kb/pro_kb_faiss.index" ]] || warn "未找到 pro_kb_faiss.index，系统将回落到 TF-IDF / 演示知识库模式"

# 3) 模型与密钥检查
if [[ "${USE_REAL_AI:-true}" == "true" && -z "${QWEN_API_KEY:-}" && -z "${DEEPSEEK_API_KEY:-}" ]]; then
  warn "未配置大模型密钥，智能体将走离线兜底回答（演示可用，答辩建议接入 MaaS）"
fi

# 4) 构建并启动
info "开始构建镜像（首次构建需下载 torch 与向量模型，约 5-15 分钟）"
compose build app
info "启动服务"
if [[ "${ENABLE_ASYNC:-false}" == "true" ]]; then
  compose --profile async up -d --remove-orphans
else
  compose up -d --remove-orphans
fi

# 5) 健康检查
PORT="${HOST_PORT:-80}"
info "等待服务就绪..."
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    info "服务已就绪：http://127.0.0.1:${PORT}/"
    curl -sS "http://127.0.0.1:${PORT}/health" || true
    echo
    info "页面入口：/index.html  /chat.html  /dashboard.html  /knowledge-map.html"
    info "查看日志：docker compose -f deploy/docker-compose.yml logs -f app"
    exit 0
  fi
  sleep 3
done

compose ps
fail "健康检查超时，请执行 docker compose logs --tail=200 app 定位问题"
