# Bounty Fix

**Reward:** —
**Issue:** https://github.com/FuRongJun-1999/dsh-bounty/issues/71
**Repo:** https://github.com/FuRongJun-1999/dsh-bounty

---

## Issue

[悬赏] 灵枢生态宣传：材料 + 渠道 + 触达读数（可核验，不写「效果好」）

## 背景
生态需要对外传播。但「宣传效果」本身不可机械复核——所以本悬赏**把宣传转成可核验的交付物**：
材料（存在性）＋ 渠道（链接可达）＋ 触达读数（可查数字）。**不写不可核验的「效果好」**。

## 验收标准（必填 · 可机械复核）
1. **交付物**：`docs/promo/<主题>_v0.1.md`——含 ① 文案 ② 目标受众 ③ 渠道清单 ④ 发布记录（链接 ＋ 日期）⑤ 触达读数
2. **复跑命令**：
   ```bash
   python -X utf8 scripts/check_links.py docs/promo/   # 期望退出码 0（逐条链接可达）
   ```
3. **期望读数**：
   - **≥3 个渠道**的**实际发布链接**（不是「计划发布」）＋ 每条的触达读数（星标 / 浏览 / 转发 / 评论数，须可查）
   - 读数须附**来源**（链接或截图路径）；**无读数的渠道写「未取到读数 ＋ 原因」**
   - 每条文案与目标受众对应；受众不明确的文案**不算交付**
4. **反面对照**：链接校验脚本须带守卫（≥3 条断言 ＋ 定点变异自证）；人为改坏一个链接 ⇒ 断言必红并点名。
5. **合规**：文案过内容政策自检（无夸大、无未证实的数据、无侵权素材）；引用数据须附来源 URL。

## 难度
medium（3 分）——单点面，但要求「可核验」而非「看起来很努力」。

## 期望交付形态
两者皆可（材料走 PR；触达读数可贴评论证据块）

## 参考材料
- 本仓对外口径（**先读**）：`README.md`、`docs/bounty/README.md` §〇（价值论证——只给可核验事实的体例）
- 悬赏站设计稿：`docs/spec/悬赏站设计_v1.0.md`

## 边界与不做项
- **不做**刷量 / 买流量 / 机器人转发（读数须真实可查）
- **不碰**未公开的内部方案与私有运行时细节（对外只讲公开面）
- **不承诺**未实现的能力（已实现与规划中须分开写）
- 不在未经许可的社区 / 频道投放

---

## Process

### 1. Orient yourself first
Before touching any code:
- Read the README and any relevant docs
- Run: find . -type f | grep -v node_modules | grep -v .git | grep -v dist | head -60
- Grep for the key terms from the issue title to find the relevant files
- Read the files around the bug — understand what's currently happening

### 2. Find and read the tests
- Look for test files near the relevant code (*.test.ts, *.spec.js, __tests__, etc.)
- Read them — they tell you what behavior is expected
- Understand what a passing fix looks like before writing a line

### 3. Implement the fix
- Make the MINIMAL change that fixes the issue — nothing more
- Do not refactor, rename, reorganize, or clean up unrelated code
- Do not add dependencies unless the issue explicitly requires it
- Do not modify config files (package.json, tsconfig.json, etc.) unless that IS the fix
- One logical change, one commit

### 4. Verify
- Run the test suite: check package.json scripts for "test", "lint", "typecheck"
  Common commands: npm test, yarn test, pnpm test, pytest, go test ./..., cargo test
- If TypeScript is present: npx tsc --noEmit
- Fix any test failures your change caused — if a test was wrong before, update it

### 5. Commit and document
- git add -A
- git commit -m "fix: [悬赏] 灵枢生态宣传：材料 + 渠道 + 触达读数（可核验，不写「效果好」）"
- Write AGENT_SUMMARY.md with:
  - Root cause: what was wrong and why
  - Fix: what you changed and the reasoning
  - Verification: how to confirm it works
  - Concerns: anything a reviewer should know

---

## Stop conditions

If ANY of these are true, write "UNCERTAIN: [reason]" at the top of AGENT_SUMMARY.md, make NO code changes, and stop:
- The fix requires changing more than ~5 files
- You cannot determine what the correct behavior should be
- The issue requires a database migration, API key, or external service
- You find 3+ open PRs already attempting this fix (high competition)
- The repo is not in a language/framework you can reason about confidently

A clean UNCERTAIN is better than a bad PR.
