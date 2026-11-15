"""学习计划蓝图：计划的增删改查与清空。

计划相关的存储与辅助函数（get_user_plans / add_user_plan 等）保留在 server
模块中，本模块通过 ``_server()`` 延迟获取，保持与测试 patch 的兼容。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..utils.http import error_response, get_request_id, success_payload

plans_bp = Blueprint("plans", __name__, url_prefix="/api/plans")


def _server():
    """延迟获取 server 模块，保持共享函数与测试 patch 的兼容。"""
    from .. import server
    return server


@plans_bp.route("", methods=["GET"])
def get_plans():
    """获取用户学习计划"""
    s = _server()
    request_id = get_request_id()
    user_id, auth_error = s.resolve_request_user_id_from_args()
    if auth_error:
        return auth_error
    plans = s.get_user_plans(user_id)

    return jsonify(success_payload(
        request_id,
        plans=plans,
        count=len(plans),
        error_code="",
        error_message="",
    ))


@plans_bp.route("", methods=["POST"])
def add_plan():
    """添加新学习计划"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error
    time = data.get('time')
    task = data.get('task')

    if not time or not task:
        return error_response(request_id, 400, "INVALID_INPUT", "时间和任务内容不能为空")

    new_plan = s.add_user_plan(user_id, time, task)

    return jsonify(success_payload(
        request_id,
        message="学习计划添加成功",
        plan=new_plan,
        error_code="",
        error_message="",
    ))


@plans_bp.route("/<plan_id>", methods=["PUT"])
def update_plan(plan_id):
    """更新学习计划（如打勾完成）"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    # 允许更新的字段
    updates = {}
    if 'completed' in data:
        updates['completed'] = data['completed']
    if 'time' in data:
        updates['time'] = data['time']
    if 'task' in data:
        updates['task'] = data['task']

    if not updates:
        return error_response(request_id, 400, "INVALID_INPUT", "没有要更新的内容")

    success = s.update_user_plan(user_id, plan_id, updates)

    if success:
        return jsonify(success_payload(
            request_id,
            message="学习计划更新成功",
            error_code="",
            error_message="",
        ))
    else:
        return error_response(request_id, 404, "PLAN_NOT_FOUND", "计划不存在或更新失败")


@plans_bp.route("/<plan_id>", methods=["DELETE"])
def delete_plan(plan_id):
    """删除学习计划"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    success = s.delete_user_plan(user_id, plan_id)

    if success:
        return jsonify(success_payload(
            request_id,
            message="学习计划删除成功",
            error_code="",
            error_message="",
        ))
    else:
        return error_response(request_id, 404, "PLAN_NOT_FOUND", "计划不存在或删除失败")


@plans_bp.route("/clear", methods=["POST"])
def clear_completed_plans():
    """清空已完成的学习计划"""
    s = _server()
    request_id = get_request_id()
    data = request.json or {}
    user_id, auth_error = s.resolve_request_user_id_from_json(data)
    if auth_error:
        return auth_error

    plans = s.get_user_plans(user_id)

    # 保留未完成的任务
    incomplete_plans = [p for p in plans if not p.get('completed', False)]
    s.set_user_plans(user_id, incomplete_plans)

    return jsonify(success_payload(
        request_id,
        message="已完成计划已清空",
        remaining_count=len(incomplete_plans),
        error_code="",
        error_message="",
    ))
