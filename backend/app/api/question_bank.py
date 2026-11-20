"""题库蓝图：抽题、查看、新增、导题、生题与判题。

题库领域依赖大量跨域函数（组卷/判题/诊断/掌握度/错题/学习反馈），这些
函数保留在 server 模块中，本模块通过 ``_server()`` 延迟获取，保持与测试
patch 的兼容，同时规避循环依赖。
"""
from __future__ import annotations

import random
import re
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

from ..services.mastery_engine import build_learning_advice, calculate_concept_mastery
from ..services.question_evaluator import SUPPORTED_QUESTION_TYPES, normalize_question_type
from ..utils.http import error_response, get_request_id, success_payload

question_bank_bp = Blueprint("question_bank", __name__, url_prefix="/api/question_bank")
QUESTION_TYPES = set(SUPPORTED_QUESTION_TYPES)


def _server():
    """延迟获取 server 模块，保持共享函数与测试 patch 的兼容。"""
    from .. import server
    return server


def _compact_text(text, limit=70):
    compact = " ".join(str(text or "").split())
    if len(compact) <= int(limit):
        return compact
    return compact[: max(1, int(limit))] + "..."


def normalize_material_points(raw_points, limit=12):
    points = []
    seen = set()
    for raw in raw_points if isinstance(raw_points, list) else []:
        if len(points) >= limit:
            break
        if isinstance(raw, str):
            title, detail = raw.strip(), raw.strip()
        elif isinstance(raw, dict):
            title = str(raw.get("title") or raw.get("name") or "").strip()
            detail = str(raw.get("detail") or raw.get("content") or title).strip()
        else:
            continue
        key = (title or detail).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        points.append({"title": title or detail[:20], "detail": detail or title})
    return points


def collect_material_items(space_payload, item_ids=None, space_id=""):
    """按条目或空间收集可用于出题的学习资料。"""
    target_ids = {str(item or "").strip() for item in (item_ids or []) if str(item or "").strip()}
    target_space = str(space_id or "").strip()
    items = []
    for space in (space_payload.get("spaces", []) if isinstance(space_payload, dict) else []):
        if not isinstance(space, dict):
            continue
        current_space_id = str(space.get("id") or "").strip()
        if target_space and current_space_id != target_space:
            continue
        for item in (space.get("items", []) if isinstance(space.get("items"), list) else []):
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or "").strip().lower() == "folder":
                continue
            item_id = str(item.get("id") or "").strip()
            if target_ids and item_id not in target_ids:
                continue
            if not str(item.get("content") or "").strip() and not item.get("knowledgePoints"):
                continue
            items.append({**item, "spaceId": current_space_id, "spaceName": str(space.get("name") or "")})
    return items


def build_material_context(items, limit_chars=4000):
    lines = []
    for item in items if isinstance(items, list) else []:
        name = str(item.get("name") or "学习资料").strip()
        lines.append(f"【资料】{name}")
        for point in normalize_material_points(item.get("knowledgePoints"), limit=8):
            lines.append(f"- 知识点：{point['title']}｜{_compact_text(point['detail'], 120)}")
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"原文节选：{_compact_text(content, 1200)}")
    return "\n".join(lines)[:limit_chars]


