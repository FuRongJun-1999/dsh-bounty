# -*- coding: utf-8 -*-
"""渲染器：调外部 HTML->图片 管线（由用户侧负责 HTML 与出图）。

本文件只做**契约与调度**，不含 HTML/CSS/视觉：

  1. 把命令数据写成 JSON 交给渲染入口；
  2. 渲染入口产出 PNG 路径；
  3. 失败/超时 => 抛 RenderError，由 bot 回「Chrome 崩了，请联系管理员」。

契约（config.json 的 render 段）
------------------------------
    {
      "cmd": ["node", "/opt/bounty-bot/render/render.js", "{payload}", "{out}"],
      "cwd": "/opt/bounty-bot/render",
      "timeout": 60
    }
  占位符 {payload} / {out} 会被替换为真实路径。渲染器只需：
      node render.js <payload.json> <out.png>
  退出码 0 且 <out.png> 存在且非空 => 成功。

★ 渲染**串行**（全局锁）：一号机内存余量有限，避免并发多开 Chrome。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

_RENDER_LOCK = threading.Lock()

#: 渲染器常量超时上限——避免配错一个 0/负数就让主线程永不返回
_MAX_TIMEOUT = 600
_DEFAULT_TIMEOUT = 60


class RenderError(RuntimeError):
    """渲染失败（含 Chrome 崩溃、超时、产物缺失）。"""


class Renderer:
    def __init__(self, cfg, workdir):
        self.cfg = cfg or {}
        self.workdir = Path(workdir)
        self.tmpdir = self.workdir / "tmp"
        self.tmpdir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self):
        return bool(self.cfg.get("cmd"))

    def _timeout(self, timeout):
        try:
            t = int(timeout if timeout is not None else self.cfg.get("timeout", _DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            t = _DEFAULT_TIMEOUT
        if t <= 0:
            t = _DEFAULT_TIMEOUT
        return min(t, _MAX_TIMEOUT)

    def render(self, kind, payload, timeout=None):
        """kind: help|bounty|contribution|rank。返回 PNG 路径。"""
        if not self.enabled:
            raise RenderError("渲染器未配置")
        limit = self._timeout(timeout)
        with _RENDER_LOCK:
            stamp = "%s_%d_%d" % (kind, int(time.time() * 1000), threading.get_ident() % 100000)
            payload_path = self.tmpdir / (stamp + ".json")
            out_path = self.tmpdir / (stamp + ".png")
            data = dict(payload or {})
            data["kind"] = kind
            data["_generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            payload_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            cmd = [str(payload_path) if c == "{payload}" else
                   str(out_path) if c == "{out}" else c
                   for c in self.cfg["cmd"]]
            env = dict(os.environ)
            env.update({k: str(v) for k, v in (self.cfg.get("env") or {}).items()})
            cwd = self.cfg.get("cwd") or str(self.workdir)
            try:
                proc = subprocess.run(
                    cmd, cwd=str(cwd), capture_output=True, timeout=limit, env=env,
                )
            except subprocess.TimeoutExpired as exc:
                self._cleanup(payload_path, out_path)
                raise RenderError("渲染超时（%ss）" % limit) from exc
            except FileNotFoundError as exc:
                self._cleanup(payload_path, out_path)
                raise RenderError("渲染器不存在：%s" % cmd[0]) from exc
            except OSError as exc:
                self._cleanup(payload_path, out_path)
                raise RenderError("渲染器启动失败：%s" % exc) from exc

            if proc.returncode != 0 or not out_path.exists():
                tail = (proc.stderr or proc.stdout or b"")[-400:].decode("utf-8", "replace")
                self._cleanup(payload_path, out_path)
                raise RenderError("渲染失败（exit=%s）：%s" % (proc.returncode, tail.strip()))
            if out_path.stat().st_size == 0:
                self._cleanup(payload_path, out_path)
                raise RenderError("渲染产物为空文件")
            return str(out_path)

    def _cleanup(self, *paths):
        for p in paths:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass

    def cleanup_after_send(self, path, keep=False):
        """图片发出后删除临时文件（用户要求：发出去之后不再保存）。

        同时删掉同批次的 payload JSON（与 PNG 同基名，仅后缀不同）。
        """
        if keep or not path:
            return
        p = Path(path)
        for target in (p, p.with_suffix(".json")):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass

    def sweep_tmp(self, max_age_hours=6):
        """清理残留临时文件（崩溃留下的 PNG/JSON，以及渲染器留下的中间 HTML）。"""
        cutoff = time.time() - max_age_hours * 3600
        n = 0
        for p in self.tmpdir.glob("*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
                    n += 1
            except OSError:
                pass
        return n
