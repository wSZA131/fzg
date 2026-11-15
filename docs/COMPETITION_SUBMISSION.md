# 作品信息收集表（模板 1）正文素材

> 用途：将本文各节内容直接粘贴到赛事《作品信息收集表》Word 模板对应栏目。
> 文中所有数字均可在仓库内复现，来源已在"口径"列注明；标注"待云端复测"的条目在服务器开通后补齐。
> 赛道：赛题 1 · 基于华为云产品打造 AI 创新应用 ｜ 应用领域：教育 / 办公助手

---

## 一、作品基本信息

| 项目 | 内容 |
| --- | --- |
| 作品名称 | 坊知工 FZG —— 掌握度驱动的智能学习伴侣 |
| 一句话介绍 | 面向中学生与高校基础课学习者，把"拍题—讲解—诊断—规划—图谱"串成一次对话的 AI 学伴 |
| 作品形态 | Web 应用（多页面可视化 Demo）+ 开放 API |
| 技术栈 | Python 3.12 / Flask / LangChain Tool Calling / FAISS + BGE / SQLAlchemy / Redis + Celery / Neo4j / 原生 HTML-CSS-JS |
| 华为云资源 | ECS、ModelArts Studio（MaaS）、RDS for MySQL、DCS for Redis、CodeArts 代码智能体 |
| 代码规模 | 后端 75 个 Python 文件、单文件主服务 7800+ 行；前端 8 个页面、13 个脚本、5 个样式表 |
| 开源计划 | 初赛提交源码包；入围后开源至 Gitee/GitCode，附部署指南、演示视频与许可证 |

---

## 二、方案背景与价值

### 2.1 真实场景

中学生与大学基础课学习者在自主学习中普遍遇到三个断点：

1. **遇到不会的题，缺的不是答案，而是"我卡在哪一步"**。通用问答工具给出的整题解答无法定位知识缺口。
2. **错题散落在本子与截图里，复习靠翻找**。缺少按知识点组织的错题与掌握度视图。
3. **学习计划是静态的**。计划不会随最近三天的正确率、耗时和概念掌握度变化而调整。

教师与机构侧的问题相反：有数据但缺"下一步该讲什么"的决策依据，学情报告停留在分数层面。

### 2.2 方案定位

坊知工把"一次提问"扩展成一条完整的教学闭环：

```
拍照/文本提问 → 识别题目 → 判定掌握度 → 选择工具（查掌握度/查图谱/查知识库/诊断错因/生成计划）
→ 结构化讲解 → 落盘错题与诊断 → 更新掌握度 → 调整学习路径与复习计划
```

学生只需提问一次，系统自动完成资料检索、关系推理、错因归因与计划调整；教师端通过仪表盘与知识图谱看到班级与个体的掌握度分布。

### 2.3 实际解决的问题与价值

| 痛点 | 坊知工的解法 | 可观测效果 |
| --- | --- | --- |
| 答案不针对个人 | 先查学生掌握度，按 `<0.4 / 0.4~0.7 / >0.7` 三段选择讲解策略与工具 | 回答中体现"根据你的学习记录"，工具轨迹可见 |
| 资料找不到、易编造 | RAG-Graph 检索：公共知识库 + 个人笔记 + 图谱关系，返回 `hits` 与 `graph_context` 作为证据 | 检索 hit@5 = 100%（6 条用例） |
| 错题无法沉淀 | 诊断结果与错题自动落盘，进入干预看板 | 每次问答产生 `diagnosis` / `wrong_question` 记录 |
| 计划不更新 | 学习反馈接口按完成度、正确率、耗时回写掌握度并重排计划 | `learning_plan` 事件落盘，计划页实时更新 |
| 部署成本高 | 云资源全部可插拔，单容器单端口交付 | 最小 1 台 4C8G ECS 即可运行，RDS/DCS 可后接 |

**商用落地潜力**：B2C 面向自主学习学生（订阅制），B2B 面向培训机构与高校基础课（按席位/私有化部署），两者共用同一套 API 与知识库构建流程，边际复制成本低。

---

## 三、创新性解读

### 3.1 场景创新：从"答题工具"到"教学闭环"

多数教育类 AI 应用止步于"回答问题"。本作品把工具调用与学习数据打通：一次提问同时触发掌握度查询、图谱推理、错因诊断与计划生成，并把这些结果写回学习档案，形成可累积的学习资产。传统场景（错题本、学情报告）因此获得新形态——**错题本变成可检索的知识图谱，学情报告变成实时掌握度曲线**。

