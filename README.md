# 坊知工 FZG

坊知工是面向教育场景的智能学习伴侣系统，当前版本已包含多模态 OCR、工具调用式智能体、知识库检索、知识图谱增强（RAG-Graph）与 SSE 流式交互能力。

## 系统架构

- 前端：原生 HTML/CSS/JS，多页面结构，支持智能体模式和时间线展示。
- 后端：Flask API + 可选 Celery/Redis，提供问答、评测、知识库、图谱接口。
- 智能体：LangChain Tool Calling（掌握度、图谱、知识库、学习计划、错题归因）。
- 知识增强：文本检索 + Neo4j 关系查询（RAG-Graph）。

## 核心能力

- 多模态题目解析：`POST /api/agent/ocr-tutor`，图片优先，支持文本回退。
- 智能体辅导：调用工具链后输出答案，并返回 `steps_log`、`evidence`、`meta`。
- 流式交互：`stream=true` 时返回 SSE 事件流，支持中间工具调用反馈。
- 知识库能力：
  - 入库：`POST /api/agent/kb/ingest`
  - 检索：`POST /api/agent/kb/search`
  - 检索结果包含 `hits` 与 `graph_context`。
- 在线评测：
  - 单评测：`POST /api/agent/eval`
  - A/B 对比：`POST /api/agent/eval-ab`
- 学习反馈（P2 新增）：`POST /api/agent/learning-feedback`
  - 记录任务完成度、正确率、耗时，并动态更新学生掌握度。
  - 请求体：`{student_id, task_id, task_type, correct_count, total_count, duration_seconds, concept}`

## 🎯 参赛与评测材料

- **[作品信息收集表正文素材](docs/COMPETITION_SUBMISSION.md)**：背景与价值、创新性、数据集、关键代码解读、可量化指标、华为云产品价值
- **[Demo 演示脚本](docs/DEMO_SCRIPT.md)**：5 分钟分镜、截图清单、PPT 大纲、答辩问答
- **评测数据**（`backend/docs/`）：
  - `hybrid_retrieval_report.json`：检索 hit@5 100%、关键词覆盖率 83.3%、平均延迟 33.5 ms（6 条用例）
  - `graph_availability_report.json`：图谱连通率 100%、图谱上下文命中率 60%（5 条用例）
  - `agent_eval_report.json`：10 条用例均产生工具调用轨迹
- **评测脚本**：`backend/scripts/eval_hybrid_retrieval.py`、`backend/scripts/eval_graph_availability.py`、`backend/scripts/run_agent_eval.py`、`backend/scripts/bench_comparison.py`
- **评测集**：`backend/scripts/education_testset.json`（37 条）、`education_testset_large.json`（59 条）

### 前端优化

- **[主仪表盘](frontend/dashboard.html)**（已对齐展示）：
  - 📊 知识点热力图（5级掌握度可视化）
  - 📈 学习进度条动画
  - 🛤️ AI推荐学习路径（Timeline视图）
  - 📉 数据分析图表（Chart.js集成）

## 快速启动

### 0. 云端 / 容器部署（推荐）

服务器与华为云资源（ECS、RDS、DCS、MaaS）就绪后，按 **[华为云部署指南](docs/DEPLOY_HUAWEI_CLOUD.md)** 操作。最短路径：

```bash
cd deploy
cp .env.example .env        # 填写 MaaS 密钥与云资源地址
bash deploy.sh              # 构建镜像 → 启动 → 健康检查
bash healthcheck.sh http://<host>
```

部署包包含 `Dockerfile`、`docker-compose.yml`（Nginx + 应用 + Redis）、`nginx.conf`（已关闭 SSE 缓冲）与环境变量模板。未配置 RDS/DCS/Neo4j 时自动降级为 SQLite/内存会话/JSON 图谱，可在本地先完成演示排练。

> 注意：`backend/data/pro_kb` 由 Git LFS 管理，克隆后需执行 `git lfs install && git lfs pull`，否则 RAG 检索会退化为演示数据（`/health` 会给出提示）。

