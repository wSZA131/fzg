"""知识图谱蓝图：图谱查看、掌握度更新、节点删除、学习路径、知识抽取与行为映射。

图谱相关函数（build_graph_response / sync_mastery_update / build_knowledge_graph
等）保留在 server 模块中，本模块通过 ``_server()`` 延迟获取，保持与测试 patch
的兼容，同时规避循环依赖。
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from ..config import GRAPH_PRIMARY
from ..services.concept_mapping import (
    DEFAULT_MATCH_THRESHOLDS as CONCEPT_MAPPING_THRESHOLDS,
    DEFAULT_METHOD_INFO as CONCEPT_MAPPING_METHOD_INFO,
    map_learning_items,
)
from ..utils.http import error_response, get_request_id, success_payload

knowledge_graph_bp = Blueprint("knowledge_graph", __name__, url_prefix="/api/knowledge_graph")


def _server():
    """延迟获取 server 模块，保持共享函数与测试 patch 的兼容。"""
    from .. import server
    return server


@knowledge_graph_bp.route("", methods=["GET"])
def get_knowledge_graph_api():
    """获取用户知识图谱（节点/关系/掌握度）"""
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    include_documents = str(request.args.get('include_documents', 'false')).strip().lower() in {'1', 'true', 'yes', 'on'}
    min_relation_score_raw = request.args.get('min_relation_score', '')
    min_relation_score = None
    if str(min_relation_score_raw).strip() != '':
        try:
            min_relation_score = float(min_relation_score_raw)
        except Exception:
            return error_response(request_id, 400, "INVALID_INPUT", "min_relation_score 必须是 0~1 之间的数字")

    result = s.build_graph_response(user_id, min_relation_score=min_relation_score, include_documents=include_documents)
    if not isinstance(result, dict):
        return error_response(request_id, 500, "INTERNAL_ERROR", "图谱构建失败")
    result["request_id"] = request_id
    return jsonify(result)


@knowledge_graph_bp.route("/mastery", methods=["POST"])
def update_knowledge_mastery_api():
    """更新某个知识点掌握度"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    concept = s.normalize_concept_name(data.get('concept'))
    mastery = data.get('mastery', None)

    if not concept or mastery is None:
        return error_response(request_id, 400, "INVALID_INPUT", "concept 和 mastery 不能为空")

    if concept == "??":
        return error_response(request_id, 400, "INVALID_INPUT", "concept 编码异常，请使用页面操作或 UTF-8 请求")

    mastery = max(0.0, min(1.0, float(mastery)))

    user_knowledge = s.get_user_knowledge(user_id)
    user_knowledge = s.normalize_user_knowledge(user_knowledge)
    concept_list = user_knowledge.get("concepts", [])
    deleted_concepts = user_knowledge.get("deleted_concepts", [])

    matched = False
    for item in concept_list:
        if item.get("concept") == concept:
            item["mastery"] = mastery
            item["review_count"] = int(item.get("review_count", 0)) + 1
            item["last_reviewed"] = datetime.now().isoformat()
            matched = True
            break

    if not matched:
        concept_list.append({
            "concept": concept,
            "first_seen": datetime.now().isoformat(),
            "mastery": mastery,
            "review_count": 1,
            "last_reviewed": datetime.now().isoformat()
        })

    user_knowledge["concepts"] = concept_list
    user_knowledge["deleted_concepts"] = [c for c in deleted_concepts if c != concept]
    s.set_user_knowledge(user_id, user_knowledge)

    # 同步到 Neo4j（可选）
    review_count = 1
    last_reviewed = datetime.now().isoformat()
    for item in concept_list:
        if item.get("concept") == concept:
            review_count = int(item.get("review_count", 1))
            last_reviewed = item.get("last_reviewed") or last_reviewed
            break
    graph_sync = s.sync_mastery_update(
        user_id=user_id,
        concept=concept,
        mastery=mastery,
        review_count=review_count,
        last_reviewed=last_reviewed,
    )

    return jsonify(success_payload(
        request_id,
        message="掌握度更新成功",
        concept=concept,
        mastery=mastery,
        graph_sync=graph_sync,
        neo4j_synced=bool(graph_sync.get("synced", False)) if s.neo4j_store.ensure_connected() else False,
        error_code="",
        error_message="",
    ))