### 3.2 技术创新一：掌握度驱动的工具路由

系统提示词内嵌分段教学策略，让模型自主决定"先诊断还是先讲解"：

```
掌握度 < 0.4（低）：优先调用错因诊断 → 生成学习计划 → 讲解
掌握度 0.4~0.7（中）：讲解 + 举例；事实问题查知识库，概念关系查图谱
掌握度 > 0.7（高）：直接进阶拓展与综合应用
```

并在工程侧加了**强制路由兜底**：若判定该题必须查知识库而模型漏调工具，则追加一次带强约束的重试，避免"模型偷懒导致无依据回答"。这一机制把"提示词策略"变成"可验证的产品行为"。

### 3.3 技术创新二：RAG-Graph 三通道融合

文本检索（BM25 风格字词打分 + 字符 n-gram）、稠密向量（FAISS + BGE）、图谱关系（Neo4j）三通道并行召回，再按 `hybrid_score` 融合并去重，返回结构化证据：

- `hits`：可展示的原文片段与来源；
- `graph_context`：命中概念的前驱/后继关系；
- `graph_contribution_rate`：图谱对本次答案的贡献占比，用于评估图谱是否真的被用上。

这使"知识图谱"不再是可视化装饰，而是参与排序与解释的检索通道。

### 3.4 技术创新三：三级降级，演示永不中断

`图片 OCR → 文本回退 → 离线兜底`：

- OCR 上游失败但有文本时自动走文本路径，不返回 502；
- 未配置大模型密钥或上游超时时，返回可展示的离线兜底结果；
- 知识库制品缺失（如未拉取 Git LFS）时，降级到 TF-IDF 或内置演示语料，并在 `/health` 明确报告原因。

对比赛演示尤其关键：**任何单一云服务异常都不会导致页面白屏**。

### 3.5 技术创新四：全链路可观测

每次问答返回 `steps_log`（真实逐步耗时、工具入参、输出摘要、状态）、`evidence`（是否命中掌握度/图谱/知识库）、`meta`（延迟、重试、超时）。前端以时间线渲染，可当场复盘"AI 为什么这么答"。配套 `test-report-dashboard.html` 与健康检查接口，形成可审计的演示证据链。

### 3.6 工程创新：云资源可插拔 + 单端口交付

SQLite ↔ RDS（`STORAGE_BACKEND=sql`）、内存会话 ↔ DCS、JSON 图谱 ↔ Neo4j 均由环境变量切换，业务代码零改动；前端由 Flask 直接托管，**只需暴露一个端口**。这让"本地开发、云端演示、私有化部署"使用同一份镜像，显著降低部署与迁移成本。

### 3.7 与现有方案的差异化

| 维度 | 通用问答产品 | 题库类 App | 坊知工 |
| --- | --- | --- | --- |
| 回答依据 | 模型记忆 | 固定解析 | 知识库 + 图谱 + 个人档案，带证据 |
| 个性化 | 弱 | 按标签推荐 | 掌握度分段策略 + 错因归因 |
| 数据沉淀 | 无 | 题目记录 | 错题、诊断、知识图谱、计划联动 |
| 可解释性 | 无 | 无 | 工具时间线 + 证据字段 |
| 部署 | 封闭 | 封闭 | 开源、单镜像、云资源可插拔 |

---

## 四、数据集的选取与数据处理

### 4.1 数据来源

| 数据集 | 规模 | 来源与生成方式 |
| --- | --- | --- |
| 公共知识库 `pro_kb` | 60,000 chunks（约 20,000 张知识卡） | 依据高等数学、线性代数、概率统计、离散数学及 K12 数学/英语/物理的学科蓝图（章节、概念、公式、题型、易错点）模板化生成，随机种子固定为 `20260410`，可用 `backend/scripts/build_professional_vector_kb.py` 完全复现 |
| 向量索引 | 60,000 × 384 维 | `BAAI/bge-small-zh-v1.5`（71M 参数）编码，FAISS 内积索引 |
| 词法索引 | TF-IDF（字符级 n-gram，特征上限默认 24,000） | 缓解中文分词误差，并作为向量通道不可用时的降级方案 |
| 私有知识库 | 按用户增长 | 用户在学习空间上传的笔记/讲义经清洗、切块后入库，按 `user_id` 隔离 |
| 评测集 A（学科） | 37 条 | 中学数学/英语/物理，覆盖基础概念、解题步骤、错题诊断（`backend/scripts/education_testset.json`） |
| 评测集 B（检索） | 6 条 | 公共检索 5 条 + 私有笔记 1 条，含期望关键词与期望通道（`backend/tests/hybrid_retrieval_eval_cases.json`） |
| 评测集 C（图谱） | 5 条 | 概念关系类问题，校验图谱连通与上下文命中（`backend/tests/graph_availability_eval_cases.json`） |
| 评测集 D（端到端） | 10 条 | 智能体工具轨迹与答案要点（`backend/tests/agent_eval_samples.json`） |
| 扩展评测集 | 59 条 | 增加长尾学科与多步推理题型（`education_testset_large.json`） |

