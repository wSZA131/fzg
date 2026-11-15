"""诊断与错题蓝图：错题归因分析、诊断报告、错题库。

诊断/错题相关的工具函数（collect_concept_question_history、build_diagnosis_source_key、
diagnosis_engine 等）保留在 server 模块中，本模块通过 ``_server()`` 延迟获取，
保持与测试 patch 的兼容，同时规避循环依赖。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

from ..services.mastery_engine import build_learning_advice, calculate_concept_mastery
from ..utils.http import error_response, get_request_id, success_payload

diagnosis_bp = Blueprint("diagnosis", __name__, url_prefix="/api/diagnosis")
wrong_questions_bp = Blueprint("wrong_questions", __name__, url_prefix="/api/wrong_questions")


def _server():
    """延迟获取 server 模块，保持共享函数与测试 patch 的兼容。"""
    from .. import server
    return server


@diagnosis_bp.route("/analyze", methods=["POST"])
def cognitive_diagnosis_api():
    """错题归因分析接口。"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    question = (data.get('question') or '').strip()
    correct_answer = (data.get('correct_answer') or '').strip()
    user_answer = (data.get('user_answer') or '').strip()
    concept = s.normalize_concept_name(data.get('concept') or '')
    response_time_seconds = data.get("response_time_seconds", data.get("duration_seconds"))

    if not question or not correct_answer or not user_answer:
        return error_response(request_id, 400, "INVALID_INPUT", "question、correct_answer、user_answer 不能为空")

    concept_history = s.collect_concept_question_history(user_id, concept, current_record=None, limit=10) if concept else []
    mastery_assessment = calculate_concept_mastery(concept, concept_history) if concept_history else None
    concept_mastery = (
        mastery_assessment.get("掌握度")
        if isinstance(mastery_assessment, dict)
        else s.get_concept_mastery_from_knowledge(user_id, concept)
    )

    diagnosis = s.diagnosis_engine.analyze_error(
        question=question,
        answer=correct_answer,
        user_answer=user_answer,
        concept=concept,
        concept_mastery=concept_mastery,
        response_time_seconds=response_time_seconds,
        attempt_count=(mastery_assessment.get("作答次数") if isinstance(mastery_assessment, dict) else len(concept_history)),
        history_records=concept_history,
    )
    learning_advice = build_learning_advice(
        error_type=diagnosis.get("error_type", "知识性错误"),
        mastery_score=concept_mastery,
        concept=concept,
        attempt_count=(mastery_assessment.get("作答次数") if isinstance(mastery_assessment, dict) else len(concept_history)),
    )
    diagnosis = {
        **(diagnosis if isinstance(diagnosis, dict) else {}),
        "recommendation": (learning_advice or {}).get("建议") or (diagnosis or {}).get("recommendation", ""),
        "reason": (learning_advice or {}).get("原因") or (diagnosis or {}).get("reason", ""),
        "recommended_actions": (learning_advice or {}).get("推荐行动") or (diagnosis or {}).get("recommended_actions", []),
    }

    request_fact_source = data.get("fact_source") if isinstance(data.get("fact_source"), dict) else {}
    primary_fact = s.find_primary_question_answer_fact(
        user_id=user_id,
        question=question,
        correct_answer=correct_answer,
        user_answer=user_answer,
        concept=concept,
        question_id=data.get("question_id"),
    )
    fact_source = request_fact_source or (
        primary_fact.get("fact_source")
        if isinstance(primary_fact, dict) and isinstance(primary_fact.get("fact_source"), dict)
        else {}
    )
    if not fact_source:
        fact_source = s.build_evaluation_fact_source(
            primary_source="diagnosis_input",
            fact_id=str(uuid.uuid4()),
            source_key="",
            question_id=data.get("question_id"),
            concept=concept,
            timestamp=datetime.now().isoformat(),
        )

    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "correct_answer": correct_answer[:200],
        "user_answer": user_answer[:200],
        "concept": concept,
        "diagnosis": diagnosis,
        "learning_advice": learning_advice,
        "mastery_assessment": mastery_assessment,
        "fact_source": fact_source,
        "source_key": s.build_diagnosis_source_key(
            fact_source=fact_source,
            question=question,
            correct_answer=correct_answer,
            user_answer=user_answer,
            concept=concept,
        ),
        "source": "diagnosis",
        "is_explanation_layer": True,
    }
    diagnosis_recorded, diagnosis_record = s.append_diagnosis_event_once(user_id, record)
    runtime_refresh = s.refresh_learning_runtime_cache(
        user_id=user_id,
        reason="diagnosis",
        focus_concept=concept,
        recommendation_limit=4,
        context={
            "source": "diagnosis",
            "concept": concept,
            "question_id": str(data.get("question_id") or "").strip(),
            "fact_source": fact_source,
        },
    )

    return jsonify(success_payload(
        request_id,
        diagnosis=diagnosis,
        learning_advice=learning_advice,
        mastery_assessment=mastery_assessment,
        profile=(runtime_refresh.get("profile", {}) if isinstance(runtime_refresh, dict) else {}),
        recommendations=(runtime_refresh.get("recommendations", []) if isinstance(runtime_refresh, dict) else []),
        fact_source=fact_source,
        diagnosis_recorded=diagnosis_recorded,
        diagnosis_record=(diagnosis_record if isinstance(diagnosis_record, dict) else record),
        graph_sync={
            "enabled": False,
            "mode": "explanation_only",
            "synced": False,
            "reason": "diagnosis_is_explanation_layer",
        },
        error_code="",
        error_message="",
    ))


@diagnosis_bp.route("/report", methods=["GET"])
def cognitive_diagnosis_report_api():
    """获取用户诊断统计报告。"""
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_current_request_user_id_from_args()
    if auth_error:
        return auth_error
    result = s.build_diagnosis_report_response(user_id)
    if isinstance(result, dict):
        result["request_id"] = request_id
    return jsonify(result)


@wrong_questions_bp.route("", methods=["GET"])
def wrong_question_bank_api():
    """获取错题库列表。"""
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_request_user_id_from_args()
    if auth_error:
        return auth_error

    items = s.load_user_event_list(user_id, "wrong_question")
    normalized_items = [
        s.deep_copy_data(item, {})
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
    ]
    normalized_items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        count=len(normalized_items),
        items=normalized_items[:100],
        error_code="",
        error_message="",
    ))