@knowledge_graph_bp.route("/node", methods=["DELETE"])
def delete_knowledge_node_api():
    """删除某个知识点节点（同时移除关联关系）。"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    concept = s.normalize_concept_name(data.get('concept'))

    if not concept:
        return error_response(request_id, 400, "INVALID_INPUT", "concept 不能为空")

    user_knowledge = s.normalize_user_knowledge(s.get_user_knowledge(user_id))
    concept_list = user_knowledge.get("concepts", [])
    relation_list = user_knowledge.get("relations", [])
    deleted_concepts = user_knowledge.get("deleted_concepts", [])

    before_concepts = len(concept_list)
    before_relations = len(relation_list)

    concept_list = [item for item in concept_list if item.get("concept") != concept]
    relation_list = [
        rel for rel in relation_list
        if rel.get("source") != concept and rel.get("target") != concept
    ]

    if concept not in deleted_concepts:
        deleted_concepts.append(concept)

    user_knowledge["concepts"] = concept_list
    user_knowledge["relations"] = relation_list
    user_knowledge["deleted_concepts"] = deleted_concepts
    s.set_user_knowledge(user_id, user_knowledge)

    graph_sync = s.sync_delete_concept(user_id=user_id, concept=concept)

    return jsonify(success_payload(
        request_id,
        message="节点删除成功",
        concept=concept,
        removed_concepts=before_concepts - len(concept_list),
        removed_relations=before_relations - len(relation_list),
        graph_sync=graph_sync,
        neo4j_synced=bool(graph_sync.get("synced", False)) if s.neo4j_store.ensure_connected() else False,
        error_code="",
        error_message="",
    ))


@knowledge_graph_bp.route("/path", methods=["GET"])
def get_learning_path_api():
    """获取从已掌握知识到目标知识点的学习路径"""
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    target = request.args.get('target', '').strip()

    if not target:
        return error_response(request_id, 400, "INVALID_INPUT", "target 参数不能为空")

    if GRAPH_PRIMARY in {"auto", "neo4j"} and getattr(s.neo4j_store, "enabled", False) and s.neo4j_store.ensure_connected():
        exists_in_neo4j = s.neo4j_store.concept_exists(target)
        if not exists_in_neo4j and GRAPH_PRIMARY == "neo4j":
            return error_response(
                request_id,
                404,
                "TARGET_NOT_FOUND",
                f"目标知识点不存在: {target}",
                path=[],
                storage="neo4j",
            )

        neo4j_path = s.neo4j_store.fetch_learning_path(user_id=user_id, target=target, max_depth=8)
        if neo4j_path:
            return jsonify(success_payload(
                request_id,
                user_id=user_id,
                target=target,
                path=neo4j_path,
                length=len(neo4j_path),
                storage="neo4j",
                error_code="",
                error_message="",
            ))

    kg = s.build_knowledge_graph()
    s.sync_user_mastery_to_graph(kg, user_id)

    if target not in kg.graph.nodes:
        return error_response(
            request_id,
            404,
            "TARGET_NOT_FOUND",
            f"目标知识点不存在: {target}",
            path=[],
            storage="json",
        )

    path = kg.get_learning_path(user_id, target)
    path_source = "json"
    if not path:
        fallback_path = s.infer_learning_path_with_fallback(user_id, target)
        if fallback_path:
            path = fallback_path
            path_source = "json_fallback"

    return jsonify(success_payload(
        request_id,
        user_id=user_id,
        target=target,
        path=path,
        length=len(path),
        storage="json",
        path_source=path_source,
        error_code="",
        error_message="",
    ))


@knowledge_graph_bp.route("/extract", methods=["POST"])
def extract_knowledge_from_text_api():
    """从文本抽取知识点并写入用户知识图谱。"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    text = (data.get('text') or '').strip()
    source = (data.get('source') or 'manual').strip()

    if not text:
        return error_response(request_id, 400, "INVALID_INPUT", "text 不能为空")

    extract_result = s.extract_knowledge_from_text_api_inner(user_id, text, source)
    detected_concepts = extract_result.get("detected_concepts", [])
    relations = extract_result.get("relations", [])
    new_count = extract_result.get("new_concept_count", 0)
    graph_sync = extract_result.get("graph_sync", {})
    extraction_method = extract_result.get("extraction_method", "rule")
    ai_extract = extract_result.get("ai_extract", {})
    mapping_results = extract_result.get("mapping_results", [])
    top_mapping = extract_result.get("top_mapping", {})

    return jsonify(success_payload(
        request_id,
        message="知识抽取成功",
        user_id=user_id,
        source=source,
        detected_concepts=detected_concepts,
        new_concept_count=new_count,
        relations=relations,
        extraction_method=extraction_method,
        ai_extract=ai_extract,
        mapping_results=mapping_results,
        top_mapping=top_mapping,
        graph_sync=graph_sync,
        error_code="",
        error_message="",
    ))


@knowledge_graph_bp.route("/map", methods=["POST"])
def map_learning_behaviors_api():
    """将题目、视频文本、学生笔记等学习行为映射到知识点。"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    items = s.collect_learning_behavior_items(data)
    if not items:
        return error_response(
            request_id,
            400,
            "INVALID_INPUT",
            "items 或 question_texts/video_texts/note_texts 不能为空",
        )

    runtime = s.build_concept_mapping_runtime(user_id)
    mapping_results = map_learning_items(
        items,
        runtime.get("profiles", []),
        stopwords=runtime.get("stopwords", set()),
    )

    return jsonify(success_payload(
        request_id,
        message="学习行为知识点映射成功",
        user_id=user_id,
        total_count=len(mapping_results),
        concept_library_size=runtime.get("concept_library_size", 0),
        method={
            **CONCEPT_MAPPING_METHOD_INFO,
            "thresholds": CONCEPT_MAPPING_THRESHOLDS,
        },
        mapping_results=mapping_results,
        error_code="",
        error_message="",
    ))