> 说明：公共知识库为**结构化生成的教研内容**，不涉及教材原文复制与版权风险；用户私有数据仅存于自建数据库，不参与公共库训练。

### 4.2 数据处理流程

1. **清洗**：去除空行、重复标点、页眉页脚；统一全半角；限制单条长度（200~300 token 窗口）。
2. **切块**：按知识点卡片切分，chunk 保留 `title/概念/公式/题型/易错点` 字段，便于引用时定位。
3. **向量化**：BGE 编码为 384 维向量，L2 归一化后写入 FAISS；同时构建 TF-IDF 稀疏矩阵作为词法通道与降级方案。
4. **图谱构建**：卡片向量相似度 > 0.44 时建立概念边，边数控制在 1,800~2,500，避免图过密导致噪声；同步时过滤"自学/零基础"等状态词，只保留知识点实体。
5. **隔离与去重**：公共库与私有库分通道召回；结果按标题去重（`max_per_title=1`），保证证据多样性。
6. **评测口径**：`hit@k` 判定命中期望关键词，`keyword_coverage` 衡量覆盖比例，`graph_context_rate` 衡量图谱通道是否返回上下文，延迟取端到端毫秒数。

---

## 五、关键代码片段解读

### 5.1 多模态入口与降级（`backend/app/api/agent_routes.py:67-109`）

```python
image_file = request.files.get("image")
if image_file:
    ocr_result = extract_text_from_image(image_file)
    if not ocr_result.get("success"):
        fallback_text = str(data.get("ocr_text") or request.form.get("ocr_text") or question or "").strip()
        if not fallback_text:
            return jsonify({...}), 502
        ocr_text = fallback_text
```

要点：图片优先、文本兜底。OCR 失败且用户没有提供文本时才返回 502，避免"模型上游抖动导致整次问答失败"。这是演示稳定性的第一道防线。

### 5.2 SSE 流式输出与结果后处理（`backend/app/api/agent_routes.py:116-181`）

```python
def stream_with_post_process():
    for chunk in agent.stream_solve_problem(...):
        ...
        if event_obj.get("type") == "final":
            payload["knowledge_extract"] = post_process.get("knowledge_extract", {})
            payload["diagnosis"] = post_process.get("diagnosis")
            payload["learning_advice"] = post_process.get("learning_advice")
            yield f"data: {json.dumps(event_obj, ensure_ascii=False)}\n\n"
```

要点：流式事件分 `start / tool_start / tool_end / retry / final`，前端据此渲染工具时间线；只在 `final` 事件上做知识抽取、诊断与建议落盘，避免中间事件重复写库。

### 5.3 智能体主流程与强制知识库重试（`backend/app/services/agent_service.py:641-698`）

```python
kb_route = self._resolve_kb_route(question_clean, ocr_clean, force_use_kb=force_use_kb)
...
response, elapsed_ms, _, retries = self._invoke_with_timeout_retry({"input": user_input}, sid, ...)
steps_log = self._build_steps_log(steps, elapsed_ms, timing_handler.tool_events)
if require_kb and not self._has_kb_tool_call(steps_log, expected_tool=preferred_kb_tool):
    retry_input = user_input + f"\n再次强调：必须先调用 {retry_tool}，再输出答案。"
    response_retry, ... = self._invoke_with_timeout_retry({"input": retry_input}, sid, ...)
```

要点：路由判定（是否需要知识库）与工具校验解耦；`_has_kb_tool_call` 直接检查 `steps_log`，把"模型是否真的查了资料"变成可断言的条件，而不是靠提示词祈祷。

### 5.4 RAG-Graph 融合检索（`backend/app/services/knowledge_base.py:1427-1495`）

```python
private_recall = _recall_private_hits(q, docs, recall_k) if uid else []
private_vector_recall = _search_private_vector_chunks(uid, q, docs, top_k=recall_k) if (uid and mode != "lexical") else []
public_recall = _search_public_chunks(q, top_k=recall_k) if mode != "lexical" else []
...
graph_concepts = _extract_graph_concepts(q, candidate_rows=concept_seed_rows, limit=max(4, top * 2))
graph_context = _query_graph_context(uid, graph_concepts, limit=max(top * 3, 8)) if uid else []
merged = _merge_graph_context_into_hits(q, mode, base_hits, graph_context)
sliced = _dedupe_hits(merged, top_k=top)
```

