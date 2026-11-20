# 文档索引

## 参赛材料

- [作品信息收集表正文素材](COMPETITION_SUBMISSION.md)：背景与价值、创新性、数据集、关键代码解读、量化指标、华为云产品价值
- [Demo 演示脚本](DEMO_SCRIPT.md)：5 分钟分镜、截图清单、PPT 大纲、答辩问答
- [API 契约](../backend/docs/API_CONTRACT.md)：智能体接口请求/响应约定

## 部署与运维

- [华为云部署指南](DEPLOY_HUAWEI_CLOUD.md)：ECS / RDS / DCS / Neo4j / MaaS 接入、验收与排障
- [云端快速启动](../CLOUD_QUICKSTART.md)：三条命令完成本地预演
- 部署编排：[deploy/docker-compose.yml](../deploy/docker-compose.yml)、[deploy/Dockerfile](../deploy/Dockerfile)
- 冒烟检查：[deploy/healthcheck.sh](../deploy/healthcheck.sh)

## 开发工具

- [CodeArts 代码智能体使用指南](CODEARTS_SKILLS_GUIDE.md)：赛题必选工具的开通、Skills 安装、
  云资源开通提示词与证据留存清单

## 评测与基准

- [评测口径与复现指南](EVAL_GUIDE.md)：三份报告的差异、每个指标的含义、报告有效性判定（先看 `meta`）、复现命令

数据文件位于 `backend/docs/`：

- `hybrid_retrieval_report.json`：混合检索评测（hit@5、关键词覆盖率、延迟）
- `graph_availability_report.json`：图谱可用性评测（连通率、上下文命中率）
- `agent_eval_report.json`：端到端智能体评测（工具轨迹）
- 复现脚本：`backend/scripts/eval_hybrid_retrieval.py`、`backend/scripts/eval_graph_availability.py`、`backend/scripts/run_agent_eval.py`
- 制品自检：`backend/scripts/verify_kb_artifacts.py`

## 其他

- [前端说明](../frontend/README.md)
- Neo4j 接入：见部署指南第 4.4 节
