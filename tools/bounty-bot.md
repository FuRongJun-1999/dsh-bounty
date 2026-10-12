# 悬赏机器人 · bounty-bot

灵枢悬赏站（[FuRongJun-1999/dsh-bounty](https://github.com/FuRongJun-1999/dsh-bounty)）的群机器人。
OneBot v11 HTTP 接入（NapCat 反向调用），**纯 Python 标准库，零第三方依赖**。

> 本目录**只含脚本代码**。HTML 模板与出图由使用者侧负责，见「渲染契约」。
> 静态素材（字体 / 纹理 / 徽记）不入库——见 `.gitignore`。

---

## 指令（全部所有人可用）

| 指令 | 输出 | 说明 |
|---|---|---|
| `/帮助` | 图片 | 使用说明 |
| `/悬赏` | 图片 | 当前悬赏；无悬赏时出图写「暂时没有悬赏哦」 |
| `/绑定 <GitHub 用户名>` | 文本 | 校验后绑定，直接回「绑定成功」 |
| `/我的贡献` | 图片 | 累计声誉分 + 悬赏热力图 |
| `/榜单` | 图片 | 声誉榜 |
| `/更新` | 文本 | 立刻检查最新结算表与悬赏 |

### 绑定规则

* **校验 GitHub 用户名真实存在**（调 `api.github.com/users/{name}`），不存在直接拒绝；
* **一 QQ 一 GitHub**：同一 QQ 重复绑定 => **覆盖**旧值（回执注明「已由 X 更新为 Y」）；
* **一 GitHub 一 QQ**：该 GitHub 已绑他人 => **拒绝**；并发下由唯一索引兜底（`BindConflict`）；
* 大小写不敏感（`octocat` 与 `OCTOCAT` 视为同一账号）。

---

## 数据源

| 数据 | 来源 | 频率 |
|---|---|---|
| 贡献结算表 | `docs/bounty/贡献表.md`（账本机械生成） | 每天更新 |
| 悬赏 | **本仓 issue：标题以「悬赏」开头** | 随 issue 变动 |

取数链（一号机实测）：`api.github.com` -> `ghproxy.net` -> `cdn.jsdelivr.net`。
`raw.githubusercontent.com` 在一号机不可达（IPv6 无路由），故不直连。

未配 GitHub Token 时限 **60 次/小时**；靠 `ETag`/`sha` 条件请求（304 不计费）+ 本地缓存兜住。
建议配一个只读 Token（提到 5000 次/小时）：填 `config.json` 的 `github_token`。

### 悬赏发布路径（本仓既定口径）

**悬赏 = 本仓 issue，标题以「悬赏」字样开头。** 机器人按此判据扫描，无需任何额外文件。

```
悬赏 灵枢生态宣传：材料 + 渠道 + 触达读数
[悬赏] 角色扮演游戏制作：可运行 + 可测
悬赏：插件测评站
```

入选判据（见 `sync.py::is_bounty_title`）：

* 标题（去首尾空白后）以 `悬赏` 或 `[悬赏]` 开头，后接空白 / 冒号（半角全角）/ 破折号 / 顿号皆可；
* **只要 `state=open`** 的 issue（`config.bounty.include_closed=true` 可纳入已关闭的）；
* **PR 不算**（`pull_request` 字段存在即剔除）；
* 前缀会被剥掉，卡片上显示干净的标题。

字段映射（见 `sync.py::issue_to_bounty`）：

| 卡片字段 | 取自 |
|---|---|
| 标题 | issue 标题（去「悬赏」前缀） |
| 难度 | 标签 `difficulty:{easy\|medium\|hard\|expert}`（决定排序与徽记） |
| 状态 | 标签 `bounty:{open\|claimed\|delivered\|verified\|settled\|disputed}`，无则按 issue 开闭 |
| 编号 | issue 号（卡片上显示 `issue #NN`，点卡片直达认领页） |
| 摘要 | 正文首个非空、非标题行（截断 120 字） |
| 截止 | milestone 的 `due_on` |

相关配置：

```jsonc
"bounty": {
  "mode": "issues",       // 悬赏来源：标题带「悬赏」的 issue
  "enabled": true,
  "labels": "",           // 可选：再限定标签，如 "bounty"
  "include_closed": false,
  "per_page": 100,        // 页过大时自动减半重试（api.github.com 会偶发半截响应）
  "max_pages": 3
}
```

---

## 热力图口径（重要）

**热力图 = 悬赏热力图，不是 GitHub 提交热力图。**

* 每个格子 = **当天获得的声誉分**；
* 声誉分来自「贡献结算表」的**累计（全部结算日）**表；
* 实现：**每日快照 + 相邻两版求差**。`contrib_snapshot` 每天一版全量快照
  （append-only，**永不删除**），当日增量 = 今日总分 − 上一版总分；
* 首版快照无前序，记 0 并在 payload 里给 `baseline` 供前端标注「初始快照」；
* 表里每日小节的 Δ 列（该次交付的当次增量）与累计表**必然自洽**，
  `settle.cross_check()` 会核对；不一致只告警、不阻断（保留旧数据）。

---

## 渲染契约（由使用者侧实现）

机器人只负责**调度与契约**，不含 HTML/CSS/视觉。

在 `config.json` 配 `render.cmd`，占位符 `{payload}` / `{out}` 会被替换为真实路径：

```jsonc
"render": {
  "cmd": ["node", "/opt/bounty-bot/render/render.js", "{payload}", "{out}"],
  "cwd": "/opt/bounty-bot/render",
  "timeout": 90
}
```

渲染器只需：读 `payload.json` -> 出图 -> 写到 `{out}` 路径。
**退出码 0 且 PNG 存在且非空** => 成功。

> `render/render.js` 是随附的参考实现（无头 Chrome 截图）：先 `--dump-dom` 量出
> `data-full-height`，再按该高度截图；中间 HTML 落系统临时目录并在 `finally` 里删除。
> 可用 `BOUNTY_CHROME` 指定浏览器路径。
>
> ⚠️ 页面**不得依赖联网资源**（如远端头像）：实测某次头像域名不可达会让整页等连接超时，
> `/我的贡献` 直接渲染失败。参考实现里头像已改为本地绘制。

### payload 结构

```jsonc
{
  "kind": "help" | "bounty" | "contribution" | "rank",
  "_generated_at": "2026-10-12 20:47:49",
  // kind=help
  "commands": [{ "cmd": "/帮助", "desc": "..." }],
  // kind=bounty
  "bounties": [{ "no","title","difficulty","reward","status","deadline","url","note" }],
  "empty": false,
  "empty_text": "暂时没有悬赏哦",
  "synced_at": "...",
  // kind=contribution
  "github": "octocat", "bound_at": "...",
  "total": 22, "rank": 1, "people": 9, "on_board": true,
  "issues": [{ "issue_no","project","difficulty","base","impact","evidence" }],
  "heatmap": {
    "start": "2025-10-13", "end": "2026-10-12",
    "days": [{ "date": "2026-10-11", "value": 6, "has": true }],
    "max": 6, "total": 6,
    "baseline": { "date": "2026-10-10", "total": 16 },
    "has_history": true
  },
  "synced_at": "..."
}
```

`render_stub.py` 是一个最小占位实现，仅供联调脚本逻辑用，**不是**正式渲染器。

---

## 纪律与兜底

* **渲染失败 => 回「Chrome 崩了，请联系管理员。」**（超时 / 崩溃 / 产物缺失都算）；
* **图片发出成功后**才删临时文件；发送失败则保留，交 `sweep_tmp` 兜底
  （早期版本在 `finally` 里无条件删，发送失败时会把现场证据也删掉）；
* **贡献历史快照永不删除**；
* 渲染**全局串行**（避免并发多开浏览器压垮内存）；
* 残留临时文件超过 6 小时自动清理（`sweep_tmp`）；
* 定时同步线程里 `sweep_tmp` 单独 try —— 清理失败不能把同步循环打死。

---

## 定时同步

进程内后台线程，**每 2.5 小时**（9000 秒）一次，启动 20 秒后先跑一次。
刻意错开整点，避开电力采样与 keypool 更新。

「有无更新」用内容指纹判（结算表用 `sha/ETag`，悬赏用全部悬赏 issue 的
`(号, updated_at, state, labels)` 拼串）；指纹没变就整轮跳过，不写库。

---

## 文件

| 文件 | 作用 |
|---|---|
| `bot.py` | 主程序：OneBot HTTP 服务 + 指令路由 |
| `db.py` | 数据层：绑定 / 贡献 / 快照 / 热力图 / 悬赏（含老库自动补列） |
| `github.py` | GitHub 取数（三级回落 + ETag + 传输重试） |
| `settle.py` | 结算表 Markdown 解析（新落点 `docs/bounty/贡献表.md`） |
| `sync.py` | 同步引擎 + 悬赏判定（标题前缀「悬赏」的 issue） |
| `render.py` | 渲染调度（契约 + 串行锁 + 清理） |
| `onebot.py` | OneBot v11 客户端（发文本/图片） |
| `render/render.js` | 参考渲染器（无头 Chrome） |
| `selftest.py` | 离线自检（50+ 项，全 PASS） |
| `config.json` | 配置（**含 NapCat token，别提交**，`chmod 600`） |

## 自检

```bash
python3 selftest.py                       # 离线：绑定 / 解析 / 快照 / 热力图 / 悬赏判定 / 指令
python3 selftest.py --table <贡献表.md>    # 用真实结算表跑结构断言
python3 selftest.py --live                # 额外做一次真·GitHub 拉取
```

## 运行

```bash
python3 bot.py                  # 前台；生产用 systemd
curl -s localhost:3040/health   # 健康检查
```

systemd 单元见 `bounty-bot.service`（`Restart=always` + `MemoryMax=400M`）。