要点：三通道并行召回 → 概念抽取 → 图谱扩展 → 融合去重。概念种子不只来自 query 文本，也来自已召回片段，解决"用户口语化提问抽不出概念"的问题。返回值包含 `graph_contribution_rate`，可直接用于评估图谱增益。

### 5.5 健康检查即部署自检（`backend/app/server.py:7740-7774`）

```python
return jsonify({
    "status": "ok",
    "ai_key_configured": bool(cfg.get("api_key")),
    "neo4j_enabled": neo4j_available,
    "celery_enabled": celery_client is not None,
    "storage_backend": storage_info.get("storage_backend", "json"),
    "database_scheme": storage_info.get("database_scheme", ""),
    "kb_ready": kb_readiness.get("ready"),
    "offline_core_chain_ready": bool(offline_chain.get("ready", False)),
    ...
})
```

要点：`/health` 不只返回 200，而是逐项报告 MaaS 密钥、Neo4j、Redis、数据库、知识库就绪度与建议动作。部署脚本与冒烟脚本直接消费这些字段，减少"看起来启动了但功能不可用"的情况。

### 5.6 单端口托管前端（`backend/app/server.py:7780-7811`）

```python
@app.route('/<path:asset_path>', methods=['GET'])
def frontend_assets(asset_path):
    if normalized.startswith('api/'):
        return jsonify({"success": False, "message": "API endpoint not found"}), 404
    full_path = os.path.join(FRONTEND_DIR, normalized)
    if os.path.isfile(full_path):
        return send_from_directory(FRONTEND_DIR, normalized)
```

要点：静态资源与 API 同源，免去跨域与双端口配置；`api/` 前缀显式排除，避免把错误接口当成文件请求。云端只需暴露 80 一个端口。

---

## 六、方案效果（可量化指标）

### 6.1 已实测指标

| 指标 | 结果 | 口径与来源 |
| --- | --- | --- |
| 检索命中率 hit@5 | **100%**（6/6） | `backend/docs/hybrid_retrieval_report.json`，top_k=5 |
| 平均关键词覆盖率 | **83.3%** | 同上 |
| 检索平均延迟 | **33.5 ms** | 同上（本地环境，不含大模型生成） |
| 图谱连通率 | **100%**（5/5） | `backend/docs/graph_availability_report.json` |
| 图谱上下文命中率 | **60%**（3/5） | 同上 |
| 智能体工具轨迹命中率 | **100%**（10/10 产生工具调用） | `backend/docs/agent_eval_report.json` |
| 公共知识库规模 | **60,000** 向量 / 384 维 | `backend/FINAL_TEST_REPORT.md` 构建与加载验证 |
| 主服务路由数 | **50** 个（另有智能体蓝图路由） | `backend/app/server.py` |
| 智能体工具数 | **6** 个（掌握度/图谱/计划/错因/知识库/GraphRAG） | `backend/app/services/agent_tools.py` |
| 前端页面数 | **8** 个 | `frontend/*.html` |
| 回归测试模块 | **17** 个 | `backend/tests/test_*.py` |
| 交付端口 | **1** 个（80） | `deploy/nginx.conf` + 单端口托管 |

### 6.2 云端复测计划（服务器开通后填写）

| 指标 | 目标 | 复测方式 |
| --- | --- | --- |
| 首字返回时间（流式） | < 2 s | 浏览器 Network 面板记录首个 SSE 事件 |
| 完整回答时延 | < 8 s（MaaS 正常水位） | `steps_log` 总耗时中位数，20 次采样 |
| 并发能力 | 20 并发无明显超时 | `ab`/`wrk` 压测 `/health` 与 `/api/agent/kb/search` |
| 检索 P95 延迟 | < 300 ms | 50 次检索采样 |
| 可用性 | 连续 24h 健康检查成功率 ≥ 99% | 定时任务调用 `/health` |
| 资源占用 | 4C8G 下 CPU < 60%、内存 < 5 GB | ECS 监控面板 |

> 说明：6.1 中延迟为本地开发机实测，云端数值受 MaaS 网络与实例规格影响，故单独列出复测计划，避免把本地数据当作线上承诺。

### 6.3 效果呈现方式（Demo）

