# Backend API Contract

## Scope

This document defines stable response fields for key learner-facing APIs.

## GET /api/profile

- success: bool
- request_id: string
- profile: object
- profile.user_id: string
- profile.updated_at: string (ISO datetime)
- profile.learning_style: one of visual|auditory|kinesthetic
- profile.style_scores: object
- profile.style_method: one of kmeans|rule|rule_fallback
- profile.style_features: object
- profile.interests: string[]
- profile.best_time_range: string
- profile.focus_minutes: number
- profile.content_type_counter: object

## GET /api/recommendations

探索推荐只返回外部资源（Wikipedia / Wikibooks / OpenStax / Oak / Google Scholar / Google Books / Google Videos / Google Play Books / YouTube），不返回用户空间资料、AI 讲解或题库任务。

- success: bool
- request_id: string
- user_id: string
- count: number
- items: recommendation[]
- recommendation_context: object
- recommendation_context.learning_style: one of visual|auditory|kinesthetic
- recommendation_context.style_method: one of kmeans|rule|rule_fallback
- recommendation_context.diagnosis_recent_count: number
- recommendation_context.generated_at: string (ISO datetime)

recommendation fields:
- id: string
- concept: string
- mastery: number|null
- resource_type: string
- resource_kind: one of open_article|open_textbook|open_lesson|open_paper|open_video|external_book
- resource_action_label: string
- title: string
- reason: string
- reason_codes: string[]
- priority: number
- score: number
- recommend_time: string
- duration_minutes: number
- difficulty: one of easy|medium|hard
- provider: string (`Wikipedia`, `Wikibooks`, `OpenStax`, `Oak National Academy`, `Google Scholar`, `Google Books`, `Google Videos`, `Google Play Books`, `YouTube`)
- cover_url: string (开放 API 缩略图或空字符串)
- action: object
- action.type: string
- strategy_tags: string[]
- evidence_brief: string
- source_evidence: object
- source_evidence.profile: object
- source_evidence.knowledge_graph: object
- source_evidence.diagnosis: object
- source_evidence.recommendation: object
- source_evidence.recommendation.sources: string[] (`weakness`, `review_due`, `interest`, `open_resource`)

Query params:
- scene: string, default home_explore
- limit: number, 1-12
- refresh: boolean
- exclude: comma-separated resource ids

Response cache fields:
- cache_hit: bool
- engine_version: number
- excluded_count: number
- audit: object (only populated when recommendations are recomputed)
- audit.open_queries: string[]
- audit.open_resource_count: number
- audit.open_providers: string[]

## POST /api/recommendations/feedback

Request body:

```json
{
  "scene": "home_explore",
  "events": [
    {
      "resource_id": "res-practice-derivative",
      "event_type": "impression",
      "position": 1,
      "concept": "导数",
      "resource_kind": "practice_bank"
    }
  ]
}
```

- event_type: one of impression|click|complete|dismiss|not_interested
- The endpoint records events in `user_event` with suffix `recommendation`.
- `click` / `complete` / `dismiss` / `not_interested` invalidate the user's recommendation cache; `impression` does not.

## GET /api/knowledge_graph/path

- success: bool
- request_id: string
- user_id: string
- target: string
- path: string[]
- length: number
- storage: one of neo4j|json
- path_source: one of json|json_fallback (present when storage=json)

Notes:
- json_fallback means the path is inferred by fallback strategy when graph shortest path is empty.
- For invalid target, the API returns TARGET_NOT_FOUND.

## POST /api/knowledge_graph/extract

- success: bool
- request_id: string
- user_id: string
- source: string
- detected_concepts: string[]
- new_concept_count: number
- relations: relation[]
- extraction_method: one of ai|rule
- ai_extract: object
- mapping_results: mapping_result[]
- top_mapping: mapping_result
- graph_sync: object

## POST /api/knowledge_graph/map

- success: bool
- request_id: string
- user_id: string
- total_count: number
- concept_library_size: number
- method: object
- method.extract_method: keyword_rule
- method.similarity_method: substring+keyword_overlap+sequence_match
- method.merge_method: normalize_equal|prefix_suffix|sequence_match>=0.82
- method.model: none
- method.bert_enabled: false
- method.thresholds: object
- mapping_results: mapping_result[]