def build_questions_from_material_points(concept, points, difficulty, count):
    """无 AI 时依据知识点直接组题，保证资料出题链路可用。"""
    s = _server()
    pool = [point for point in (points or []) if str(point.get("detail") or "").strip()]
    if not pool:
        return []

    concept_text = s.normalize_concept_name(concept or "") or _compact_text(pool[0]["title"], 24) or "资料知识点"
    level = str(difficulty or "medium").strip().lower()
    if level not in {"easy", "medium", "hard"}:
        level = "medium"
    target = max(1, min(10, int(count or 5)))
    questions = []
    for index in range(target):
        point = pool[index % len(pool)]
        title = _compact_text(point.get("title") or "该知识点", 24)
        detail = _compact_text(point.get("detail"), 80)
        if not detail:
            continue

        if index % 2 == 0:
            distractors = []
            for other in pool:
                if other is point:
                    continue
                candidate = _compact_text(other.get("detail"), 60)
                if candidate and candidate not in distractors and candidate != detail:
                    distractors.append(candidate)
                if len(distractors) >= 3:
                    break
            fallback_distractors = [
                "资料中没有提到这一说法",
                "资料中的表述与该说法相反",
                "资料只给出了定义，并没有相关结论",
            ]
            for candidate in fallback_distractors:
                if len(distractors) >= 3:
                    break
                if candidate not in distractors:
                    distractors.append(candidate)
            options = [f"A. {detail}"] + [
                f"{letter}. {text}"
                for letter, text in zip(["B", "C", "D"], distractors[:3])
            ]
            raw_item = {
                "concept": concept_text,
                "difficulty": level,
                "question_type": "single_choice",
                "question": f"根据学习资料，关于「{title}」的表述，正确的是（ ）",
                "options": options,
                "answer": "A",
                "analysis": f"资料原文：{detail}",
            }
        else:
            raw_item = {
                "concept": concept_text,
                "difficulty": level,
                "question_type": "short_answer",
                "question": f"请结合学习资料解释「{title}」，并说明它在资料中的作用。",
                "options": [],
                "answer": detail,
                "analysis": f"作答时应覆盖资料中的关键表述：{detail}",
            }

        normalized = s.normalize_question_item(
            raw_item,
            fallback_id=f"qb-material-{uuid.uuid4().hex[:12]}",
            creator="official_ai",
            is_public_default=True,
            bank_source="official_ai",
        )
        if normalized:
            normalized["created_by"] = "official_ai"
            normalized["bank_source"] = "official_ai"
            questions.append(normalized)
    return questions


@question_bank_bp.route("/draw", methods=["GET"])
def draw_question_from_bank_api():
    """题库抽题：按指定知识点抽题并发问。"""
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    concept = s.normalize_concept_name(request.args.get('concept', '') or '')
    difficulty = (request.args.get('difficulty', '') or '').strip().lower()
    bank_scope = s.normalize_question_bank_scope(request.args.get('bank_scope', 'both') or 'both')
    raw_question_type = (request.args.get('question_type', '') or '').strip().lower()
    requested_type = normalize_question_type(raw_question_type) if raw_question_type else ''
    if requested_type not in QUESTION_TYPES:
        requested_type = ''

    if not concept:
        return error_response(
            request_id,
            400,
            "INVALID_INPUT",
            "请先填写要考察的知识点",
            required_field="concept",
        )

    # 官方题库抽题时自动生题，避免题目长期不变。
    if bank_scope in {"ai", "both"}:
        existing_bank, _ = s.build_question_bank_for_user(user_id)
        official_ai_count = sum(1 for x in existing_bank if str(x.get("bank_source") or "") == "official_ai")
        has_requested_type = (not requested_type) or any(
            normalize_question_type(x.get("question_type")) == requested_type
            and s.question_item_in_scope(x, bank_scope, user_id=user_id)
            for x in existing_bank
        )
        should_generate = (not has_requested_type) or random.random() < 0.2
        if should_generate:
            if requested_type:
                generate_count = 1
            else:
                generate_count = 3 if official_ai_count < 5 else 1
            generated_items, _ = s.generate_official_questions_with_ai(
                concept,
                difficulty or "medium",
                generate_count,
                preferred_type=requested_type,
            )
            if generated_items:
                official_items = s.load_official_question_bank_items()
                official_items.extend(generated_items)
                s.save_official_question_bank_items(official_items)

    bank, mastery_map = s.build_question_bank_for_user(user_id)
    if requested_type:
        bank = [item for item in bank if normalize_question_type(item.get("question_type")) == requested_type]
    question_item = s.select_question_from_bank(
        bank,
        mastery_map,
        concept=concept,
        difficulty=difficulty,
        recent_ids=s.get_recent_drawn_question_ids(user_id, limit=8),
        bank_scope=bank_scope,
        user_id=user_id,
    )

    if not question_item:
        return error_response(
            request_id,
            404,
            "QUESTION_NOT_FOUND",
            "未找到满足条件的题目",
            concept=concept,
            difficulty=difficulty,
            question_type=requested_type,
        )

    prompt_text = s.build_question_prompt_text(question_item)
    event_payload = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "question_id": question_item.get("id"),
        "concept": question_item.get("concept"),
        "difficulty": question_item.get("difficulty"),
        "question_type": question_item.get("question_type"),
    }
    s.append_user_event(user_id, "question_draw", event_payload)

    return jsonify(success_payload(
        request_id,
        message="抽题成功",
        user_id=user_id,
        question={
            "id": question_item.get("id"),
            "concept": question_item.get("concept"),
            "difficulty": question_item.get("difficulty"),
            "question_type": question_item.get("question_type"),
            "question": question_item.get("question"),
            "options": question_item.get("options", []),
            "bank_source": question_item.get("bank_source", "official_template"),
        },
        prompt_text=prompt_text,
        bank_size=len(bank),
        filters={
            "concept": concept,
            "difficulty": difficulty,
            "bank_scope": bank_scope,
        },
        error_code="",
        error_message="",
    ))


