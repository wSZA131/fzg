#!/usr/bin/env python3
"""公共知识库制品自检。

解决的问题：pro_kb 的大文件走 Git LFS 管理。克隆仓库时若未执行 git lfs pull，
这些文件只是 129 字节左右的文本指针，程序仍能启动，但检索会静默降级成
内置的 6 条演示数据——评测指标随之失真，而界面上看不出区别。

本脚本只做文件层面检查，不导入应用模块，可在任意 Python 环境下直接运行：

    python backend/scripts/verify_kb_artifacts.py
"""

import argparse
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_KB_DIR = os.path.join(BACKEND_DIR, "data", "pro_kb")

LFS_POINTER_SIGNATURE = b"version https://git-lfs"
LFS_POINTER_MAX_BYTES = 512

# 缺失或为指针时，公共向量检索不可用（会退化为演示数据）。
CRITICAL_FILES = (
    ("pro_kb_faiss.index", 1024 * 1024),
    ("pro_kb_texts.json", 1024 * 1024),
    ("pro_kb_chunks.jsonl", 1024 * 1024),
)

# 缺失时功能降级但服务仍可用（例如回退到 TF-IDF）。
SUPPORTING_FILES = (
    ("pro_kb_tfidf_vectorizer.pkl", 10 * 1024),
    ("pro_kb_faiss_meta.json", 64),
    ("pro_kb_graph.json", 1024),
    ("pro_kb_cards.jsonl", 1024),
    ("pro_kb_summary.json", 64),
    ("pro_kb_tfidf_matrix.npz", 1024),
)


def human_size(num_bytes):
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def inspect(path, min_expected_bytes):
    """返回 (状态, 说明)。状态取值：ok / lfs_pointer / too_small / missing。"""
    if not os.path.isfile(path):
        return "missing", "文件不存在"

    size = os.path.getsize(path)
    try:
        with open(path, "rb") as handle:
            head = handle.read(LFS_POINTER_MAX_BYTES)
    except OSError as exc:
        return "missing", f"无法读取：{exc}"

    if head.startswith(LFS_POINTER_SIGNATURE):
        return "lfs_pointer", f"{human_size(size)}（Git LFS 指针，内容未拉取）"
    if size < min_expected_bytes:
        return "too_small", f"{human_size(size)}（小于预期 {human_size(min_expected_bytes)}）"
    return "ok", human_size(size)


def main():
    parser = argparse.ArgumentParser(description="检查 pro_kb 知识库制品是否可用")
    parser.add_argument("--kb-dir", default=DEFAULT_KB_DIR, help="制品目录，默认 backend/data/pro_kb")
    parser.add_argument(
        "--strict-supporting",
        action="store_true",
        help="把支撑文件（图谱、TF-IDF 等）的问题也计入失败退出码",
    )
    args = parser.parse_args()

    kb_dir = os.path.abspath(args.kb_dir)
    print(f"制品目录: {kb_dir}\n")

    if not os.path.isdir(kb_dir):
        print("ERROR: 目录不存在。请确认仓库已完整克隆。")
        return 1

    critical_bad = []
    supporting_bad = []

    def report(title, entries, bucket):
        print(title)
        print(f"  {'文件':<32}{'状态':<14}大小 / 说明")
        for name, min_bytes in entries:
            status, detail = inspect(os.path.join(kb_dir, name), min_bytes)
            label = {
                "ok": "可用",
                "lfs_pointer": "LFS 指针",
                "too_small": "疑似不完整",
                "missing": "缺失",
            }.get(status, status)
            mark = "  " if status == "ok" else "! "
            print(f"{mark}{name:<32}{label:<14}{detail}")
            if status != "ok":
                bucket.append((name, status))
        print()

    report("关键制品（缺失则公共向量检索不可用）", CRITICAL_FILES, critical_bad)
    report("支撑制品（缺失时功能降级）", SUPPORTING_FILES, supporting_bad)

    lfs_files = [n for n, s in critical_bad + supporting_bad if s == "lfs_pointer"]
    missing_files = [n for n, s in critical_bad + supporting_bad if s == "missing"]

    if not critical_bad and not supporting_bad:
        print("结论: 全部制品可用，知识库运行在完整数据上。")
        return 0

    if lfs_files:
        print(f"结论: {len(lfs_files)} 个文件仍是 Git LFS 指针，未拉取真实内容。")
        print("影响: 服务仍能启动，但公共检索会静默降级为内置演示数据（约 6 条切片），")
        print("      检索命中率与图谱指标都不再代表真实效果。")
        print("修复:")
        print("  git lfs install && git lfs pull")
        print("  未安装 git-lfs 时：")
        print("    Ubuntu/Debian: sudo apt install git-lfs")
        print("    macOS:         brew install git-lfs")
        print("  若仓库托管方不提供 LFS，请从发布附件或构建脚本重新生成制品：")
        print("    python backend/scripts/build_professional_vector_kb.py")
    elif missing_files:
        print(f"结论: {len(missing_files)} 个文件缺失。")
        print("修复: 重新生成制品 python backend/scripts/build_professional_vector_kb.py")

    if critical_bad:
        return 1
    return 1 if args.strict_supporting else 0


if __name__ == "__main__":
    sys.exit(main())
