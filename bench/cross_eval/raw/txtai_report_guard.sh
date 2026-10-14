#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
F=docs/reviews/txtai-Workflow_v0.1.md
{
echo "### 七个二级标题逐字核对"
for h in "## 0. 结论摘要" "## 1. 被测对象与版本" "## 2. 复现步骤" "## 3. 基线 vs 方案对照读数" "## 4. 读数明细" "## 5. 不适用条件" "## 6. 未测项与原因"; do
  if grep -qxF "$h" "$F"; then echo "OK   $h"; else echo "MISS $h"; fi
done
echo "### 全部二级标题"
grep -n '^## ' "$F"
echo "### 禁用措辞扫描（应无输出）"
grep -nE '看起来更好|体验更佳|更优雅|更强大|显而易见|明显优于' "$F"
echo "### 行数 / 字节"
wc -l -c "$F"
} 2>&1 | tee bench/cross_eval/raw/txtai_report_guard.txt