@question_bank_bp.route("/questions", methods=["GET"])
def list_question_bank_questions_api():
    """查看题库（默认仅返回当前用户可见题）。"""
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    concept = s.normalize_concept_name(request.args.get('concept', '') or '')
    difficulty = (request.args.get('difficulty', '') or '').strip().lower()
    bank_scope = s.normalize_question_bank_scope(request.args.get('bank_scope', 'both') or 'both')

    bank, _ = s.build_question_bank_for_user(user_id)
    items = []
    for item in bank:
        if not s.question_item_in_scope(item, bank_scope, user_id=user_id):
            continue
        if concept and s.normalize_concept_name(item.get("concept") or "") != concept:
            continue
        if difficulty and str(item.get("difficulty") or "").strip().lower() != difficulty:
            continue
        items.append({
            "id": item.get("id"),
            "concept": item.get("concept"),
            "difficulty": item.get("difficulty"),
            "question_type": item.get("question_type"),
            "question": item.get("question"),
            "options": item.get("options", []),
            "created_by": item.get("created_by", "system"),
            "is_public": bool(item.get("is_public", True)),
            "bank_source": item.get("bank_source", "official_template"),
        })

    neo4j_available = s.neo4j_store.ensure_connected()

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        bank_scope=bank_scope,
        count=len(items),
        questions=items,
        error_code="",
        error_message="",
    ))


@question_bank_bp.route("/questions", methods=["POST"])
def add_question_bank_question_api():
    """动态新增题目到可扩展题库。"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    normalized = s.normalize_question_item(
        raw=data,
        fallback_id=f"qb-custom-{uuid.uuid4().hex[:12]}",
        creator=user_id,
        is_public_default=False,
        bank_source="user_custom",
    )
    if not normalized:
        return error_response(request_id, 400, "INVALID_INPUT", "题目信息不完整或格式错误")

    custom_items = s.load_custom_question_bank_items()
    custom_items = [item for item in custom_items if str(item.get("id") or "") != normalized["id"]]
    custom_items.append(normalized)
    s.save_custom_question_bank_items(custom_items)

    return jsonify(success_payload(
        request_id,
        message="题目已加入动态题库",
        user_id=user_id,
        question={
            "id": normalized["id"],
            "concept": normalized["concept"],
            "difficulty": normalized["difficulty"],
            "question_type": normalized["question_type"],
            "question": normalized["question"],
            "options": normalized.get("options", []),
            "bank_source": normalized.get("bank_source", "user_custom"),
        },
        custom_bank_count=len(custom_items),
        error_code="",
        error_message="",
    ))


@question_bank_bp.route("/import", methods=["POST"])
def import_question_bank_question_api():
    """粘贴板导题：支持 JSON 或行文本批量导入。"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    text = str(data.get('text') or '').strip()

    if not text:
        return error_response(request_id, 400, "INVALID_INPUT", "导入文本不能为空")

    imported, errors = s.parse_import_questions_text(text, user_id)
    if not imported:
        return error_response(request_id, 400, "INVALID_INPUT", "未解析到有效题目", parse_errors=errors[:8])

    custom_items = s.load_custom_question_bank_items()
    ids = {str(x.get("id") or "") for x in custom_items}
    for item in imported:
        if str(item.get("id") or "") in ids:
            item["id"] = f"qb-import-{uuid.uuid4().hex[:12]}"
        custom_items.append(item)
    s.save_custom_question_bank_items(custom_items)

    return jsonify(success_payload(
        request_id,
        message="导题成功",
        user_id=user_id,
        imported_count=len(imported),
        custom_bank_count=len(custom_items),
        parse_errors=errors[:8],
        error_code="",
        error_message="",
    ))


