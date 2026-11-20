import argparse
import json
import os
from datetime import datetime

import requests


def load_cases(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Run online/offline evaluation for agent OCR tutor.")
    parser.add_argument("--base", default=os.getenv("EVAL_BASE", "http://127.0.0.1:5000"), help="Backend base url")
    parser.add_argument(
        "--cases",
        default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "agent_eval_samples.json"),
        help="Path to eval cases json",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "agent_eval_report.json"),
        help="Output report path",
    )
    parser.add_argument(
        "--require-ai",
        action="store_true",
        help="AI 未启用时直接失败，避免把离线兜底分当成模型能力分写进报告",
    )
    args = parser.parse_args()

    cases = load_cases(args.cases)
    url = args.base.rstrip("/") + "/api/agent/eval"

    headers = {}
    eval_token = str(os.getenv("AGENT_EVAL_TOKEN", "")).strip()
    if eval_token:
        headers["X-Eval-Token"] = eval_token

    response = requests.post(url, json={"cases": cases}, headers=headers, timeout=120)
    response.raise_for_status()
    report = response.json()
    meta = report.get("meta") or {}

    if args.require_ai and str(meta.get("agent_mode")) != "llm":
        print("ERROR: 当前环境未启用真实大模型，评测结果不能用于效果对比，已放弃写入报告。")
        for note in meta.get("notes") or []:
            print(f"  - {note}")
        print("请先配置 QWEN_API_KEY（或 DEEPSEEK_API_KEY）并设置 USE_REAL_AI=true 后重试。")
        raise SystemExit(2)

    for note in meta.get("notes") or []:
        print(f"WARN: {note}")

    report["generated_at"] = datetime.now().isoformat()
    report["endpoint"] = url

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    summary = report.get("summary", {})
    print("Agent eval done")
    print(
        "env: agent_mode={} provider={} model={} kb_mode={}".format(
            meta.get("agent_mode", "unknown"),
            meta.get("provider", "unknown"),
            meta.get("model", "unknown"),
            meta.get("kb_mode", "unknown"),
        )
    )
    print(f"cases={summary.get('cases', 0)} avg_score={summary.get('avg_score', 0)}")
    print(f"report={args.out}")


if __name__ == "__main__":
    main()
