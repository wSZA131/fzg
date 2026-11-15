# 坊知工 FZG 华为云部署指南

本文覆盖从"本地预演"到"华为云 ECS 上线"的完整流程。云服务器尚未开通时，可先执行第 1 节完成本地验证；资源到位后按第 3 节逐项替换环境变量即可，无需改动代码。

---

## 1. 整体架构

```
用户浏览器
   │  80/443
   ▼
Nginx（ECS，容器）
   │  proxy_pass，SSE 关闭缓冲
   ▼
Flask 应用（同容器，端口 5000）
   ├── 前端静态页面（frontend/，由 Flask 直接托管，单端口交付）
   ├── 智能体（LangChain Tool Calling，6 个工具）
   ├── RAG-Graph 检索（FAISS 6 万向量 + TF-IDF + 图谱上下文）
   ├── 华为云 RDS for MySQL（DATABASE_URL，可选，缺省 SQLite）
   ├── 华为云 DCS for Redis（会话历史、Celery broker，可选，缺省容器内 Redis）
   ├── Neo4j（Aura 或 ECS 自建，可选，缺省 JSON 图谱）
   └── 华为云 MaaS（OpenAI 兼容接口，提供问答/OCR 大模型能力）
```

设计原则：**所有云服务均为"可插拔"**。任一云资源未配置时，后端自动降级（SQLite / 内存会话 / JSON 图谱 / 离线兜底回答），保证 Demo 页面始终可访问。这正是"服务器还在申请"阶段可以先完成开发与演示的原因。

---

## 2. 本地预演（无需云资源）

```bash
cd deploy
cp .env.example .env
# 编辑 .env：可只填 QWEN_API_KEY（或任意 OpenAI 兼容 key）
bash deploy.sh
```

- 首次构建会下载 CPU 版 torch 与中文向量模型（约 5-15 分钟）。
- 启动后访问 `http://127.0.0.1/`，执行 `bash healthcheck.sh http://127.0.0.1` 自检。
- 未配置数据库/Redis 时：`/health` 返回 `database_scheme: sqlite`、`celery_enabled: false`，属于预期。
- 未配置大模型 key 时：智能体走离线兜底，页面仍可完整演示交互流程，但不具备真实生成质量。

> 注意：`backend/data/pro_kb` 由 Git LFS 管理。克隆后必须执行 `git lfs install && git lfs pull`，否则健康检查会提示 `public vector unavailable: git lfs pointer detected`，RAG 检索退化为演示数据。

---

## 3. 华为云资源准备

### 3.1 资源清单

| 资源 | 建议规格 | 在项目中的作用 | 是否必须 |
| --- | --- | --- | --- |
| ECS 弹性云服务器 | 4 vCPU / 8 GB，Ubuntu 22.04，系统盘 60 GB | 运行 Nginx + Flask 应用 | 必须 |
| ModelArts Studio（MaaS） | 按 token 计费，开通 DeepSeek/Qwen 任一方舟模型 | 智能体推理、题目讲解 | 必须（否则为离线兜底） |
| RDS for MySQL 8.0 | 2 vCPU / 4 GB，存储 40 GB | 用户、空间、题库、学习记录持久化 | 建议 |
| DCS for Redis 5.0/6.0 | 1 GB 主备 | 智能体会话历史、Celery broker | 建议 |
| Neo4j | Aura 免费版，或 ECS 自建 4.4+ | 知识图谱关系查询 | 可选 |
| OBS 对象存储 | 标准存储 | 学习空间附件（当前版本暂用容器卷） | 后续演进 |

> 预算有限时优先保证 **ECS + MaaS**；RDS/DCS 可在演示前再接入，代码无需改动。

### 3.2 通过 CodeArts 智能体 / Skills 开通资源

比赛要求使用"华为云码道 CodeArts 代码智能体"完成资源开通与应用部署，推荐操作顺序：

1. 在 CodeArts 中打开本项目仓库，登录已领取代金券的华为云账号。
2. 在智能体对话中提交资源需求，例如：
   > 请在我的 VPC 内创建一台 4C8G 的 Ubuntu 22.04 ECS、一个 2U4G 的 MySQL 8.0 RDS 实例和一个 1G 的 Redis 实例，并输出内网地址、端口、账号初始化方式与安全组建议。
3. 若当前环境已加载 `auto-deploy` 类 Skills（参考赛题提供的 Skills 一键部署案例），按其引导选择"应用部署"模板，把 `deploy/docker-compose.yml` 作为部署入口。
4. 记录智能体返回的 **RDS 内网地址 / DCS 内网地址 / 安全组规则**，填入第 4 节环境变量；同时保留智能体会话截图，作为"需求理解 → 资源开通 → 部署上线"过程材料。

若 Skills 面板未提供对应能力，使用控制台手动创建即可，后续步骤完全一致。

### 3.3 ECS 初始化