@question_bank_bp.route("/generate", methods=["POST"])
def generate_question_bank_question_api():
    """官方题库：通过 AI 批量生题并入库。"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    concept = s.normalize_concept_name(data.get('concept') or '')
    difficulty = (data.get('difficulty', 'medium') or 'medium').strip().lower()
    try:
        count = int(data.get('count', 3) or 3)
    except Exception:
        count = 3
    count = max(1, min(10, count))

    questions, mode = s.generate_official_questions_with_ai(concept, difficulty, count)
    if not questions:
        return error_response(request_id, 502, "QUESTION_GENERATE_FAILED", "官方题库生题失败")

    official_items = s.load_official_question_bank_items()
    official_items.extend(questions)
    s.save_official_question_bank_items(official_items)

    return jsonify(success_payload(
        request_id,
        message="官方题库生题完成",
        user_id=user_id,
        generate_mode=mode,
        generated_count=len(questions),
        official_bank_count=len(s.load_official_question_bank_items()),
        sample_questions=[
            {
                "id": q.get("id"),
                "concept": q.get("concept"),
                "difficulty": q.get("difficulty"),
                "question_type": q.get("question_type"),
                "question": q.get("question"),
                "bank_source": q.get("bank_source", "official_ai"),
            }
            for q in questions[:5]
        ],
        error_code="",
        error_message="",
    ))


@question_bank_bp.route("/generate_from_material", methods=["POST"])
def generate_question_from_material_api():
    """资料出题：基于上传资料抽取的知识点与正文生成练习题并入题库。"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    raw_ids = data.get("item_ids") if isinstance(data.get("item_ids"), list) else []
    item_ids = [str(item or "").strip() for item in raw_ids if str(item or "").strip()]
    single_item_id = str(data.get("item_id") or "").strip()
    if single_item_id and single_item_id not in item_ids:
        item_ids.append(single_item_id)
    space_id = str(data.get("space_id") or "").strip()
    knowledge_point = str(data.get("knowledge_point") or "").strip()
    difficulty = str(data.get("difficulty") or "medium").strip().lower()
    try:
        count = int(data.get("count", 5) or 5)
    except Exception:
        count = 5
    count = max(1, min(10, count))

    space_payload = s.get_user_space_payload(user_id)
    materials = collect_material_items(space_payload, item_ids=item_ids, space_id=space_id)
    if not materials:
        return error_response(
            request_id,
            400,
            "MATERIAL_NOT_FOUND",
            "请先上传包含文字内容的学习资料，再尝试资料出题",
        )

    points = []
    for item in materials:
        points.extend(normalize_material_points(item.get("knowledgePoints"), limit=8))
    if not points:
        from ..services.document_ingest import extract_knowledge_points
        for item in materials:
            points.extend(normalize_material_points(
                extract_knowledge_points(item.get("content"), limit=8),
                limit=8,
            ))
    if not points:
        # 没有结构化知识点时，用正文中的完整句子兜底，保证资料仍可出题
        for item in materials:
            body = str(item.get("content") or "")
            for sentence in re.split(r"[。！？；!?;\n]+|(?<=\.)\s+", body):
                sentence = str(sentence or "").strip()
                if 16 <= len(sentence) <= 80:
                    points.append({
                        "title": sentence[:16],
                        "detail": sentence,
                        "weight": 0.2,
                    })
                if len(points) >= 8:
                    break
            if len(points) >= 8:
                break
    points = normalize_material_points(points, limit=16)
    concept = (knowledge_point or (points[0]["title"] if points else "") or str(materials[0].get("name") or "")).strip()

    material_context = build_material_context(materials)
    questions, mode = s.generate_official_questions_with_ai(
        concept,
        difficulty,
        count,
        material_context=material_context,
    )
    if questions:
        forced_concept = s.normalize_concept_name(concept or "")
        if forced_concept:
            for question in questions:
                question["concept"] = forced_concept
    else:
        questions = build_questions_from_material_points(concept, points, difficulty, count)
        mode = "material_local" if questions else mode

    if not questions:
        return error_response(
            request_id,
            502,
            "QUESTION_GENERATE_FAILED",
            "资料内容不足，暂未生成题目，请补充更完整的资料后重试",
        )

    official_items = s.load_official_question_bank_items()
    official_items.extend(questions)
    s.save_official_question_bank_items(official_items)

    return jsonify(success_payload(
        request_id,
        message="资料出题完成",
        user_id=user_id,
        generate_mode=mode,
        concept=concept,
        generated_count=len(questions),
        knowledge_points=points[:8],
        material_count=len(materials),
        material_names=[str(item.get("name") or "") for item in materials[:5]],
        official_bank_count=len(s.load_official_question_bank_items()),
        sample_questions=[
            {
                "id": q.get("id"),
                "concept": q.get("concept"),
                "difficulty": q.get("difficulty"),
                "question_type": q.get("question_type"),
                "question": q.get("question"),
                "bank_source": q.get("bank_source", "official_ai"),
            }
            for q in questions[:5]
        ],
        error_code="",
        error_message="",
    ))