### 低内存部署（2 核 2G 实例）

`torch` + `sentence-transformers` 约需 1 GB 内存，2G 机型装不下。项目支持低配构建：

```bash
cd deploy
cp .env.lite.example .env     # 填 MaaS key 与 FLASK_SECRET_KEY
bash deploy.sh
```

`LITE_MODE=true` 时镜像不装 torch 与 BGE 模型（约 400 MB），检索退化为
**TF-IDF 编码 + FAISS 检索**——`faiss-cpu` 仅 30–50 MB，完整知识库照样能检索，
只是没有语义向量匹配。运行内存实测约 700–900 MB。

低配模式同时关闭 Redis/Celery（会话走进程内存），并收紧上传上限与日志体积。
完整向量检索能力需 4C8G 及以上，使用常规 `deploy/.env.example`。

### 1. 安装依赖

```powershell
cd backend
python -m pip install -r requirements.txt
```

### 2. 关键环境变量（示例）

```env
USE_REAL_AI=true
AI_PROVIDER=qwen
QWEN_API_KEY=your_api_key
QWEN_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_MODEL_NAME=qwen-plus

AGENT_TIMEOUT_SECONDS=50
AGENT_MAX_RETRIES=1
AGENT_ENABLE_GUARD=true
AGENT_HISTORY_BACKEND=auto
AGENT_REDIS_URL=redis://127.0.0.1:6379/2

USE_NEO4J=auto
NEO4J_URI=neo4j+s://<your-aura>.databases.neo4j.io
NEO4J_USERNAME=<username>
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=<database>
```

### 2.1 OCR 说明（请保留）

- 智能体入口为 `POST /api/agent/ocr-tutor`，支持“图片优先 + 文本回退”。
- 默认可使用 `OCR_PROVIDER=mock` 进行本地联调；接入真实 OCR 时建议统一通过 Qwen-VL。
- 当图片 OCR 上游失败，但请求中包含 `question` 或 `ocr_text` 时，后端会自动降级到文本路径，避免直接 502 中断。

推荐 OCR 相关环境变量：

```env
OCR_PROVIDER=mock
# 若使用真实 OCR，可切换并配置上游密钥/地址
# OCR_PROVIDER=qwen_vl
```

### 2.2 云端 Neo4j（Aura）说明（请保留）

- 本项目支持云端 Neo4j Aura，不要求本地安装 Neo4j 服务端。
- 建议 `USE_NEO4J=auto`：当 URI/账号/密码配置齐全并连通时自动启用。
- 本地仅需安装 Python 驱动（`requirements.txt` 已包含 `neo4j` 依赖）。

Aura 推荐配置：

```env
USE_NEO4J=auto
NEO4J_URI=neo4j+s://<your-aura>.databases.neo4j.io
NEO4J_USERNAME=<username>
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=<database>
```

说明：

- `neo4j+s://` 是 Aura 常用安全连接方式。
- 若只做本地最小可运行，可临时关闭：`USE_NEO4J=false`。

### 3. 启动开发栈

```powershell
powershell -ExecutionPolicy Bypass -File backend/scripts/start-dev-stack.ps1
```

一键停止：

```powershell
powershell -ExecutionPolicy Bypass -File backend/scripts/stop-dev-stack.ps1
```

Linux 启动（可选）：

```bash
chmod +x scripts/start-dev-stack.sh scripts/stop-dev-stack.sh
./scripts/start-dev-stack.sh
```

Linux 停止：

```bash
./scripts/stop-dev-stack.sh
```

### 3.1 手动启动说明（请保留）

不使用一键脚本时，可按以下顺序手动启动：

1. 安装依赖

```powershell
cd backend
python -m pip install -r requirements.txt
```

1. 启动后端

```powershell
python -m app.server
```

1. 启动前端静态服务（新终端）

```powershell
python -m http.server 5501 --directory frontend
```

1. 健康检查

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

