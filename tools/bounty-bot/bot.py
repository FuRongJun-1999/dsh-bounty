# -*- coding: utf-8 -*-
"""悬赏机器人 · 主程序（OneBot v11 HTTP，供 NapCat 反向调用）。

指令（全部所有人可用）：
    /帮助            渲染成图片
    /悬赏            渲染成图片（无悬赏时也出图，写「暂时没有悬赏哦」）
    /绑定 <github>   纯文本回「绑定成功」
    /我的贡献        渲染成图片（累计声誉分 + 悬赏热力图）
    /榜单            渲染成图片（声誉榜）
    /更新            纯文本回执

数据源（dsh-bounty 仓）：
    * 结算表  docs/bounty/贡献表.md            （由账本机械生成）
    * 悬赏    本仓 issue——标题以「悬赏」开头   （见 sync.py）

纪律：
  * 渲染失败 => 回「Chrome 崩了，请联系管理员」；
  * 图片发出后即删临时文件（发送失败则保留，交 sweep_tmp 兜底）；
  * 贡献历史快照永不删除。
"""
from __future__ import annotations

import json
import re
import signal
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import db                      # noqa: E402
import github as gh           # noqa: E402
import onebot                 # noqa: E402
import render as render_mod   # noqa: E402
import sync as sync_mod       # noqa: E402

CFG_PATH = ROOT / "config.json"
LOG_PATH = ROOT / "bot.log"

#: GitHub 登录名格式（最长 39，连字符不能在首尾、不能连续）
_VALID_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

CFG = {}
CONN = None
RENDERER = None
API = None
_LOG_LOCK = threading.Lock()


# ---------------------------------------------------------------- 基础设施

def log(*parts):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(str(p) for p in parts))
    with _LOG_LOCK:
        try:
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
    print(line, flush=True)