首页 → 智能问答（拍照/文本提问，展示工具时间线）→ 仪表盘（掌握度热力图变化）→ 知识图谱（新增概念节点）→ 题库（错题诊断）→ 学习空间（上传资料后检索命中）。完整分镜见 `docs/DEMO_SCRIPT.md`。

---

## 七、华为云产品的使用价值

### 7.1 赛题要求的五个环节对照

| 环节 | 使用方式 | 产出物 |
| --- | --- | --- |
| 需求理解 | 用 CodeArts 智能体拆解赛题与功能清单，形成模块划分（智能体/检索/图谱/空间/评测） | 项目结构与本文件第二节 |
| 代码生成 | 智能体辅助生成接口骨架、数据模型、前端页面与测试用例 | `backend/app`、`frontend`、`backend/tests` |
| 项目构建 | 通过构建与依赖检查发现缺失依赖（FAISS/TF-IDF/Neo4j 驱动），补齐 `requirements.txt` | `deploy/Dockerfile` 可一键构建 |
| 问题修复 | 依据测试失败与运行日志定位问题（如 OCR 失败未降级、流式事件丢失、SSE 被代理缓冲） | 三级降级、`X-Accel-Buffering: no` |
| 部署上线 | Skills/控制台开通 RDS、DCS，使用 ECS + Docker Compose 一键部署 | `deploy/` 部署包与 `docs/DEPLOY_HUAWEI_CLOUD.md` |

### 7.2 云服务与代码的对应关系

| 华为云产品 | 代码接入点 | 未开通时的降级 |
| --- | --- | --- |
| ECS | Docker Compose 运行 `fzg-app` + Nginx | 本地 Docker 预演 |
| ModelArts Studio（MaaS） | `QWEN_API_URL` 指向 OpenAI 兼容端点，`QWEN_MODEL_NAME` 选择模型 | 离线兜底回答 |
| RDS for MySQL | `DATABASE_URL=mysql+pymysql://...` + `STORAGE_BACKEND=sql`，SQLAlchemy 自动建表 | SQLite + JSON 仓储 |
| DCS for Redis | `REDIS_URL` / `AGENT_REDIS_URL` / `CELERY_*` | 内存会话历史 |
| Neo4j | `NEO4J_URI` 等，`GRAPH_PRIMARY=auto` | JSON 图谱 |
| CodeArts 代码智能体 | 需求拆解、代码生成、构建修复、部署编排 | — |

### 7.3 成本与可复制性

- 最小可用配置：1 台 4C8G ECS + MaaS 按量调用，无需 RDS/DCS 即可演示全部页面；
- 完整配置：ECS + RDS 2U4G + DCS 1G + MaaS，月成本可控在代金券额度内；
- 镜像内置向量模型与知识库，**扩容只需复制镜像**，适合机构私有化部署；
- 部署脚本包含 LFS 校验、密钥生成、健康检查，非专业人员按文档可在 30 分钟内完成上线。

---

## 八、开源与提交材料

| 材料 | 状态 | 位置 |
| --- | --- | --- |
| 项目源代码 | 已完成 | 本仓库 |
| 依赖环境 | 已完成 | `backend/requirements.txt`、`deploy/Dockerfile` |
| 部署指导 | 已完成 | `docs/DEPLOY_HUAWEI_CLOUD.md`、`deploy/` |
| 使用文档 | 已完成 | `README.md`、`frontend/README.md`、`docs/DEMO_SCRIPT.md` |
| 开源许可证 | 已完成 | `LICENSE`（MIT） |
| Demo 截图 | 部分完成 | `image/`、`img1/`（8 张），建议按演示脚本重拍 |
| 演示视频 | 待录制 | 录制后放 `docs/media/` 或外链 |
| 云端 Demo 链接 | 待服务器开通 | 初赛不要求，决赛前补齐 |

---

## 九、待补齐清单（服务器开通后）

- [ ] 在 ECS 上完成部署，记录公网访问地址与部署耗时
- [ ] 按 `docs/DEPLOY_HUAWEI_CLOUD.md` 第 5 节执行 `healthcheck.sh`，截图存档
- [ ] 填写 6.2 节云端复测指标
- [ ] 补充 CodeArts 智能体会话截图（需求拆解、代码生成、部署执行各 1~2 张）
- [ ] 录制 3~5 分钟演示视频（分镜见 `docs/DEMO_SCRIPT.md`）
- [ ] 按 `docs/DEMO_SCRIPT.md` 第四节制作 PPT
- [ ] 将仓库推送至 Gitee/GitCode 并确认 LFS 制品可正常拉取
