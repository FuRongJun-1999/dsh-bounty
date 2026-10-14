ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
R=docs/reviews/LangGraph_v0.1.md
echo "---- 七个二级标题机械核对 ----"
for h in "## 0. 结论摘要" "## 1. 被测对象与版本" "## 2. 复现步骤" "## 3. 基线 vs 方案对照读数" "## 4. 读数明细" "## 5. 不适用条件" "## 6. 未测项与原因"; do
  n=$(grep -c -F -- "$h" "$R")
  echo "count=$n  $h"
done
echo "---- 围栏代码块数量（须为偶数） ----"
grep -c '^```' "$R"
echo "---- 违禁措辞扫描（应为空） ----"
grep -n -E '看起来更好|体验更佳|更优雅|更强大' "$R" || echo "(empty: 无违禁措辞)"
echo "---- 交付文件 ----"
ls -l bench/cross_eval/systems/langgraph_impl.py docs/reviews/LangGraph_v0.1.md
ls -l bench/cross_eval/raw/ | grep langgraph
echo "---- 写域外文件是否被碰过（git 状态） ----"
git status --porcelain 2>/dev/null | head -30 || echo "(no git)"
