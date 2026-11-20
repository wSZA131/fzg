# 评测口径与复现指南

本文件解决的问题：仓库里的评测报告是**在特定环境下生成的**，脱离环境看数字会得出错误结论。
答辩或材料引用指标前，请先按本文第 3 节确认报告是否有效。

## 1. 三份报告分别在测什么

| 脚本 | 报告 | 测的对象 | 核心指标 |
| --- | --- | --- | --- |
| `backend/scripts/eval_hybrid_retrieval.py` | `hybrid_retrieval_report.json` | 检索链路（向量 + 词法 + 图谱 + 私有笔记） | `hit_at_k`、`avg_keyword_coverage`、`avg_latency_ms` |
| `backend/scripts/eval_graph_availability.py` | `graph_availability_report.json` | 图谱可用性与证据一致性 | `graph_connectivity_rate`、`graph_recall_rate`、`graph_context_rate` |
| `backend/scripts/run_agent_eval.py` | `agent_eval_report.json` | 端到端智能体（回答质量 + 工具轨迹） | `avg_score`、`keyword_score`、`has_tool_trace` |

三者不可混谈：检索命中率高不代表回答好，工具被调用也不代表答案对。

## 2. 每个指标的准确含义

**`keyword_score`**：期望关键词在回答中的字面命中比例。它是**必要不充分**指标——
关键词全覆盖也可能是错答案，但关键词全不中通常说明回答跑偏或根本没走到模型。

**`avg_score`**（`/api/agent/eval`）：`0.6 × keyword_score + 0.4 × 有真实工具调用`。
因此**满分 0.4 且 keyword 全 0**，恰好等于"工具被调用了，但回答里没出现期望词"。

**`hit_at_k`**：前 k 条检索结果中是否包含标注的正确切片。只反映召回，不反映排序质量。

**`graph_recall_rate` / `evidence_consistency_rate`**：图谱路径是否命中标注概念、证据是否自洽。
这两项对图谱数据的完整度极其敏感，知识库降级时会直接归零。

## 3. 先看 `meta`，再看数字

`/api/agent/eval` 与 `/api/agent/eval-ab` 的响应现在包含 `meta` 字段：

```json
{
  "meta": {
    "agent_mode": "local_rule_fallback",
    "ai_key_configured": false,
    "kb_mode": "demo_fallback",
    "notes": ["AI 未启用……keyword_score 不代表模型能力。"]
  }
}
```

判读规则：

| `meta.agent_mode` | `meta.kb_mode` | 报告能说明什么 |
| --- | --- | --- |
| `llm` | `full` | 可以用于效果对比与指标宣传 |
| `llm` | `demo_fallback` | 反映模型能力，但检索类指标不代表完整库 |
| `local_rule_fallback` | 任意 | **只能作为兜底链路的连通性验证，不能作为效果指标** |

只要 `notes` 非空，就不要把该报告的数字写进参赛材料。

## 4. 复现步骤

```bash
cd backend

# 0) 先确认知识库制品是真实文件而不是 LFS 指针
python scripts/verify_kb_artifacts.py

# 1) 确认模型与知识库就绪
curl -s http://127.0.0.1:5000/health | python -m json.tool
#    期望 ai_key_configured: true、kb_mode 不为 demo_fallback

# 2) 开启评测接口（默认关闭，避免公网刷额度）
export AGENT_EVAL_ENABLED=true

# 3) 跑端到端评测；--require-ai 会在模型未启用时直接失败，避免产出误导性报告
python scripts/run_agent_eval.py --require-ai

# 4) 检索与图谱评测
python scripts/eval_hybrid_retrieval.py
python scripts/eval_graph_availability.py
```

`--require-ai` 是刻意设计的：宁可跑不出报告，也不产出一份"看起来有数据、实际测的是兜底模板"的报告。

## 5. 当前仓库内的历史报告

`backend/docs/*.json` 中的既有报告生成于离线兜底环境（无 AI key、知识库为 LFS 指针状态）。
它们可用来验证接口连通与工具链路，**不应作为模型效果的证据**。

配好 `QWEN_API_KEY` 并执行 `git lfs pull` 后按第 4 节重跑，用新报告替换旧文件。

## 6. 关于评测集规模

现有测试集规模在 6～59 条之间，样本量偏小，单条波动会显著影响均值。
对外引用时建议同时给出用例数与 `meta`，不要只报一个平均值。
