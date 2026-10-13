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

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

_RENDER_LOCK = threading.Lock()

#: 渲染器常量超时上限——避免配错一个 0/负数就让主线程永不返回
_MAX_TIMEOUT = 600
#: 默认渲染超时。无头 Chrome 冷启动 + 长卡（悬赏 6 条能到 3000px 高）实测 8~12s，
#: 机器负载高时会翻倍，故给 150s 余量（不是让渲染变慢，是别误判超时）。
_DEFAULT_TIMEOUT = 150


class RenderError(RuntimeError):
    """渲染失败（含 Chrome 崩溃、超时、产物缺失）。"""


#: 默认缓存目录名（相对 workdir）
_CACHE_DIR = ".cache"

#: 默认不过期的 kind——内容是静态的，渲染一次后可长期复用
_STATIC_KINDS = ("help",)


class Renderer:
    def __init__(self, cfg, workdir):
        self.cfg = cfg or {}
        self.workdir = Path(workdir)
        self.tmpdir = self.workdir / "tmp"
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.cachedir = self.workdir / str(self.cfg.get("cache_dir") or _CACHE_DIR)
        self.cachedir.mkdir(parents=True, exist_ok=True)
        self._style_fp = None      # 模板指纹，惰性计算一次

    @property
    def enabled(self):
        return bool(self.cfg.get("cmd"))

    # ------------------------------------------------------------ 缓存
    @property
    def cache_enabled(self):
        return self.cfg.get("cache", True) is not False

    def _static_kinds(self):
        """静态卡（内容不变，永不过期）。配置可覆盖；置空数组则全部实时渲染。"""
        v = self.cfg.get("static_kinds")
        if v is None:
            return _STATIC_KINDS
        if isinstance(v, str):
            return (v,) if v else ()
        return tuple(v)

    def style_fingerprint(self):
        """模板与样式的指纹，参与缓存键。

        没有它，改了 HTML/CSS 但 payload 没变时会**永远发旧图**（静态卡尤其致命）。
        取渲染工作目录下的 *.html / *.css（数量少、体积小）。
        """
        if self._style_fp is not None:
            return self._style_fp
        base = Path(self.cfg.get("cwd") or self.workdir)
        h = hashlib.sha256()
        try:
            files = sorted([p for p in base.glob("*.html")] + [p for p in base.glob("*.css")],
                           key=lambda p: p.name)
            for p in files:
                h.update(p.name.encode("utf-8"))
                h.update(p.read_bytes())
        except OSError:
            pass
        self._style_fp = h.hexdigest()[:12]
        return self._style_fp

    def cache_key(self, kind, data):
        """按**渲染真正用到的东西**算键。

        注意要排除 _generated_at 这类每次都变的时间戳，否则缓存永不命中。
        """
        # 排除 _xxx（每次变的时间戳）与 kind（由参数单独给，别重复进 payload）
        payload = {k: v for k, v in (data or {}).items()
                   if not k.startswith("_") and k != "kind"}
        blob = json.dumps({"kind": kind, "payload": payload,
                           "style": self.style_fingerprint()},
                          ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]

    def _cache_path(self, kind, key):
        return self.cachedir / ("%s_%s.png" % (kind, key))

    def cached(self, kind, payload):
        """命中则返回可发送的 PNG 路径，否则 None。"""
        if not (self.enabled and self.cache_enabled):
            return None
        key = self.cache_key(kind, payload)
        p = self._cache_path(kind, key)
        try:
            if p.is_file() and p.stat().st_size > 0:
                return str(p)
        except OSError:
            pass
        return None

    def _store_cache(self, kind, key, out_path):
        """把渲染产物收进缓存；成功返回缓存路径（供调用方统一返回），否则 None。"""
        if not (self.cache_enabled and kind in self._static_kinds()):
            return None
        dst = self._cache_path(kind, key)
        if Path(out_path).suffix.lower() == ".jpg":
            dst = dst.with_suffix(".jpg")
        try:
            shutil.copyfile(out_path, dst)
        except OSError:
            return None
        try:
            Path(out_path).unlink(missing_ok=True)   # 中间产物清掉，缓存件即唯一副本
        except OSError:
            pass
        return str(dst)

    def render_cached(self, kind, payload, timeout=None):
        """先查缓存，命中直接返回；未命中才真渲染。

        静态卡（默认 help）渲染一次后长期复用；动态卡（bounty/contribution/rank）
        只要 payload 没变也复用——数据一变，key 就变，自然重渲染。
        """
        hit = self.cached(kind, payload)
        if hit:
            return hit
        key = self.cache_key(kind, payload)     # 与 cached() 同一算法，勿再包一层
        path = self.render(kind, payload, timeout=timeout)
        # 静态卡：返回缓存件本身（唯一副本）——这样调用方拿到的路径发完也不会被删
        return self._store_cache(kind, key, path) or path

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
            return self._shrink(out_path)

    def _shrink(self, out_path):
        """把产物压到适合 QQ 上传的体积（不压则原样返回）。

        不压的后果：NapCat 默认 uploadSpeedKBps=256，3MB 图 base64 后 4MB，
        上传要 16 秒 > baseTimeout(10s) => 「send_group_msg 失败：timed out」。
        """
        if self.cfg.get("compress", True) is False:
            return str(out_path)
        try:
            import imageopt
            target = int(self.cfg.get("max_image_kb", 900)) * 1024
            newp, changed = imageopt.compress_png(
                out_path, target_bytes=target,
                quality=int(self.cfg.get("jpeg_quality", 82)),
                allow_jpeg=self.cfg.get("allow_jpeg", True) is not False)
            if changed:
                pass  # 压缩成功（可能换了后缀）
            return str(newp)
        except Exception:
            return str(out_path)   # 压缩失败绝不能影响出图

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
        # 缓存件是长期复用的资产，发完不能删
        try:
            if p.parent.resolve() == self.cachedir.resolve():
                return
        except OSError:
            pass
        # 一并清掉同批次的 payload JSON 与压缩可能产生的 .jpg
        for target in (p, p.with_suffix(".json"), p.with_suffix(".jpg")):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass

    def sweep_tmp(self, max_age_hours=6):
        """清理残留临时文件（崩溃留下的 PNG/JSON）。

        只扫 tmp/——缓存目录（默认 .cache/）是长期资产，绝不在此清理。
        """
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