1. 可选：启动 Redis/Celery（完整异步功能）

> Redis 仅异步任务与会话历史需要，缺省会自动降级为内存模式，可不启动。
> Windows 下请自行安装 [Redis for Windows](https://github.com/tporadowski/redis/releases) 并监听 6379；Linux/macOS 使用 `redis-server`。

```powershell
redis-server --port 6379
```

```powershell
cd backend
$env:CELERY_BROKER_URL='redis://127.0.0.1:6379/0'
$env:CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1'
python -m celery -A app.server:celery_client worker -l info -P solo
```

### 4. 健康检查

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

## 智能体模式常见问题排查

### 现象 1：页面提示“流式会话已结束，但未收到最终结果”

可能原因：

- 后端 SSE 流中断，仅返回 `error` 事件。
- Redis 不可达导致会话历史初始化失败。
- AI Key 无效或模型上游不可用。

建议排查顺序：

1. 检查后端健康状态

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

1. 若本机未启动 Redis，先强制使用内存会话历史

```env
AGENT_HISTORY_BACKEND=memory
```

1. 校验 AI 相关配置

```env
USE_REAL_AI=true
AI_PROVIDER=qwen
QWEN_API_KEY=<有效密钥>
QWEN_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_MODEL_NAME=qwen-plus
```

1. 修改环境变量后重启后端

```powershell
python -m app.server
```

说明：当前版本已增强流式兜底逻辑，当智能体运行异常时会返回可展示的 `final` 负载，减少前端“无最终结果”的误报。

## 测试与验收

在 `backend` 目录执行：

```powershell
python -m unittest tests.test_agent_ocr_tutor_contract -v
python -m unittest tests.test_agent_kb_contract -v
python -m unittest tests.test_knowledge_base_graphrag -v
```

全量测试（`backend/pytest.ini` 已限定只收集 `tests/`）：

```bash
cd backend
pytest -q      # 期望 143 passed, 1 skipped
```

## 知识库制品自检

`backend/data/pro_kb/` 下的大文件由 Git LFS 管理。若克隆后未拉取，文件只是约 130 字节的指针，
**服务仍能正常启动，但检索会静默降级为内置演示数据**，此时任何检索指标都不代表真实效果。

```bash
python backend/scripts/verify_kb_artifacts.py
```

退出码非 0 表示制品不可用，脚本会直接给出修复命令。

## 运维观测

- `GET /metrics`：Prometheus 文本格式，包含智能体成功率、平均时延、超时/重试次数、
  工具调用失败率与限流统计，可直接接入华为云 AOM 或自建 Prometheus。
- `GET /api/agent/metrics`：同一批指标的 JSON 版本，便于页面展示。
- `GET /health`：就绪度自检（模型 key、知识库、图谱、存储、异步链路逐项报告）。

接口限流默认关闭，公网部署请在 `.env` 中开启：

```env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_AGENT_TUTOR=120   # 单个 IP 每分钟智能问答次数
```

限流按接口成本分桶（智能问答 60/min、登录注册 10/min、其它 API 240/min），
`/health` 与 `/metrics` 豁免。超限返回 `429` 并携带 `Retry-After`。

> 评测指标怎么读、报告什么时候有效，见 [评测口径与复现指南](docs/EVAL_GUIDE.md)。

## 版本迭代时间线（倒序）

### 2026-11-18（当前）

- 移动端适配：所有页面补全 `viewport-fit=cover`；底部 Tab 导航由 `page-shell.js` 复用侧边栏导航数据动态生成，导航配置保持单一来源。
- 新增 PWA 能力：`manifest.webmanifest`、应用图标、`offline.html`、`sw.js`（仅缓存静态资源，`/api/` 请求完全绕过）、`assets/css/shared/mobile-shell.css`（仅在 `max-width: 760px` 生效）。
- `deploy/nginx.conf` 为 `/sw.js` 与 `/manifest.webmanifest` 单独关闭长缓存，避免升级后旧脚本长期生效。
- 新增 `GET /metrics`（Prometheus 文本格式）与接口限流（滑动窗口，默认关闭、部署模板默认开启，按接口成本分桶，`/health` 与 `/metrics` 豁免）。
- 评测接口新增 `meta` 环境快照（`agent_mode` / `kb_mode` / `ai_key_configured` / `notes`），`run_agent_eval.py` 增加 `--require-ai`，避免把离线兜底分当成模型能力分写入报告。
- 新增 `backend/scripts/verify_kb_artifacts.py`，一键识别 Git LFS 指针并给出修复命令。
- 新增 `docs/EVAL_GUIDE.md`：三份评测报告的差异、指标含义与有效性判定。
- 新增 `backend/pytest.ini` 限定测试收集范围，修复 `scripts/test_*.py` 被误收集导致整轮测试中断的问题；补限流与可观测性契约测试（7 例）。
- 账号系统升级：密码强度校验（8 位 + 字母 + 数字）、修改密码、恢复码找回密码（`services/auth_credentials.py`，独立存储不侵入 `auth_users` 表）、登录失败 5 次锁定 10 分钟、登录设备列表与「退出其他所有设备」。
- 修复「游客数据绑定」名不副实：注册时真实继承访客数据；登录默认不合并（避免公共设备串号），仅在前端显式勾选时携带 `adopt_guest_data=true` 触发迁移。删除两个硬编码返回空壳的 binding 函数。
- 练习记录落库：新增 `POST /api/question_bank/practice-session` 与 `GET /api/question_bank/practice-sessions`，结束练习不再只写 localStorage。
- 删除无任何引用的重复认证实现 `frontend/js/auth.js`（27.8 KB）及其空目录。
- 登录 UI：密码可见切换、强度提示、找回密码面板、注册后一次性展示恢复码、设置面板新增「安全」「登录设备」两个页签。
- 新增契约测试 `test_auth_upgrade_contract.py`（16 例）与 `test_practice_session_contract.py`（4 例），测试总数 143 → 163。
- 新增「朗读 / 听讲解」：`assets/js/shared/speech-player.js` 使用浏览器原生 SpeechSynthesis，零依赖零费用、内容不出本机；自动清理 Markdown 与公式，长文本按句分段播放，支持播放中再次点击停止；不支持该 API 的浏览器不显示入口。
- 错题重练接入历史错题库：当前会话无错题时回退到 `GET /api/wrong_questions`，最多载入 10 道并按解答题重练（历史记录未保存选项）。
- 学习空间新增跨空间搜索：`GET /api/spaces/search` 按标题、摘要、正文与标签匹配，返回所属空间与命中片段；前端在顶栏提供搜索入口，点击结果直接跳转并定位到该资料。
- 新增契约测试 `test_space_search_contract.py`（6 例），测试总数 163 → 169。
- 朗读能力扩展到三处：问答消息、学习空间资料预览、知识图谱知识点详情。样式抽到 `assets/css/shared/speech.css` 共用；预览页按资料类型自动隐藏入口（音视频与图片无文本可读），切换资料时自动停止上一份朗读。
- 账号设置精简：移除「登录设备」页签与「聊天模式」选项；新增账户资料编辑（`PUT /api/auth/profile`，支持修改昵称），密码显示/隐藏改为图标；登录页「记住密码」替代原「游客数据继承」勾选（注册仍自动继承访客数据）。
- 主题与语言落地：新增深色主题（`data-fangzhigong-theme`，含首屏防闪白脚本）与中英文界面（`assets/js/shared/i18n.js`，覆盖登录、账号设置与主导航）。切换语言后整页重载。
- 退出登录后自动回到未登录首页；新增 `PUT /api/auth/profile` 契约测试（3 例），测试总数 169 → 172。
- 账号资料新增「个人简介」：`auth_users.bio`（JSON 仓储直存，SQL 仓储启动时幂等补列），`PUT /api/auth/profile` 支持 `bio`；资料完成度改为按「昵称 + 简介」真实计算，不再固定 100%。
- 深色主题修复：批量归组 157 个白底类选择器统一压深，解决"背景变黑、卡片仍白"的割裂问题。
- 语言切换修复：切换时同步调用 `PUT /api/auth/profile` 写入后端 locale，避免刷新后被 `/api/auth/me` 覆盖回旧值；同时把偏好写入独立 `localStorage` 键。
- 契约测试增至 174（`test_auth_upgrade_contract.py` 21 例）。

### 2026-11-13

- 新增云端部署包：`deploy/Dockerfile`、`docker-compose.yml`、`nginx.conf`、`.env.example`、`deploy.sh`、`healthcheck.sh`。
- 新增文档：华为云部署指南、参赛作品材料、Demo 演示脚本与文档索引；补齐 MIT 许可证。
- README 修正失效的文档链接与未标注口径的性能结论，改为引用仓库内可复现的评测报告。
- 安全加固：匿名请求不再采信任意 `user_id`（仅允许签名访客 ID 认领）；用户 ID 参与文件名时做净化；CORS 改为白名单；调试模式默认关闭；异步任务按归属校验。
- 数据一致性：注销账号按精确文件名删除；修复 `updatedAt` 时间戳时区偏移；事件长文本列改用 `LONGTEXT`。
- 智能体：离线兜底不再伪造工具轨迹（统一标记 `local_rule_fallback`）；步骤耗时按工具事件对齐；Redis 不可达时如实上报 `history_backend`；内存会话加 LRU 上限；评测接口默认关闭并修正工具轨迹计分。
- 前端：图表库 CDN 失败降级；首页防重复提交与重复抽取；判题后广播 `knowledge:updated`；学习计划保存失败回滚；知识库引用按钮改为事件委托；清理 3 个无引用脚本与重复 CDN。

### 2026-04-11

- 工具执行时间线改为真实逐步耗时统计，修复步骤耗时同值问题。
- 学习计划工具升级为“生成即落盘”：写入 `user_plans` 并记录 `learning_plan` 事件。
- 错题归因工具支持诊断事件落盘，干预看板可直接消费。
- 图谱新增非知识点三层过滤与停用词扩展，阻止“自学/零基础”等状态词入图。

### 2026-04-10

- 智能体接口支持 SSE 流式返回（`stream=true`）。
- `ocr-tutor` 增加 OCR 失败文本降级，避免直接中断。
- 知识库升级为 RAG-Graph 输出：`hits + graph_context`。
- 新增 GraphRAG 测试：`tests/test_knowledge_base_graphrag.py`。
- 修复 A/B 评测入参校验顺序，保证契约一致性。
- 流式事件处理增强：前端不再吞掉 `error` 事件，能展示真实异常原因。
- 会话历史回退增强：Redis 不可达时自动回退内存会话历史。
- 流式兜底增强：智能体运行异常时也返回 `final` 负载，避免会话结束无最终结果。

### 2026-04（上旬）

- 新增知识库入库与检索接口（`/api/agent/kb/ingest`、`/api/agent/kb/search`）。
- 新增在线评测接口（`/api/agent/eval`、`/api/agent/eval-ab`）。
- 智能体支持结构化步骤日志：`steps_log`。

### 2026-03（历史）

- 基础问答、学习画像、知识图谱可视化、学习空间等核心页面与接口完成首版落地。

## 文档导航

- 文档索引：[docs/README.md](docs/README.md)
- 华为云部署：[docs/DEPLOY_HUAWEI_CLOUD.md](docs/DEPLOY_HUAWEI_CLOUD.md)
- 云端快速启动：[CLOUD_QUICKSTART.md](CLOUD_QUICKSTART.md)
- 参赛材料：[docs/COMPETITION_SUBMISSION.md](docs/COMPETITION_SUBMISSION.md)
- Demo 演示：[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
- 前端说明：[frontend/README.md](frontend/README.md)
- 许可证：[LICENSE](LICENSE)
