"""运维观测端点。

只做一件事：把进程内已有的指标翻译成 Prometheus 文本格式，
便于接入华为云 AOM / 自建 Prometheus，不引入 prometheus_client 依赖。
"""

from flask import Blueprint, Response

from ..services import rate_limit
from ..services.agent_metrics import agent_metrics

observability_bp = Blueprint("observability", __name__)

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _counter(name, help_text, value):
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} counter",
        f"{name} {value}",
    ]


def _gauge(name, help_text, value):
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} gauge",
        f"{name} {value}",
    ]


def _labeled_block(metric_type, name, help_text, samples):
    """同一个指标名只声明一次 HELP/TYPE，各标签各占一行。"""
    if not samples:
        return []
    body = [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} {metric_type}",
    ]
    for label_value, value in samples:
        body.append(f'{name}{{bucket="{label_value}"}} {value}')
    return body


def render_prometheus_text():
    snap = agent_metrics.snapshot()
    lines = []

    lines += _counter("fzg_agent_requests_total", "智能体请求总数", snap.get("requests", 0))
    lines += _counter("fzg_agent_success_total", "智能体请求成功数", snap.get("success", 0))
    lines += _counter("fzg_agent_failures_total", "智能体请求失败数", snap.get("fail", 0))
    lines += _counter("fzg_agent_timeouts_total", "智能体请求超时数", snap.get("timeouts", 0))
    lines += _counter("fzg_agent_retries_total", "智能体重试次数", snap.get("retries", 0))
    lines += _counter("fzg_agent_tool_calls_total", "工具调用总数", snap.get("tool_calls", 0))
    lines += _counter("fzg_agent_tool_failures_total", "工具调用失败数", snap.get("tool_fail", 0))

    lines += _gauge("fzg_agent_success_rate", "智能体请求成功率（0-1）", snap.get("success_rate", 0))
    lines += _gauge("fzg_agent_tool_fail_rate", "工具调用失败率（0-1）", snap.get("tool_fail_rate", 0))
    lines += _gauge("fzg_agent_latency_avg_ms", "智能体平均时延（毫秒）", snap.get("avg_latency_ms", 0))
    lines += _gauge("fzg_agent_uptime_seconds", "进程运行时长（秒）", snap.get("uptime_seconds", 0))
    lines += _gauge(
        "fzg_rate_limit_enabled",
        "接口限流是否启用（1=启用）",
        1 if rate_limit.is_enabled() else 0,
    )

    stats = rate_limit.metrics_snapshot()
    if stats:
        items = sorted(stats.items())
        lines += _labeled_block(
            "counter",
            "fzg_rate_limit_allowed_total",
            "按限流桶统计的放行请求数",
            [(bucket, item.get("allowed", 0)) for bucket, item in items],
        )
        lines += _labeled_block(
            "counter",
            "fzg_rate_limit_rejected_total",
            "按限流桶统计的拒绝请求数",
            [(bucket, item.get("rejected", 0)) for bucket, item in items],
        )
        lines += _labeled_block(
            "gauge",
            "fzg_rate_limit_tracked_keys",
            "按限流桶统计的客户端跟踪数",
            [(bucket, item.get("tracked_keys", 0)) for bucket, item in items],
        )

    return "\n".join(lines) + "\n"


@observability_bp.route('/metrics', methods=['GET'])
def prometheus_metrics():
    # 用 content_type 而非 mimetype，避免 Flask 再追加一次 charset
    return Response(render_prometheus_text(), content_type=CONTENT_TYPE)