```bash
# 1) 安装 Docker（使用华为云镜像源）
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg git git-lfs
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://repo.huaweicloud.com/docker-ce/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://repo.huaweicloud.com/docker-ce/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker

# 2) 获取代码（二选一）
git clone https://github.com/mapleleaves28744/dachuang_fangzhigong.git fzg && cd fzg
# 或从 Gitee/GitCode 镜像克隆，或使用 CodeArts 构建产物解压

# 3) 拉取 LFS 制品（关键步骤）
git lfs install && git lfs pull
ls -lh backend/data/pro_kb/pro_kb_faiss.index   # 应为百 MB 级，而不是 100 多字节
```

安全组需放通入方向 **80**（若配置 HTTPS 则再加 **443**）；RDS/DCS 只允许 ECS 所在安全组访问，不要对公网开放 3306/6379。

---

## 4. 配置环境变量

```bash
cd deploy
cp .env.example .env
vim .env
```

### 4.1 大模型（MaaS）

智能体链路固定读取 `QWEN_*` 三个变量，接入 MaaS 时**保持 `AI_PROVIDER=qwen`**，把地址指向 MaaS 的 OpenAI 兼容端点：

```env
USE_REAL_AI=true
AI_PROVIDER=qwen
QWEN_API_KEY=<MaaS API Key>
QWEN_API_URL=https://<maas-endpoint>/v1/chat/completions
QWEN_MODEL_NAME=<控制台中的模型名>
```

说明：
- `QWEN_API_URL` 可填完整 `.../chat/completions`，代码会自动归一为 base_url。
- `/api/ask`、`/api/analyze` 走 `AI_PROVIDER` 选择的分支；为避免两套配置不一致，建议统一使用 `AI_PROVIDER=qwen` + MaaS 端点。
- 需要真实识题时再设置 `OCR_PROVIDER=qwen_vl`；演示阶段用 `mock` 即可，文本提问不受影响。

### 4.2 RDS for MySQL

先在实例中创建库与账号（字符集务必 `utf8mb4`）：

```sql
CREATE DATABASE fzg DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE USER 'fzg'@'%' IDENTIFIED BY '<strong-password>';
GRANT ALL PRIVILEGES ON fzg.* TO 'fzg'@'%';
FLUSH PRIVILEGES;
```

```env
DATABASE_URL=mysql+pymysql://fzg:<password>@<rds-internal-ip>:3306/fzg?charset=utf8mb4
STORAGE_BACKEND=sql
SPACE_STORAGE_BACKEND=sql
```

注意：只配置 `DATABASE_URL` 不会切换主数据仓储。用户、画像、计划等默认仍写入 `backend/data/*.json`（`STORAGE_BACKEND=json`），多实例部署会互相覆盖，因此接 RDS 时必须显式设置 `STORAGE_BACKEND=sql`。

验证：重启后 `/health` 的 `storage_backend` 应为 `sql`，`database_scheme` 为 `mysql`。表结构由 SQLAlchemy 自动创建，无需手工建表。

### 4.3 DCS for Redis

Redis 实例按 DB 编号隔离三类用途，与默认约定一致：

```env
REDIS_URL=redis://:<password>@<dcs-internal-ip>:6379/0
AGENT_REDIS_URL=redis://:<password>@<dcs-internal-ip>:6379/2
CELERY_BROKER_URL=redis://:<password>@<dcs-internal-ip>:6379/0
CELERY_RESULT_BACKEND=redis://:<password>@<dcs-internal-ip>:6379/1
```

未配置时自动使用 compose 内的 `redis` 服务，无需改动。

### 4.4 Neo4j（可选）

```env
USE_NEO4J=auto
GRAPH_PRIMARY=auto
GRAPH_SYNC_MODE=auto
NEO4J_URI=neo4j+s://<instance>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=neo4j
```

`auto` 表示"配齐且连通才启用"，连接失败不会阻塞启动。批量导入图谱可执行：

```bash
docker compose exec app python scripts/sync_local_state_to_neo4j_aura.py
```

### 4.5 其他

```env
FLASK_SECRET_KEY=<随机 48 字节>
AUTH_TOKEN_TTL_DAYS=14
HOST_PORT=80

# 同源部署（Nginx 反代）无需配置；前后端分域名时填写白名单，逗号分隔
CORS_ALLOWED_ORIGINS=
# 评测接口默认关闭，防止公网刷模型额度；本地评测可临时开启
AGENT_EVAL_ENABLED=false
# 内存会话上限，Redis 不可用时限制匿名会话增长
AGENT_HISTORY_MAX_SESSIONS=200
```

---

## 5. 启动与验收

```bash
cd deploy
bash deploy.sh
```

脚本会依次完成：环境检查 → LFS 指针检查 → 构建镜像 → 启动 Nginx/应用/Redis → 健康检查。

上线自检：

```bash
bash healthcheck.sh http://<ecs-public-ip>
```

