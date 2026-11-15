# 云端快速启动

三分钟完成本地容器预演；华为云资源到位后只需替换 `deploy/.env`。

## 1. 前置

- Docker 24+ 与 Compose 插件
- Git LFS（知识库制品由 LFS 管理）

```bash
git lfs install && git lfs pull
ls -lh backend/data/pro_kb/pro_kb_faiss.index   # 应为百 MB 级
```

## 2. 启动

```bash
cd deploy
cp .env.example .env
# 必填：QWEN_API_KEY / QWEN_API_URL / QWEN_MODEL_NAME（MaaS 的 OpenAI 兼容端点）
bash deploy.sh
```

首次构建需下载 CPU 版 torch 与 `BAAI/bge-small-zh-v1.5` 向量模型，约 5–15 分钟。

## 3. 验证

```bash
bash healthcheck.sh http://127.0.0.1
```

预期：`status=ok`、`kb_ready=true`、6 个页面返回 200。

## 4. 访问

| 入口 | 地址 |
| --- | --- |
| 首页 | `http://<host>/index.html` |
| 智能问答 | `http://<host>/chat.html` |
| 学习仪表盘 | `http://<host>/dashboard.html` |
| 知识图谱 | `http://<host>/knowledge-map.html` |
| 题库练习 | `http://<host>/question-bank.html` |
| 学习空间 | `http://<host>/spaces.html` |
| 健康状态 | `http://<host>/health` |

## 5. 下一步

- 云资源接入（RDS / DCS / Neo4j / MaaS）：[docs/DEPLOY_HUAWEI_CLOUD.md](docs/DEPLOY_HUAWEI_CLOUD.md)
- 演示流程与截图：[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
- 参赛材料：[docs/COMPETITION_SUBMISSION.md](docs/COMPETITION_SUBMISSION.md)
