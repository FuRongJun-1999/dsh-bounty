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
    b.setdefault("mode", "issues")          # issues = 标题带「悬赏」的 issue
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


def parse_command(message):
    """OneBot message（array 或 string）-> (cmd, args)。只认行首第一个词。"""
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
    first, _, rest = text.partition(" ")
    return first.strip(), rest.strip()


# ---------------------------------------------------------------- 指令实现

COMMANDS = [
    {"cmd": "/帮助", "desc": "查看本说明"},
    {"cmd": "/悬赏", "desc": "查看当前悬赏委托（来自本仓 issue）"},
    {"cmd": "/绑定 <GitHub 用户名>", "desc": "绑定你的 GitHub 账号"},
    {"cmd": "/我的贡献", "desc": "查看累计声誉分与悬赏热力图"},
    {"cmd": "/榜单", "desc": "查看声誉榜"},
    {"cmd": "/更新", "desc": "立刻检查是否有最新结算表与悬赏"},
]


def cmd_help() -> str:
    """返回图片路径。"""
    return RENDERER.render("help", {"commands": COMMANDS})


def cmd_bounty() -> str:
    items = db.list_bounties(CONN)
    return RENDERER.render("bounty", {
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
    return "ok", RENDERER.render("contribution", payload)


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
        return "这个 GitHub 账号已经绑定了另一个 QQ（尾号 %s），不能重复绑定。" % str(exist["qq"])[-4:]

    try:
        action, old = db.bind(CONN, qq, canonical)
    except db.BindConflict:
        # 并发下另一个 QQ 刚抢走同一 GitHub：唯一索引兜住
        return "这个 GitHub 账号刚刚被别的 QQ 绑走了，请换一个或联系管理员。"
    if action == "created":
        return "绑定成功！\nGitHub：%s\n发送「/我的贡献」查看你的累计贡献。" % canonical
    if (old or "").lower() == canonical.lower():
        return "绑定成功！\nGitHub：%s（与上次相同）" % canonical
    return "绑定成功！（已由 %s 更新为 %s）\n发送「/我的贡献」查看你的累计贡献。" % (old, canonical)


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


def cmd_rank() -> str:
    """（附加）声誉榜。渲染成图片。"""
    rows = db.all_totals(CONN)
    return RENDERER.render("rank", {"ranking": rows,
                                    "synced_at": db.meta_get(CONN, "contrib_synced_at")})


# ---------------------------------------------------------------- 消息路由

RENDER_CMDS = {"/帮助": cmd_help, "/悬赏": cmd_bounty, "/榜单": cmd_rank}


def handle_command(cmd, args, qq, group_id):
    """返回 (kind, content)。kind in {text, image}。"""
    if cmd in RENDER_CMDS:
        return "image", RENDER_CMDS[cmd]()
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
    """发回结果；图片**发出成功后**才删临时文件（发送失败保留，交 sweep_tmp 兜底）。"""
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
        token = (CFG.get("napcat") or {}).get("token") or ""
        if not token:
            return True
        got = self.headers.get("Authorization", "")
        return got == "Bearer " + token

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return None
        if length <= 0 or length > 8 * 1024 * 1024:   # 8MB 上限，防超大载荷打爆内存
            return b"{}"
        return self.rfile.read(length)

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
    log("  悬赏源:", "issue（标题前缀「悬赏」）")

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