def load_config(path=CFG_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.setdefault("listen_host", "127.0.0.1")
    cfg.setdefault("listen_port", 3040)
    cfg.setdefault("repo", "FuRongJun-1999/dsh-bounty")
    cfg.setdefault("branch", "main")
    # 新落点：结算表已由 docs/spec/贡献结算表_v0.1.md 迁到 docs/bounty/贡献表.md
    cfg.setdefault("contrib_path", "docs/bounty/贡献表.md")
    cfg.setdefault("github_token", "")
    cfg.setdefault("group_whitelist", [])
    cfg.setdefault("admin_qq", [])
    cfg.setdefault("render", {})
    b = cfg.setdefault("bounty", {})
    # json = 真源 docs/bounty/悬赏.json（默认）；issues = 标题带「悬赏」的 issue；auto = 先 json
    b.setdefault("mode", "json")
    b.setdefault("source_path", "docs/bounty/悬赏.json")
    b.setdefault("enabled", True)
    b.setdefault("labels", "")
    b.setdefault("include_closed", False)
    b.setdefault("per_page", 100)
    b.setdefault("max_pages", 3)
    cfg.setdefault("napcat", {})
    s = cfg.setdefault("sync", {})
    s.setdefault("on_start", True)
    s.setdefault("interval_seconds", 9000)
    return cfg


def in_whitelist(group_id):
    wl = CFG.get("group_whitelist") or []
    return not wl or str(group_id) in {str(x) for x in wl}


# ---------------------------------------------------------------- 指令解析

_CQ_AT = re.compile(r"^\s*\[CQ:at,[^\]]*\]")


#: 指令名（按长度降序匹配，避免 /绑定 被 /榜 之类的前缀抢走）
_KNOWN_CMDS = ("/帮助", "/悬赏", "/绑定", "/我的贡献", "/榜单", "/更新")


def parse_command(message):
    """OneBot message（array 或 string）-> (cmd, args)。

    只认行首第一个词；**指令与参数之间空格可有可无**：
        /绑定 octocat      -> ("/绑定", "octocat")
        /绑定octocat       -> ("/绑定", "octocat")      <- 等价
    非「已知指令 + 可选参数」的形态一律不认（例如 /绑定abc 若 abc 不是合法登录名
    也会先当参数传下去，由绑定逻辑自己报格式错）。
    """
    text = ""
    if isinstance(message, list):
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "text":
                text += (seg.get("data") or {}).get("text", "")
        if not text:      # 纯 @ 无文本 => 不是命令
            return None, ""
    elif isinstance(message, str):
        text = message
    text = text.strip()
    if not text:
        return None, ""
    # 允许前置 @ 提及（可多个，可带前导空白）
    while True:
        m = _CQ_AT.match(text)
        if not m:
            break
        text = text[m.end():].strip()
    if not text.startswith("/"):
        return None, ""

    # ① 先按「已知指令前缀」匹配（支持无空格）：/绑定octocat
    for cmd in sorted(_KNOWN_CMDS, key=len, reverse=True):
        if text == cmd:
            return cmd, ""
        if text.startswith(cmd):
            rest = text[len(cmd):]
            # 前缀后面必须紧跟参数（可无空格）；空白就吃掉
            rest = rest.strip()
            if rest:
                return cmd, rest
    # ② 退回「空格分隔的第一个词」：兼容将来新增的指令
    first, _, rest = text.partition(" ")
    return first.strip(), rest.strip()


# ---------------------------------------------------------------- 指令实现

COMMANDS = [
    {"cmd": "/帮助", "desc": "查看本说明"},
    {"cmd": "/悬赏", "desc": "查看当前悬赏委托（来自本仓 issue）"},
    {"cmd": "/绑定 <GitHub 用户名>", "desc": "绑定你的 GitHub 账号（空格可有可无）"},
    {"cmd": "/我的贡献", "desc": "查看累计声誉分与悬赏热力图"},
    {"cmd": "/榜单", "desc": "声誉总榜；/榜单 日、/榜单 月 看日榜月榜"},
    {"cmd": "/更新", "desc": "立刻检查是否有最新结算表与悬赏"},
]


def cmd_help() -> str:
    """返回图片路径。

    内容固定 => 走缓存：首次渲染后长期复用，不再每次起 Chrome。
    """
    return RENDERER.render_cached("help", {"commands": COMMANDS})


def cmd_bounty() -> str:
    items = db.list_bounties(CONN)
    # 动态卡：payload 变了（悬赏增删/状态变/换负责人）才重渲染，没变就复用上一张
    return RENDERER.render_cached("bounty", {
        "bounties": items,
        "empty": not items,
        "empty_text": "暂时没有悬赏哦",
        "synced_at": db.meta_get(CONN, "bounty_synced_at"),
        "source": db.meta_get(CONN, "bounty_source"),
    })


def cmd_contribution(qq):
    """返回 (状态, 图片路径 或 纯文本兜底说明)。"""
    b = db.get_binding(CONN, qq)
    if not b:
        return "unbound", "你还没有绑定 GitHub 账号。\n发送「/绑定 <你的GitHub用户名>」即可绑定。"
    login = b["github"]
    detail = db.person_detail(CONN, login)
    rank, total_people = db.rank_of(CONN, login)
    heat = db.heatmap(CONN, login)
    payload = {
        "github": login,
        "bound_at": b["bound_at"],
        "total": (detail or {}).get("total", 0),
        "issues": (detail or {}).get("issues", []),
        "rank": rank,
        "people": total_people,
        "on_board": detail is not None,
        "heatmap": heat,
        "synced_at": db.meta_get(CONN, "contrib_synced_at"),
        "contrib_day": db.meta_get(CONN, "contrib_day"),
    }
    return "ok", RENDERER.render_cached("contribution", payload)


def cmd_bind(qq, arg) -> str:
    """绑定（纯文本）。规则：
      * 校验 GitHub 用户名真实存在；
      * 一 QQ 一 GitHub：重复绑定 => 覆盖旧值；
      * 一 GitHub 一 QQ：该 GitHub 已绑别人 => 拒绝。
    """
    name = (arg or "").strip().lstrip("@")
    if not name:
        return "请带上你的 GitHub 用户名，例如：/绑定 octocat"
    if not _VALID_LOGIN.match(name):
        return "这个 GitHub 用户名格式不对哦（只能含字母、数字和单个连字符）。"

    token = CFG.get("github_token") or ""
    canonical = gh.canonical_login(name, token)
    if not canonical:
        return "没找到 GitHub 用户「%s」，请检查拼写后再试。" % name

    exist = db.get_binding_by_github(CONN, canonical)
    if exist and str(exist["qq"]) != str(qq):
        return ("这个 GitHub 账号已经绑定了另一个 QQ（尾号 %s），不能重复绑定。\n"
                "每个人绑自己的 GitHub 账号即可，互不影响。\n"
                "发送「/绑定 <你的GitHub用户名>」（空格可有可无）"
                % str(exist["qq"])[-4:])

    try:
        action, old = db.bind(CONN, qq, canonical)
    except db.BindConflict:
        # 并发下另一个 QQ 刚抢走同一 GitHub：唯一索引兜住
        return "这个 GitHub 账号刚刚被别的 QQ 绑走了，请换一个或联系管理员。"
    if action == "created":
        return "绑定成功！\nGitHub：%s\n发送「/我的贡献」查看你的累计贡献。" % canonical
    if (old or "").lower() == canonical.lower():
        return "绑定成功！\nGitHub：%s（与上次相同）" % canonical
    # 换绑：说清是**你自己**的旧绑定被替换（不是别人的），避免误解
    return ("绑定成功！\nGitHub：%s\n（你之前绑的 %s 已被替换）\n"
            "发送「/我的贡献」查看你的累计贡献。" % (canonical, old))


def cmd_update(qq) -> str:
    """立刻同步（纯文本回执）。"""
    res = sync_mod.sync_all(CONN, CFG, force=True)
    changed = []
    if res.contrib_changed:
        changed.append("结算表有更新")
    if res.bounty_changed:
        changed.append("悬赏有更新")
    tail = ("发现更新 —— " + "、".join(changed)) if changed else "暂无更新"
    return "\n".join(["已检查最新状态：", res.summary(), tail])


def cmd_rank(args="") -> str:
    """声誉榜（渲染成图片）。**不限人数**——有多少人出多少人。

    /榜单            总榜（累计，含历史补录）
    /榜单 日          今日日榜
    /榜单 日 2026-10-11  指定日
    /榜单 月          本月月榜
    /榜单 月 2026-10  指定月
    """
    arg = (args or "").strip()
    kind = "total"
    title = "声誉总榜"
    rows = db.all_totals(CONN)
    scope = "累计（当前贡献表 ＋ 历史补录）"
    if arg:
        parts = arg.split()
        head = parts[0]
        want = parts[1] if len(parts) > 1 else ""
        if head.startswith("日"):
            kind, title = "day", "今日日榜"
            day = want or db.today()
            rows = db.board_by_day(CONN, day)
            scope = "结算日 %s（当天增量）" % day
        elif head.startswith("月"):
            kind, title = "month", "本月月榜"
            ym = want or db.today()[:7]
            rows = db.board_by_month(CONN, ym)
            scope = "%s（当月累计）" % ym
    return RENDERER.render_cached("rank", {
        "ranking": rows, "kind": kind, "title": title, "scope": scope,
        "days": db.snapshot_days(CONN),
        "synced_at": db.meta_get(CONN, "contrib_synced_at")})


# ---------------------------------------------------------------- 消息路由

RENDER_CMDS = {"/帮助": cmd_help, "/悬赏": cmd_bounty, "/榜单": cmd_rank}


def handle_command(cmd, args, qq, group_id):
    """返回 (kind, content)。kind in {text, image}。"""
    if cmd in RENDER_CMDS:
        fn = RENDER_CMDS[cmd]
        # /榜单 支持参数（日/月），其余不带参
        return "image", (fn(args) if cmd == "/榜单" else fn())
    if cmd == "/绑定":
        return "text", cmd_bind(qq, args)
    if cmd == "/我的贡献":
        status, out = cmd_contribution(qq)
        if status == "unbound":
            return "text", out
        return "image", out
    if cmd == "/更新":
        return "text", cmd_update(qq)
    return "text", "未知指令。发送「/帮助」查看可用指令。"


def reply(handler_event, kind, content):
    """发回结果。

    图片的删法分两种：
      * 常驻缓存件（.cache/，静态卡复用）—— **永不删**，由 Renderer 自己识别；
      * 一次性临时件（tmp/）—— 发出成功即删；**发送失败**才留着（便于排查），
        但会记一条日志，并由 sweep_tmp 在 6 小时内清掉，不会无限堆积。
    """
    gid = handler_event.get("group_id")
    uid = handler_event.get("user_id")
    sent = False
    try:
        if kind == "image":
            if gid:
                API.send_group_image(gid, content)
            else:
                API.send_private_image(uid, content)
        else:
            if gid:
                API.send_group_text(gid, content)
            else:
                API.send_private_text(uid, content)
        sent = True
        return True
    except Exception as exc:
        if kind == "image":
            log("[send-fail-keep]", "保留临时图待排查：%s（%s）" % (content, type(exc).__name__))
        raise
    finally:
        if kind == "image" and sent:
            RENDERER.cleanup_after_send(content)


def process_event(event):
    """处理一条 OneBot 事件。"""
    try:
        if event.get("post_type") != "message":
            return
        mtype = event.get("message_type")
        gid = event.get("group_id") if mtype == "group" else None
        uid = event.get("user_id")
        if uid is None:
            return
        if gid is not None and not in_whitelist(gid):
            return
        cmd, args = parse_command(event.get("message"))
        if not cmd:
            return
        log("[cmd]", uid, gid or "-", cmd, args[:40])
        try:
            kind, content = handle_command(cmd, args, uid, gid)
        except render_mod.RenderError as exc:
            log("[render-fail]", exc)
            kind, content = "text", "Chrome 崩了，请联系管理员。"
        except Exception as exc:
            log("[error]", type(exc).__name__, exc)
            traceback.print_exc()
            kind, content = "text", "处理出错了，请联系管理员。（%s）" % type(exc).__name__
        try:
            reply({"group_id": gid, "user_id": uid}, kind, content)
        except Exception as exc:
            log("[send-fail]", type(exc).__name__, exc)
    except Exception:
        traceback.print_exc()


def process_event_safe(event):
    try:
        process_event(event)
    except Exception:
        traceback.print_exc()


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "bounty-bot/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _authorized(self):
        """鉴权：**宽容放行**，绝不用 403 卡住上报。

        为什么：NapCat 的 Http Client 上报在非 2xx 时会记
        「新消息事件HTTP上报返回快速操作失败」并可能中断该条投递——实测三个
        机器人里只有本机返回 403，正是这条报错的来源。
        token 只用来「配对校验」：不匹配记一条日志，仍然处理。
        需要严格模式的部署可把 config.napcat.strict_token 设为 true。
        """
        token = (CFG.get("napcat") or {}).get("token") or ""
        strict = bool((CFG.get("napcat") or {}).get("strict_token"))
        if not token:
            return True
        got = self.headers.get("Authorization", "") or ""
        ok = (got == "Bearer " + token) or (got == token)
        if not ok:
            log("[auth]", "token 不匹配（%s），按宽容模式放行" % (got[:24] or "<无>"))
            return not strict        # 默认：不匹配也放行
        return True

    #: 请求体上限（防超大载荷打爆内存）
    MAX_BODY = 8 * 1024 * 1024

    def _body(self):
        """读请求体。

        ★ 必须同时支持 **chunked** 与 Content-Length 两种编码：
          NapCat 的 Http Client 上报**不带 Content-Length**（chunked），
          早期实现只认 Content-Length，会把 length 当 0 => 读到空 {} =>
          每条真实消息都被静默丢弃（现象：事件到了 3040 却不进命令处理）。
        """
        raw = b""
        if (self.headers.get("Transfer-Encoding", "") or "").lower().strip() == "chunked":
            raw = self._read_chunked()
        else:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                return None
            if length < 0 or length > self.MAX_BODY:
                return None
            raw = self.rfile.read(length) if length else b""
            if length and len(raw) != length:
                return None                      # 体不完整，别拿半截 JSON 去解析
        if len(raw) > self.MAX_BODY:
            return None
        return raw or b"{}"

    def _read_chunked(self):
        """读 chunked 体；格式错/超限返回 b''（交由上层当空事件）。"""
        chunks, total = [], 0
        while True:
            line = self.rfile.readline(64)
            if not line:
                break
            try:
                size = int(line.strip().split(b";", 1)[0] or b"0", 16)
            except ValueError:
                return b""
            if size <= 0:
                self.rfile.readline(8)           # 吃掉结尾 CRLF
                break
            total += size
            if total > self.MAX_BODY:
                return b""
            chunks.append(self.rfile.read(size))
            self.rfile.readline(8)               # 每个 chunk 后的 CRLF
        return b"".join(chunks)

    def _reply(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        if not self.path.split("?")[0].startswith("/onebot"):
            self.send_error(404)
            return
        if not self._authorized():
            self.send_error(403)
            return
        raw = self._body()
        if raw is None:
            self.send_error(400)
            return
        try:
            event = json.loads(raw.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError:
            self.send_error(400)
            return
        # NapCat 期望快速 204，业务异步处理
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()
        threading.Thread(target=process_event_safe, args=(event,), daemon=True).start()

    def do_GET(self):
        if self.path.split("?")[0].startswith("/health"):
            body = json.dumps({"ok": True, "ts": time.time()}).encode()
            self._reply(200, body)
            return
        self.send_error(404)


# ---------------------------------------------------------------- 定时同步

def sync_loop():
    """每 2.5 小时自动同步（刻意错开电力采样与 keypool 的整点）。"""
    interval = int((CFG.get("sync") or {}).get("interval_seconds", 9000))
    interval = max(interval, 60)
    time.sleep(20)
    while True:
        try:
            res = sync_mod.sync_all(CONN, CFG, force=False)
            log("[sync]", res.summary().replace("\n", " | "))
        except Exception as exc:
            log("[sync-error]", type(exc).__name__, exc)
        try:
            RENDERER.sweep_tmp()
        except Exception as exc:
            log("[sweep-error]", type(exc).__name__, exc)
        time.sleep(interval)


def main():
    global CFG, CONN, RENDERER, API
    CFG = load_config()
    CONN = db.connect(ROOT / "bounty.db")
    RENDERER = render_mod.Renderer(CFG.get("render"), ROOT)
    API = onebot.OneBot(
        (CFG.get("napcat") or {}).get("url", "http://127.0.0.1:3010"),
        (CFG.get("napcat") or {}).get("token", ""),
    )
    host = CFG["listen_host"]
    port = int(CFG["listen_port"])
    log("悬赏机器人启动 http://%s:%s/onebot" % (host, port))
    log("  群白名单:", CFG.get("group_whitelist") or "(全部)")
    log("  仓库:", CFG["repo"])
    log("  结算表:", CFG["contrib_path"])
    b = CFG.get("bounty") or {}
    log("  悬赏源:", ("真源 %s" % b.get("source_path", "docs/bounty/悬赏.json"))
        if (b.get("mode") or "json") == "json" else "issue（标题前缀「悬赏」）")
    log("  悬赏口径:", "认领与否均计入，只排除已结束(done)")

    def _bye(signum, frame):
        log("[signal]", signum, "退出")
        raise SystemExit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _bye)
        except (ValueError, OSError):
            pass

    if (CFG.get("sync") or {}).get("on_start", True):
        try:
            res = sync_mod.sync_all(CONN, CFG, force=False)
            log("[startup-sync]", res.summary().replace("\n", " | "))
        except Exception as exc:
            log("[startup-sync-error]", type(exc).__name__, exc)
    threading.Thread(target=sync_loop, daemon=True).start()
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        try:
            CONN.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
