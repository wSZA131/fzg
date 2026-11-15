#!/usr/bin/env bash
# 上线冒烟检查：健康状态 + 静态页面 + 知识库检索 + 图谱状态
set -uo pipefail

BASE_URL="${1:-http://127.0.0.1}"
PASS=0
FAIL=0

check() {
  local name="$1" url="$2"
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url")"
  if [[ "$code" == "200" ]]; then
    printf '[ ok ] %-22s %s\n' "$name" "$code"
    PASS=$((PASS + 1))
  else
    printf '[fail] %-22s %s (%s)\n' "$name" "$code" "$url"
    FAIL=$((FAIL + 1))
  fi
}

echo "== 服务健康 =="
curl -fsS --max-time 20 "${BASE_URL}/health" | python3 -m json.tool 2>/dev/null || curl -sS "${BASE_URL}/health"

echo
echo "== 页面可访问性 =="
check "首页"            "${BASE_URL}/index.html"
check "智能问答"        "${BASE_URL}/chat.html"
check "学习仪表盘"      "${BASE_URL}/dashboard.html"
check "知识图谱"        "${BASE_URL}/knowledge-map.html"
check "题库练习"        "${BASE_URL}/question-bank.html"
check "学习空间"        "${BASE_URL}/spaces.html"

echo
echo "== 知识库检索 =="
kb_resp="$(curl -sS --max-time 30 -X POST "${BASE_URL}/api/agent/kb/search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"导数的定义","top_k":3}')"
if printf '%s' "$kb_resp" | grep -q '"success": *true'; then
  echo "[ ok ] /api/agent/kb/search"
  PASS=$((PASS + 1))
else
  echo "[warn] /api/agent/kb/search 返回异常："
  printf '%s\n' "$kb_resp" | head -c 600
  FAIL=$((FAIL + 1))
fi

echo
echo "== 视觉模型/OCR 状态（见上方 health 字段 ocr_provider）=="

echo
echo "通过 ${PASS} 项，失败 ${FAIL} 项"
[[ "$FAIL" -eq 0 ]]
