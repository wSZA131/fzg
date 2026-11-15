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