@question_bank_bp.route("/answer", methods=["POST"])
def answer_question_bank_question_api():
    """提交题库答案并返回判题反馈。"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    question_id = str(data.get('question_id') or '').strip()
    user_answer = str(data.get('user_answer') or '').strip()

    if not question_id:
        return error_response(request_id, 400, "INVALID_INPUT", "question_id 不能为空")
    if not user_answer:
        return error_response(request_id, 400, "INVALID_INPUT", "user_answer 不能为空")

    question_item = s.find_question_by_id(user_id, question_id)
    if not question_item:
        return error_response(request_id, 404, "QUESTION_NOT_FOUND", "题目不存在或不可见")

    now_dt = datetime.now()
    evaluation = s.evaluate_question_answer(question_item, user_answer)
    duration_seconds = data.get("duration_seconds", None)
    if duration_seconds in ("", None):
        duration_seconds = s.infer_question_answer_duration_seconds(user_id, question_id, now_dt=now_dt)
    else:
        try:
            duration_seconds = max(0.0, min(7200.0, float(duration_seconds)))
        except Exception:
            duration_seconds = s.infer_question_answer_duration_seconds(user_id, question_id, now_dt=now_dt)

    event_payload = {
        "id": str(uuid.uuid4()),
        "timestamp": now_dt.isoformat(),
        "question_id": question_id,
        "concept": question_item.get("concept"),
        "difficulty": question_item.get("difficulty"),
        "question_type": question_item.get("question_type"),
        "question": question_item.get("question"),
        "expected_answer": question_item.get("answer"),
        "user_answer": user_answer,
        "is_correct": bool(evaluation.get("is_correct", False)),
        "score": float(evaluation.get("score", 0.0) or 0.0),
        "evaluation_method": evaluation.get("evaluation_method", "rule"),
        "scoring_type": evaluation.get("scoring_type", question_item.get("question_type") or "short_answer"),
        "evaluation_summary": evaluation.get("summary", ""),
        "evaluation_breakdown": evaluation.get("breakdown", []),
        "evaluation_evidence": evaluation.get("evidence", {}),
    }
    if duration_seconds is not None:
        event_payload["duration_seconds"] = round(float(duration_seconds), 3)
    event_payload["answer_signature"] = s.build_evaluation_answer_signature(
        question=question_item.get("question"),
        correct_answer=evaluation.get("expected_answer", ""),
        user_answer=user_answer,
        concept=question_item.get("concept"),
        question_id=question_id,
    )
    event_payload["fact_source"] = s.build_evaluation_fact_source(
        primary_source="question_answer",
        fact_id=event_payload["id"],
        source_key=f"question_answer::{event_payload['id']}",
        question_id=question_id,
        concept=question_item.get("concept"),
        timestamp=event_payload["timestamp"],
    )

    concept = s.normalize_concept_name(question_item.get("concept") or "")
    concept_history_before = s.collect_concept_question_history(
        user_id=user_id,
        concept=concept,
        current_record=None,
        limit=10,
    ) if concept else []
    concept_history = s.collect_concept_question_history(
        user_id=user_id,
        concept=concept,
        current_record=event_payload,
        limit=10,
    ) if concept else []
    diagnosis_mastery_assessment = (
        calculate_concept_mastery(concept, concept_history_before, now=now_dt)
        if concept_history_before
        else None
    )

    mastery_assessment = calculate_concept_mastery(concept, concept_history, now=now_dt) if concept_history else {
        "知识点": concept,
        "掌握度": 0.0,
        "状态": "薄弱",
    }
    mastery_snapshot = s.update_concept_mastery_snapshot(
        user_id=user_id,
        concept=concept,
        mastery_assessment=mastery_assessment,
        answered_at=event_payload["timestamp"],
    ) if concept else {}

    s.append_user_event(user_id, "question_answer", event_payload)

    diagnosis = None
    learning_advice = None
    diagnosis_recorded = False
    diagnosis_fact_source = event_payload.get("fact_source", {})
    if (not bool(evaluation.get("is_correct", False))) or s.contains_confusion_signal(user_answer):
        diagnosis = s.diagnosis_engine.analyze_error(
            question=question_item.get("question"),
            answer=evaluation.get("expected_answer", ""),
            user_answer=user_answer,
            concept=concept,
            concept_mastery=(
                diagnosis_mastery_assessment.get("掌握度")
                if isinstance(diagnosis_mastery_assessment, dict)
                else mastery_assessment.get("掌握度")
            ),
            response_time_seconds=duration_seconds,
            attempt_count=(
                diagnosis_mastery_assessment.get("作答次数")
                if isinstance(diagnosis_mastery_assessment, dict)
                else len(concept_history_before)
            ),
            history_records=concept_history_before,
        )
        learning_advice = build_learning_advice(
            error_type=diagnosis.get("error_type", "知识性错误"),
            mastery_score=mastery_assessment.get("掌握度"),
            concept=concept,
            attempt_count=mastery_assessment.get("作答次数", len(concept_history)),
        )
        diagnosis = {
            **(diagnosis if isinstance(diagnosis, dict) else {}),
            "recommendation": (learning_advice or {}).get("建议") or (diagnosis or {}).get("recommendation", ""),
            "reason": (learning_advice or {}).get("原因") or (diagnosis or {}).get("reason", ""),
            "recommended_actions": (learning_advice or {}).get("推荐行动") or (diagnosis or {}).get("recommended_actions", []),
        }

        wrong_item = s.build_wrong_question_entry(
            source="question_answer",
            question=question_item.get("question"),
            user_answer=user_answer,
            concept=question_item.get("concept"),
            topics=[question_item.get("concept")] if question_item.get("concept") else [],
            extra={
                "source_key": f"question_answer::{event_payload['timestamp']}::{question_id or question_item.get('concept') or ''}",
                "question_id": question_id,
                "difficulty": question_item.get("difficulty"),
                "question_type": question_item.get("question_type"),
                "expected_answer": evaluation.get("expected_answer", ""),
                "score": float(evaluation.get("score", 0.0) or 0.0),
                "is_correct": bool(evaluation.get("is_correct", False)),
                "error_type": diagnosis.get("error_type", ""),
                "fact_source": diagnosis_fact_source,
            },
        )
        s.append_user_event(user_id, "wrong_question", wrong_item)

        diagnosis_record = {
            "id": str(uuid.uuid4()),
            "timestamp": now_dt.isoformat(),
            "question": str(question_item.get("question") or ""),
            "correct_answer": str(evaluation.get("expected_answer", "") or "")[:200],
            "user_answer": user_answer[:200],
            "concept": concept,
            "diagnosis": diagnosis,
            "learning_advice": learning_advice,
            "mastery_assessment": mastery_assessment,
            "fact_source": diagnosis_fact_source,
            "source_key": s.build_diagnosis_source_key(
                fact_source=diagnosis_fact_source,
                question=question_item.get("question"),
                correct_answer=evaluation.get("expected_answer", ""),
                user_answer=user_answer,
                concept=concept,
            ),
            "source": "question_answer",
            "is_explanation_layer": True,
        }
        diagnosis_recorded, _ = s.append_diagnosis_event_once(user_id, diagnosis_record)

    runtime_refresh = s.refresh_learning_runtime_cache(
        user_id=user_id,
        reason="question_answer",
        focus_concept=concept,
        recommendation_limit=4,
        context={
            "source": "question_answer",
            "question_id": question_id,
            "concept": concept,
            "score": float(evaluation.get("score", 0.0) or 0.0),
            "is_correct": bool(evaluation.get("is_correct", False)),
            "task_timestamp": event_payload["timestamp"],
        },
    )

    return jsonify(success_payload(
        request_id,
        message="判题完成",
        user_id=user_id,
        question_id=question_id,
        concept=question_item.get("concept"),
        is_correct=bool(evaluation.get("is_correct", False)),
        score=float(evaluation.get("score", 0.0) or 0.0),
        expected_answer=evaluation.get("expected_answer", ""),
        feedback=evaluation.get("feedback", ""),
        evaluation_method=evaluation.get("evaluation_method", "rule"),
        scoring_type=evaluation.get("scoring_type", question_item.get("question_type") or "short_answer"),
        evaluation_breakdown=evaluation.get("breakdown", []),
        evaluation_evidence=evaluation.get("evidence", {}),
        evaluation_summary=evaluation.get("summary", ""),
        duration_seconds=event_payload.get("duration_seconds"),
        mastery_assessment=mastery_assessment,
        graph_sync=(mastery_snapshot.get("graph_sync", {}) if isinstance(mastery_snapshot, dict) else {}),
        diagnosis=diagnosis,
        diagnosis_recorded=diagnosis_recorded,
        fact_source=diagnosis_fact_source,
        learning_advice=learning_advice,
        profile=(runtime_refresh.get("profile", {}) if isinstance(runtime_refresh, dict) else {}),
        recommendations=(runtime_refresh.get("recommendations", []) if isinstance(runtime_refresh, dict) else []),
        review_reminders=(runtime_refresh.get("review_reminders", {}) if isinstance(runtime_refresh, dict) else {}),
        next_action="继续点击题库抽题进行下一题",
        error_code="",
        error_message="",
    ))


@question_bank_bp.route("/practice-session", methods=["POST"])
def save_practice_session_api():
    """保存一次完整练习的汇总结果。

    单题作答已通过 /answer 落库，但整场练习的标题、用时、正确率此前只存在
    浏览器 localStorage，换设备即丢失。这里按事件方式补一条汇总记录。
    """
    s = _server()
    request_id = get_request_id()
    data = request.get_json(silent=True) or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    session = data.get("session")
    if not isinstance(session, dict):
        return error_response(request_id, 400, "INVALID_INPUT", "session 必须是对象")

    raw_items = session.get("items") if isinstance(session.get("items"), list) else []
    answers = session.get("answers") if isinstance(session.get("answers"), dict) else {}

    total_count = 0
    answered_count = 0
    correct_count = 0
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        total_count += 1
        answer = answers.get(str(item.get("id") or ""))
        if not isinstance(answer, dict):
            continue
        answered_count += 1
        if answer.get("correct"):
            correct_count += 1

    try:
        elapsed_seconds = int(float(session.get("elapsedSeconds") or 0))
    except (TypeError, ValueError):
        elapsed_seconds = 0

    payload = {
        "id": str(session.get("id") or "").strip() or uuid.uuid4().hex,
        "timestamp": datetime.now().isoformat(),
        "title": str(session.get("title") or "").strip()[:120],
        "concept": str(session.get("concept") or "").strip()[:80],
        "scope": str(session.get("scope") or "").strip()[:40],
        "difficulty": str(session.get("difficulty") or "").strip()[:40],
        "total_count": total_count,
        "answered_count": answered_count,
        "correct_count": correct_count,
        "accuracy": round(correct_count / total_count, 4) if total_count else 0.0,
        "elapsed_seconds": max(0, elapsed_seconds),
        "completed_at": str(session.get("completedAt") or ""),
        "source": "practice_page",
    }
    s.append_user_event(user_id, "practice_session", payload)

    return jsonify(success_payload(
        request_id,
        message="练习记录已保存",
        session=payload,
        error_code="",
        error_message="",
    ))


@question_bank_bp.route("/practice-sessions", methods=["GET"])
def list_practice_sessions_api():
    """读取练习历史，按时间倒序，最多 50 条。"""
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_request_user_id_from_args()
    if auth_error:
        return auth_error

    raw_items = s.load_user_event_list(user_id, "practice_session")
    items = [
        s.deep_copy_data(item, {})
        for item in (raw_items if isinstance(raw_items, list) else [])
        if isinstance(item, dict)
    ]
    items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        count=len(items),
        items=items[:50],
        error_code="",
        error_message="",
    ))