mapping_result fields:
- 原始内容: string
- 知识点: string
- 置信度: number (0-1)

## POST /api/auth/register

请求：
- username: string（3-32 位）
- password: string（至少 8 位，且含字母与数字）
- display_name: string
- locale: CN|EN
- guest_user_id: string（可选；注册时自动继承访客学习数据）

响应新增：
- recovery_code: string（格式 XXXX-XXXX，只返回一次，服务端仅存哈希）
- binding: object（migrated / plans / spaces / space_items / concepts / relations / events）

错误码：`WEAK_PASSWORD`（密码强度不足）、`AUTH_USER_EXISTS`、`AUTH_DISPLAY_NAME_EXISTS`

## POST /api/auth/login

请求：
- username / password
- guest_user_id: string（可选）
- adopt_guest_data: bool（可选，默认 false）

说明：
- 默认**不合并**访客数据，避免公共设备上的他人进度污染账号；
  只有 `adopt_guest_data=true` 时才调用数据迁移。
- 连续 5 次密码错误后账号锁定 10 分钟，返回 `429` + `AUTH_LOCKED`。

## PUT /api/auth/profile

修改当前账号资料，需 `Authorization: Bearer <token>`。

请求（字段均可选）：
- `display_name`：昵称，最长 24 字符
- `bio`：个人简介，最长 500 字符（超长自动截断）
- `locale`：`CN` | `EN`

响应：`user`（公开字段）
错误码：`AUTH_DISPLAY_NAME_EXISTS`（昵称与他人重复）、`AUTH_REQUIRED`

## POST /api/auth/change-password

需 `Authorization: Bearer <token>`。

请求：`old_password`、`new_password`
响应：`revoked_sessions`（本次被撤销的其他会话数）
错误码：`AUTH_INVALID_CREDENTIALS`、`WEAK_PASSWORD`

## POST /api/auth/recovery/issue

需登录。响应 `recovery_code`（新码），旧码立即失效。

## POST /api/auth/recovery/reset

无需登录。
请求：`username`、`recovery_code`、`new_password`
响应：`revoked_sessions`、`recovery_code`（自动轮换）
说明：账号不存在与恢复码错误统一返回 `RECOVERY_FAILED`，避免账号枚举。

## GET /api/auth/sessions

需登录。响应：
- sessions: array
  - session_id / created_at / last_seen_at / expires_at / current

已撤销与已过期的会话不会返回。

## POST /api/auth/sessions/revoke

需登录。
请求：`session_id`（退出指定设备）或 `all_others: true`（退出其他所有设备）
响应：`revoked`（数量）
错误码：`SESSION_NOT_FOUND`；退出当前设备需用 `/logout`，此接口返回 `INVALID_INPUT`。

## POST /api/question_bank/practice-session

保存一次完整练习的汇总（单题作答仍走 `/answer`）。

请求：
- user_id
- session: object（id / title / concept / scope / difficulty / items / answers / elapsedSeconds / completedAt）

响应：
- session: object
  - total_count / answered_count / correct_count
  - accuracy: number（correct_count / total_count）
  - elapsed_seconds / timestamp / concept / title

## GET /api/question_bank/practice-sessions

请求参数：`user_id`、可选 `limit`
响应：`count`、`items`（时间倒序，最多 50 条）

## GET /api/spaces/search

跨空间搜索资料条目。

请求参数：
- `user_id`
- `q`：关键词（必填，最长 60 字符）
- `limit`：可选，1-50，默认 20

响应：
- `query` / `count`
- `results`: array
  - `space_id` / `space_name`
  - `item_id` / `name` / `kind`
  - `snippet`：命中位置前后约 160 字的片段
  - `updated_at`

说明：
- 匹配范围为条目名称、摘要、正文前 4000 字与标签；
- 不读取 `fileDataUrl`，避免把 base64 内容当作可搜索文本；
- 关键词为空返回 `INVALID_INPUT`。