期望结果：
- `/health` 返回 `"status": "ok"`，`readiness` 为 `ready`（`degraded` 表示知识库与离线链路都不可用）；
- `kb_ready: true`（完成 LFS 拉取且模型可用）；
- `storage_backend: sql`、`space_storage_backend: sql`（接入 RDS 且设置 `STORAGE_BACKEND=sql` 时）；
- `neo4j_enabled` 与是否配置图数据库一致；
- 6 个页面全部 200；
- `/api/agent/kb/search` 返回 `"success": true` 且 `hits` 非空。

页面入口：

| 页面 | 路径 | 演示要点 |
| --- | --- | --- |
| 首页 | `/index.html` | 产品定位与功能入口 |
| 智能问答 | `/chat.html` | 多模态识题、SSE 步骤时间线、工具调用证据 |
| 学习仪表盘 | `/dashboard.html` | 掌握度热力图、学习路径、趋势图 |
| 知识图谱 | `/knowledge-map.html` | 概念关系与掌握度着色 |
| 题库练习 | `/question-bank.html` | 组卷、作答、错因诊断 |
| 学习空间 | `/spaces.html` | 资料上传、私有知识库入库与检索 |

---

## 6. 运维

```bash
docker compose ps
docker compose logs -f app
docker compose restart app
docker compose down            # 停止（保留数据卷）
docker compose up -d           # 再次启动

# 升级
git pull && git lfs pull
docker compose build app && docker compose up -d
```

数据备份：

```bash
# 应用状态（SQLite、用户 JSON、知识库制品）
docker run --rm -v fzg_fzg-data:/data -v "$PWD":/backup alpine tar czf /backup/fzg-data-$(date +%F).tar.gz -C /data .
```

使用 RDS 时，数据库备份交由 RDS 自动备份策略管理。

---

## 7. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `/health` 中 `kb_ready=false`、日志提示 git lfs pointer | 未拉取 LFS 制品，或镜像在拉取前构建 | 宿主机执行 `git lfs pull` 后 `docker compose build --no-cache app` |
| 首次启动卡住或向量检索不可用 | 容器无法访问 HuggingFace | 确认构建参数 `HF_ENDPOINT=https://hf-mirror.com`；或改用离线镜像并在 `.env` 设 `HF_HUB_OFFLINE=1` |
| RDS 连接超时 | 安全组/白名单未放通内网，或用了公网地址 | RDS 白名单加入 ECS 内网 IP，`DATABASE_URL` 使用内网域名 |
| 页面正常但回答与问题无关 | 未配置大模型 key，走了离线兜底 | 配置 `QWEN_API_KEY` 后重启；`/health` 的 `ai_enabled` 应为 true |
| SSE 一直在转圈、最后一次性输出 | 反向代理缓冲 | 已在本仓库 `deploy/nginx.conf` 关闭 `proxy_buffering`；若改用 SLB/ELB 需同样关闭缓冲 |
| 上传图片报 413 | Nginx 请求体限制 | `nginx.conf` 中 `client_max_body_size` 已设 20m；按需调整 |
| Celery 反复重启 | 未启用 async profile 或 Redis 不可达 | 默认不启动；确需异步时 `ENABLE_ASYNC=true bash deploy.sh`，且必须使用 RDS 而非 SQLite |
| 容器内写文件权限不足 | 以非 root 用户运行 | 使用命名卷（默认已配置），不要改成宿主机 bind mount 目录 |
| 国内访问首页字体/公式渲染偏慢 | 前端引用了 Google Fonts（`fonts.googleapis.com`）与 jsDelivr 的 KaTeX | 已改为异步加载，不阻塞首屏；仍建议演示前预热一次 |
| 调用 `/api/agent/eval` 返回 403 `EVAL_DISABLED` | 评测接口默认关闭（会触发真实模型调用并写库） | 服务端设 `AGENT_EVAL_ENABLED=true`，或配置 `AGENT_EVAL_TOKEN` 并在请求头带 `X-Eval-Token` |
| 跨域请求被浏览器拦截 | `CORS_ALLOWED_ORIGINS` 未包含前端域名 | 同源部署无需配置；分域名时在 `.env` 填 `https://your-domain` 后重启 |

---

## 8. 上线检查清单

- [ ] `git lfs pull` 已完成，`pro_kb_faiss.index` 为百 MB 级
- [ ] `.env` 中 `FLASK_SECRET_KEY` 已替换为随机值
- [ ] MaaS key 可用，`/health` 显示 `ai_key_configured: true`
- [ ] RDS 已建库建号，`storage_backend: sql`
- [ ] DCS 已连通，`celery_enabled: true`（如启用异步）
- [ ] 安全组仅放通 80/443，3306/6379 不对公网开放
- [ ] `healthcheck.sh` 全部通过
- [ ] 6 个页面截图与录屏已归档（见 `docs/DEMO_SCRIPT.md`）
- [ ] 云资源账单与代金券余额已确认
