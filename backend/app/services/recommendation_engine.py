"""首页探索推荐引擎。

探索是额外的外部资源推荐：
- 只返回 Wikipedia、Wikibooks、YouTube 等开放 API 资源；
- 用户画像、知识掌握度和复习状态只用于决定查询哪些主题；
- 不返回用户空间资料、AI 讲解或题库任务。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from .topic_guard import is_learning_topic


ENGINE_VERSION = 7
CACHE_TTL_SECONDS = 600
MAX_LIMIT = 12
RECENT_IMPRESSION_HOURS = 24
DISMISS_COOLDOWN_DAYS = 30
OPEN_RESOURCE_QUERY_LIMIT = 4

RESOURCE_KIND_LABELS = {
    "open_article": "百科",
    "open_textbook": "教材",
    "open_lesson": "课程",
    "open_paper": "论文",
    "open_video": "视频",
    "external_book": "图书",
}

RESOURCE_TYPE_LABELS = {
    "open_article": "拓展阅读",
    "open_textbook": "开放教材",
    "open_lesson": "课程资源",
    "open_paper": "学术论文",
    "open_video": "视频拓展",
    "external_book": "商业图书",
}

RESOURCE_ACTION_LABELS = {
    "open_article": "去阅读",
    "open_textbook": "去学习",
    "open_lesson": "去上课",
    "open_paper": "去阅读",
    "open_video": "看视频",
    "external_book": "去查看",
}

DEFAULT_STYLE = "visual"
STYLE_LABELS = {
    "visual": "视觉型",
    "auditory": "听觉型",
    "kinesthetic": "动觉型",
}


def _concept_key(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip()).lower()
    return re.sub(r"[·•,，。:：;；!！?？'\"“”‘’()（）\-_/]+", "", text)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if math.isfinite(number):
            return number
    except (TypeError, ValueError):
        pass
    return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _stable_id(prefix: str, concept: str, kind: str) -> str:
    digest = hashlib.sha1(f"{concept}|{kind}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _normalize_string_list(value: Any) -> List[str]:
    source = value if isinstance(value, list) else []
    result = []
    seen = set()
    for item in source:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalize_external_resource(raw: Any) -> Optional[Dict[str, Any]]:
    """规范化开放 API 返回的资源。"""
    if not isinstance(raw, dict):
        return None

    resource_id = str(raw.get("id") or "").strip()
    concept = str(raw.get("concept") or "").strip()
    title = str(raw.get("title") or "").strip()
    kind = str(raw.get("resource_kind") or "").strip().lower()
    action = raw.get("action") if isinstance(raw.get("action"), dict) else {}

    if not resource_id or not concept or not title:
        return None
    if kind not in {"open_article", "open_textbook", "open_lesson", "open_paper", "open_video", "external_book", "external_course"}:
        return None
    if not action or not str(action.get("url") or "").strip():
        return None

    normalized_kind = (
        kind
        if kind in {"open_article", "open_textbook", "open_lesson", "open_paper", "open_video", "external_book"}
        else "open_article"
    )
    duration = max(0, min(180, _safe_int(raw.get("duration_minutes"), 0)))
    return {
        "id": resource_id,
        "title": title,
        "concept": concept,
        "resource_kind": normalized_kind,
        "resource_type": str(raw.get("resource_type") or RESOURCE_TYPE_LABELS.get(normalized_kind, "拓展阅读")),
        "provider": str(raw.get("provider") or "开放资源"),
        "difficulty": str(raw.get("difficulty") or "medium").strip().lower(),
        "duration_minutes": duration,
        "cover_url": str(raw.get("cover_url") or "").strip(),
        "action": dict(action),
        "tags": _normalize_string_list(raw.get("tags")),
        "learning_styles": _normalize_string_list(raw.get("learning_styles")) or [DEFAULT_STYLE],
        "quality_score": max(0.0, min(1.0, _safe_float(raw.get("quality_score"), 0.7))),
        "source": str(raw.get("source") or "open_api"),
    }


def _build_knowledge_context(knowledge: Any) -> Dict[str, Any]:
    payload = knowledge if isinstance(knowledge, dict) else {}
    blocked = {
        _concept_key(item)
        for item in (payload.get("deleted_concepts") or [])
        if _concept_key(item)
    }
    weak = []
    concept_mastery: Dict[str, float] = {}
    for item in payload.get("concepts", []) if isinstance(payload.get("concepts"), list) else []:
        if not isinstance(item, dict):
            continue
        concept = str(item.get("concept") or "").strip()
        key = _concept_key(concept)
        if not key or key in blocked or not is_learning_topic(concept):
            continue
        mastery = max(0.0, min(1.0, _safe_float(item.get("mastery"), 0.0)))
        concept_mastery[key] = mastery
        if mastery < 0.6:
            weak.append({"concept": concept, "key": key, "mastery": mastery})
    weak.sort(key=lambda item: item["mastery"])

    graph_neighbors: Dict[str, List[Dict[str, Any]]] = {}
    for relation in payload.get("relations", []) if isinstance(payload.get("relations"), list) else []:
        if not isinstance(relation, dict):
            continue
        source = str(relation.get("source") or relation.get("from") or "").strip()
        target = str(relation.get("target") or relation.get("to") or "").strip()
        score = max(0.0, min(1.0, _safe_float(relation.get("score"), 0.5)))
        if not source or not target:
            continue
        graph_neighbors.setdefault(_concept_key(source), []).append({
            "concept": target,
            "score": score,
        })
        graph_neighbors.setdefault(_concept_key(target), []).append({
            "concept": source,
            "score": score,
        })

    return {
        "weak_concepts": weak,
        "concept_mastery": concept_mastery,
        "graph_neighbors": graph_neighbors,
        "blocked": blocked,
    }


def _build_interest_context(profile: Dict[str, Any]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    display_names: Dict[str, str] = {}

    for topic in (profile.get("interests") or []) if isinstance(profile.get("interests"), list) else []:
        text = str(topic or "").strip()
        key = _concept_key(text)
        if not key or not is_learning_topic(text):
            continue
        counts[key] = counts.get(key, 0) + 2
        display_names[key] = text

    if not counts:
        return {"scores": {}, "names": {}}

    max_count = max(counts.values()) or 1
    return {
        "scores": {
            key: round(min(1.0, value / max_count), 3)
            for key, value in counts.items()
        },
        "names": display_names,
    }


def collect_open_resource_queries(
    profile: Any,
    knowledge: Any,
    reminders: Optional[Any] = None,
    limit: int = OPEN_RESOURCE_QUERY_LIMIT,
) -> List[str]:
    """从画像、薄弱点和复习状态中选出值得查询外部资源的主题。

    探索只展示外部开放资源，用户自己的资料和 AI 生成内容不进入这里。
    """
    knowledge_context = _build_knowledge_context(knowledge)
    interest_bundle = _build_interest_context(
        profile if isinstance(profile, dict) else {},
    )
    interest_scores = interest_bundle.get("scores", {})
    interest_names = interest_bundle.get("names", {})
    due_context = _build_due_context(reminders or {})
    blocked = knowledge_context.get("blocked", set())
    safe_limit = max(1, min(_safe_int(limit, OPEN_RESOURCE_QUERY_LIMIT), 6))

    ordered_keys: List[str] = []

    def add_key(concept: Any, key: Any = None) -> None:
        concept_text = str(concept or "").strip()
        concept_key = str(key or _concept_key(concept_text)).strip()
        if not concept_text or not concept_key:
            return
        if concept_key in blocked or concept_key in ordered_keys:
            return
        if not is_learning_topic(concept_text):
            return
        ordered_keys.append(concept_key)

    for item in knowledge_context.get("weak_concepts", [])[:3]:
        add_key(item.get("concept"), item.get("key"))
    for item in due_context.values():
        add_key(item.get("concept"))
    for key, _score in sorted(interest_scores.items(), key=lambda row: row[1], reverse=True)[:3]:
        add_key(interest_names.get(key) or key, key)

    concept_by_key = {_concept_key(key): key for key in interest_names.values()}
    for item in knowledge_context.get("weak_concepts", []):
        concept_by_key[_concept_key(item.get("concept"))] = item.get("concept")
    for item in due_context.values():
        concept_by_key[_concept_key(item.get("concept"))] = item.get("concept")

    result = []
    for key in ordered_keys[:safe_limit]:
        concept = concept_by_key.get(key) or key
        if concept and concept not in result:
            result.append(concept)
    return result


def _build_due_context(reminders: Any) -> Dict[str, Dict[str, Any]]:
    payload = reminders if isinstance(reminders, dict) else {}
    due_map: Dict[str, Dict[str, Any]] = {}
    for item in payload.get("due_items", []) if isinstance(payload.get("due_items"), list) else []:
        if not isinstance(item, dict):
            continue
        concept = str(item.get("concept") or "").strip()
        key = _concept_key(concept)
        if not key or not is_learning_topic(concept):
            continue
        due_map[key] = {
            "concept": concept,
            "overdue_days": max(0, _safe_int(item.get("overdue_days"), 0)),
            "priority": max(0.0, _safe_float(item.get("priority"), 0.0)),
            "mastery": max(0.0, min(1.0, _safe_float(item.get("mastery"), 0.0))),
        }
    return due_map


def _build_diagnosis_context(diagnosis_logs: Sequence[Any]) -> Dict[str, Any]:
    recent = list(diagnosis_logs[-20:]) if isinstance(diagnosis_logs, list) else []
    category_count = {"knowledge": 0, "skill": 0, "habit": 0, "unknown": 0}
    matched_by_concept: Counter = Counter()

    for item in recent:
        if not isinstance(item, dict):
            continue
        diagnosis = item.get("diagnosis") if isinstance(item.get("diagnosis"), dict) else {}
        category = str(diagnosis.get("category") or "unknown").strip()
        if category not in category_count:
            category = "unknown"
        category_count[category] += 1
        merged = " ".join([
            str(item.get("question") or ""),
            str(item.get("user_answer") or ""),
            str(item.get("correct_answer") or ""),
            str(item.get("concept") or ""),
        ])
        concept_text = str(item.get("concept") or "").strip()
        if concept_text:
            matched_by_concept[_concept_key(concept_text)] += 1
        else:
            for token in re.findall(r"[\u4e00-\u9fffA-Za-z]{2,16}", merged):
                matched_by_concept[_concept_key(token)] += 1

    dominant_category = "unknown"
    if any(category_count.values()):
        dominant_category = max(category_count, key=category_count.get)

    return {
        "recent_count": len(recent),
        "category_count": category_count,
        "dominant_category": dominant_category,
        "matched_by_concept": dict(matched_by_concept),
    }


def _build_feedback_context(events: Sequence[Any]) -> Dict[str, Any]:
    now = datetime.now()
    recent_limit = now - timedelta(hours=RECENT_IMPRESSION_HOURS)
    dismiss_limit = now - timedelta(days=DISMISS_COOLDOWN_DAYS)
    stats: Dict[str, Dict[str, Any]] = {}
    recently_shown: Set[str] = set()
    dismissed: Set[str] = set()

    for item in events[-500:] if isinstance(events, list) else []:
        if not isinstance(item, dict):
            continue
        resource_id = str(item.get("resource_id") or "").strip()
        event_type = str(item.get("event_type") or "").strip().lower()
        if not resource_id or event_type not in {"impression", "click", "complete", "dismiss", "not_interested"}:
            continue
        event_time = _parse_datetime(item.get("timestamp"))
        if event_time is None:
            event_time = now

        bucket = stats.setdefault(resource_id, {
            "impressions": 0,
            "clicks": 0,
            "completes": 0,
            "dismisses": 0,
        })
        if event_type == "impression":
            bucket["impressions"] += 1
            if event_time >= recent_limit:
                recently_shown.add(resource_id)
        elif event_type == "click":
            bucket["clicks"] += 1
        elif event_type == "complete":
            bucket["completes"] += 1
        elif event_type in {"dismiss", "not_interested"}:
            bucket["dismisses"] += 1
            if event_time >= dismiss_limit:
                dismissed.add(resource_id)

    for bucket in stats.values():
        impressions = max(1, bucket["impressions"])
        bucket["affinity"] = max(-1.0, min(1.0, (
            bucket["clicks"] / impressions
            + 0.5 * bucket["completes"] / impressions
            - 0.8 * bucket["dismisses"] / impressions
        )))

    return {
        "stats": stats,
        "recently_shown": recently_shown,
        "dismissed": dismissed,
    }


def _build_candidates(
    knowledge_context: Dict[str, Any],
    interest_context: Dict[str, float],
    due_context: Dict[str, Dict[str, Any]],
    feedback_context: Dict[str, Any],
    open_resources: Sequence[Dict[str, Any]],
    blocked: Set[str],
    exclude_ids: Set[str],
) -> List[Dict[str, Any]]:
    """探索只允许开放 API 资源，不混入站内任务或用户资料。"""
    candidates: Dict[str, Dict[str, Any]] = {}
    dismissed = feedback_context.get("dismissed", set())
    weak_map = {item["key"]: item for item in knowledge_context.get("weak_concepts", [])}

    def add_candidate(
        resource: Dict[str, Any],
        source: str,
        mastery: Optional[float] = None,
        due_days: int = 0,
    ) -> None:
        resource_id = str(resource.get("id") or "").strip()
        concept_key = _concept_key(resource.get("concept"))
        if not resource_id or not concept_key or concept_key in blocked:
            return
        if resource_id in exclude_ids or resource_id in dismissed:
            return

        existing = candidates.get(resource_id)
        if existing:
            existing["sources"].add(source)
            if mastery is not None:
                existing["mastery"] = mastery
            if due_days > existing.get("due_days", 0):
                existing["due_days"] = due_days
            return

        candidates[resource_id] = {
            "resource": dict(resource),
            "sources": {source},
            "mastery": mastery,
            "due_days": max(0, due_days),
            "concept_key": concept_key,
        }

    for raw_resource in open_resources or []:
        resource = _normalize_external_resource(raw_resource)
        if not resource:
            continue
        concept_key = _concept_key(resource.get("concept"))
        mastery = weak_map.get(concept_key, {}).get("mastery")
        due = due_context.get(concept_key)
        add_candidate(resource, "open_resource", mastery=mastery)
        if mastery is not None:
            add_candidate(resource, "weakness", mastery=mastery)
        elif concept_key in interest_context:
            add_candidate(resource, "interest")
        if due:
            add_candidate(
                resource,
                "review_due",
                mastery=mastery if mastery is not None else due.get("mastery"),
                due_days=due.get("overdue_days", 0),
            )

    return list(candidates.values())


def _style_match(resource: Dict[str, Any], style: str) -> float:
    styles = resource.get("learning_styles") if isinstance(resource.get("learning_styles"), list) else []
    if not styles:
        return 0.4
    return 1.0 if style in styles else 0.15


def _candidate_reason_codes(candidate: Dict[str, Any], style: str) -> List[str]:
    codes = []
    sources = candidate.get("sources", set())
    if "weakness" in sources:
        codes.append("weak_mastery")
    if "review_due" in sources or candidate.get("due_days", 0) > 0:
        codes.append("review_due")
    if "interest" in sources:
        codes.append("interest_match")
    if "open_resource" in sources:
        codes.append("open_resource")
    if _style_match(candidate.get("resource", {}), style) > 0.5:
        codes.append("style_match")
    return codes


def _candidate_mode(candidate: Dict[str, Any]) -> str:
    if candidate.get("due_days", 0) > 0 or "review_due" in candidate.get("sources", set()):
        return "到期复习"
    mastery = candidate.get("mastery")
    if mastery is not None:
        if mastery < 0.35:
            return "基础回补"
        if mastery < 0.5:
            return "结构修复"
        return "稳定强化"
    if "interest" in candidate.get("sources", set()):
        return "兴趣拓展"
    return "开放拓展"


def _build_reason(candidate: Dict[str, Any], diagnosis: Dict[str, Any], style: str) -> Dict[str, Any]:
    resource = candidate["resource"]
    concept = resource.get("concept") or "该主题"
    mastery = candidate.get("mastery")
    due_days = candidate.get("due_days", 0)
    duration = resource.get("duration_minutes", 0)
    codes = _candidate_reason_codes(candidate, style)
    provider = resource.get("provider") or "开放资源"

    if due_days > 0 or "review_due" in codes:
        reason = f"「{concept}」已到复习时间，来自 {provider} 的《{resource.get('title')}》可用于今天的回顾。"
    else:
        duration_text = f"{duration} 分钟" if duration else "几分钟"
        if mastery is not None:
            reason = f"「{concept}」当前掌握度 {int(mastery * 100)}%，为你找到 {provider} 的《{resource.get('title')}》，适合用 {duration_text} 补充背景。"
        elif "interest_match" in codes:
            reason = f"你最近关注「{concept}」，来自 {provider} 的{resource.get('resource_type') or '外部资源'}可以作为拓展。"
        else:
            reason = f"围绕「{concept}」找到的{resource.get('resource_type') or '外部资源'}，可作为当前学习的补充材料。"

    return {
        "reason": reason,
        "reason_codes": codes,
        "mode": _candidate_mode(candidate),
        "focus": diagnosis.get("dominant_category", "unknown"),
    }


def _score_candidate(candidate: Dict[str, Any], context: Dict[str, Any]) -> float:
    resource = candidate["resource"]
    style = context["style"]
    mastery = candidate.get("mastery")
    concept_key = candidate["concept_key"]
    interest_score = context["interest"].get(concept_key, 0.0)
    due_score = 1.0 if candidate.get("due_days", 0) > 0 or "review_due" in candidate.get("sources", set()) else 0.0
    weakness = max(0.0, 1.0 - mastery) if mastery is not None else 0.0
    feedback = context["feedback"]["stats"].get(resource.get("id"), {})
    affinity = _safe_float(feedback.get("affinity"), 0.0)
    recently_shown = 1.0 if resource.get("id") in context["feedback"].get("recently_shown", set()) else 0.0

    raw = (
        0.32 * weakness
        + 0.20 * interest_score
        + 0.16 * due_score
        + 0.12 * _style_match(resource, style)
        + 0.10 * _safe_float(resource.get("quality_score"), 0.7)
        + 0.05 * 1.0
        + 0.05 * affinity
        - 0.30 * recently_shown
    )
    return round(max(0.0, min(1.0, raw)) * 100, 2)


def _similarity(left: Dict[str, Any], right: Dict[str, Any]) -> float:
    left_tags = set(_normalize_string_list(left.get("tags")))
    right_tags = set(_normalize_string_list(right.get("tags")))
    if not left_tags or not right_tags:
        return 0.0
    union = left_tags | right_tags
    return len(left_tags & right_tags) / len(union) if union else 0.0


def _select_diverse(candidates: Sequence[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """按资源类型轮转，保证一批里百科、教材、视频尽量都有。"""
    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    if not ranked:
        return []

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for item in ranked:
        kind = str(item["resource"].get("resource_kind") or "open_article")
        buckets.setdefault(kind, []).append(item)

    kind_order = sorted(
        buckets,
        key=lambda kind: max(item["score"] for item in buckets[kind]),
        reverse=True,
    )
    concept_count = len({item["concept_key"] for item in ranked})
    concept_cap = max(3, min(5, math.ceil(limit / max(1, concept_count)) + 1))
    selected: List[Dict[str, Any]] = []
    selected_ids = set()
    concept_counts: Counter = Counter()

    def fill_round(cap: int) -> bool:
        progressed = False
        for kind in kind_order:
            if len(selected) >= limit:
                break
            for item in buckets[kind]:
                resource_id = item["resource"].get("id")
                if resource_id in selected_ids:
                    continue
                if concept_counts[item["concept_key"]] >= cap:
                    continue
                selected.append(item)
                selected_ids.add(resource_id)
                concept_counts[item["concept_key"]] += 1
                progressed = True
                break
        return progressed

    while len(selected) < limit:
        if not fill_round(concept_cap):
            if not fill_round(10 ** 6):
                break

    return selected


def _format_item(candidate: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    resource = candidate["resource"]
    style = context["style"]
    diagnosis = context["diagnosis"]
    mastery = candidate.get("mastery")
    reason_data = _build_reason(candidate, diagnosis, style)
    category = diagnosis.get("dominant_category", "unknown")
    mode = reason_data["mode"]
    feedback = context["feedback"]["stats"].get(resource.get("id"), {})
    affinity = _safe_float(feedback.get("affinity"), 0.0)
    kind = resource.get("resource_kind", "open_article")

    priority = _score_candidate(candidate, context)
    style_label = STYLE_LABELS.get(style, "综合")
    evidence_parts = [f"画像:{style_label}({context.get('style_method') or 'rule'})"]
    if mastery is not None:
        evidence_parts.append(f"图谱:掌握度{int(mastery * 100)}%")
    if candidate.get("due_days", 0) > 0:
        evidence_parts.append(f"复习:超期{candidate['due_days']}天")
    elif "review_due" in candidate.get("sources", set()):
        evidence_parts.append("复习:今日到期")
    if feedback:
        evidence_parts.append(f"反馈:点击{feedback.get('clicks', 0)}/曝光{feedback.get('impressions', 0)}")
    if "interest" in candidate.get("sources", set()):
        evidence_parts.append("兴趣:近期命中")
    if "open_resource" in candidate.get("sources", set()):
        evidence_parts.append(f"来源:{resource.get('provider') or '开放API'}")
    evidence_brief = " | ".join(evidence_parts)

    matched_count = diagnosis.get("matched_by_concept", {}).get(candidate["concept_key"], 0)
    action = dict(resource.get("action") or {})
    action.setdefault("type", kind)
    action.setdefault("concept", resource.get("concept"))
    duration = max(0, _safe_int(resource.get("duration_minutes"), 0))

    return {
        "id": resource.get("id"),
        "concept": resource.get("concept"),
        "mastery": mastery,
        "resource_type": resource.get("resource_type") or RESOURCE_TYPE_LABELS.get(kind, "学习资源"),
        "resource_kind": kind,
        "resource_action_label": RESOURCE_ACTION_LABELS.get(kind, "去学习"),
        "title": resource.get("title"),
        "reason": reason_data["reason"],
        "reason_codes": reason_data["reason_codes"],
        "priority": priority,
        "score": priority,
        "recommend_time": f"{duration} 分钟" if duration else "开放资源",
        "duration_minutes": duration,
        "difficulty": resource.get("difficulty", "medium"),
        "provider": resource.get("provider", "开放资源"),
        "cover_url": resource.get("cover_url", ""),
        "action": action,
        "tags": resource.get("tags", []),
        "strategy_tags": [
            f"style:{style}",
            f"method:{context.get('style_method') or 'rule'}",
            f"focus:{category}",
            f"mode:{mode}",
            f"kind:{kind}",
        ],
        "evidence_brief": evidence_brief,
        "source_evidence": {
            "profile": {
                "learning_style": style,
                "style_method": context.get("style_method") or "rule",
                "style_confidence": round(_safe_float(context.get("style_scores", {}).get(style), 0.6), 3),
                "behavior_channel": style,
            },
            "knowledge_graph": {
                "concept": resource.get("concept"),
                "mastery": round(mastery, 3) if mastery is not None else None,
                "weak_threshold": 0.6,
            },
            "diagnosis": {
                "matched_count": matched_count,
                "recent_category_count": diagnosis.get("category_count", {}),
                "dominant_category": category,
                "dominant_count": diagnosis.get("category_count", {}).get(category, 0),
                "examples": [],
            },
            "recommendation": {
                "sources": sorted(candidate.get("sources", [])),
                "affinity": round(affinity, 3),
                "reason_codes": reason_data["reason_codes"],
                "engine_version": ENGINE_VERSION,
            },
        },
    }


def build_recommendation_feed(
    user_id: str,
    profile: Any,
    knowledge: Any,
    reminders: Any,
    diagnosis_logs: Optional[Sequence[Any]] = None,
    feedback_events: Optional[Sequence[Any]] = None,
    open_resources: Optional[Sequence[Any]] = None,
    limit: int = 8,
    exclude_ids: Optional[Iterable[str]] = None,
    scene: str = "home_explore",
) -> Dict[str, Any]:
    """探索推荐：只汇总开放 API 资源，用户资料与 AI 生成内容不进入这里。"""
    safe_limit = max(1, min(_safe_int(limit, 8), MAX_LIMIT))
    profile_obj = profile if isinstance(profile, dict) else {}
    style = str(profile_obj.get("learning_style") or DEFAULT_STYLE).strip().lower()
    if style not in STYLE_LABELS:
        style = DEFAULT_STYLE

    knowledge_context = _build_knowledge_context(knowledge)
    interest_bundle = _build_interest_context(profile_obj)
    interest_context = interest_bundle.get("scores", {})
    due_context = _build_due_context(reminders)
    diagnosis_context = _build_diagnosis_context(diagnosis_logs or [])
    feedback_context = _build_feedback_context(feedback_events or [])
    external_resources = [
        normalized
        for normalized in (_normalize_external_resource(item) for item in (open_resources or []))
        if normalized
    ]
    exclude_set = {str(item or "").strip() for item in (exclude_ids or []) if str(item or "").strip()}

    context = {
        "style": style,
        "style_method": profile_obj.get("style_method") or "rule",
        "style_scores": profile_obj.get("style_scores") if isinstance(profile_obj.get("style_scores"), dict) else {},
        "interest": interest_context,
        "diagnosis": diagnosis_context,
        "feedback": feedback_context,
    }
    candidates = _build_candidates(
        knowledge_context=knowledge_context,
        interest_context=interest_context,
        due_context=due_context,
        feedback_context=feedback_context,
        open_resources=external_resources,
        blocked=knowledge_context.get("blocked", set()),
        exclude_ids=exclude_set,
    )

    for candidate in candidates:
        candidate["score"] = _score_candidate(candidate, context)

    selected = _select_diverse(candidates, safe_limit)
    items = [_format_item(candidate, context) for candidate in selected]

    return {
        "items": items,
        "engine_version": ENGINE_VERSION,
        "scene": scene,
        "generated_at": datetime.now().isoformat(),
        "audit": {
            "user_id": user_id,
            "weak_concept_count": len(knowledge_context.get("weak_concepts", [])),
            "interest_count": len(interest_context),
            "due_count": len(due_context),
            "diagnosis_recent_count": diagnosis_context["recent_count"],
            "open_resource_count": len(external_resources),
            "candidate_count": len(candidates),
            "excluded_count": len(exclude_set),
            "dismissed_count": len(feedback_context.get("dismissed", set())),
        },
    }
