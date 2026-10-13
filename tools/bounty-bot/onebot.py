# -*- coding: utf-8 -*-
"""图片发送（OneBot v11 标准接口）。

NapCat 的 HTTP 服务在 127.0.0.1:3010；机器人经它发群消息。
图片以 base64 形式内联发送（免公网图床、免容器挂载），发完即删本地文件。

为什么不用 file:// 路径：NapCat 跑在容器里，宿主机路径它看不见；
base64 是唯一不依赖挂载约定的通道。
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "bounty-bot/1.0"
#: QQ 单条消息的图片体积经验上限（base64 后约 1.33 倍）；超了就在日志里点名
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class OneBotError(RuntimeError):
    pass


#: 发图/发消息这类写操作的重试次数（网络抖动、上传超时）
_SEND_RETRIES = 2


class OneBot:
    def __init__(self, base_url, token="", timeout=60, retries=_SEND_RETRIES):
        self.base_url = base_url.rstrip("/")
        self.token = token or ""
        # 默认 60s：图片要经 NapCat 上传（默认限速 256KB/s），30s 会误判超时
        self.timeout = timeout
        self.retries = max(0, int(retries))

    def _call(self, action, payload=None):
        url = "%s/%s" % (self.base_url, action)
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        last = None
        for attempt in range(self.retries + 1):
            try:
                return self._call_once(url, action, body)
            except OneBotError as exc:
                last = exc
                # 只重试「超时/网络」这类瞬时失败；retcode 业务错误不重试
                if "timed out" not in str(exc) and "urlopen error" not in str(exc):
                    raise
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        raise last

    def _call_once(self, url, action, body):
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": UA})
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise OneBotError("HTTP %s: %s" % (e.code, e.read()[:200])) from e
        except Exception as exc:
            raise OneBotError("调用 %s 失败：%s" % (action, exc)) from exc
        try:
            data = json.loads(raw or "{}")
        except ValueError as exc:
            raise OneBotError("调用 %s 返回的不是 JSON：%s" % (action, raw[:200])) from exc
        # OneBot v11：status=ok / retcode=0 为成功；两者都不给时按成功处理（兼容实现差异）
        if data.get("status") not in (None, "ok") and data.get("retcode") not in (0, None):
            raise OneBotError("retcode=%s %s" % (data.get("retcode"), data.get("message")))
        return data

    def send_group_text(self, group_id, text):
        return self._call("send_group_msg", {"group_id": int(group_id), "message": text})

    def send_private_text(self, user_id, text):
        return self._call("send_private_msg", {"user_id": int(user_id), "message": text})

    def send_group_image(self, group_id, path):
        return self._call("send_group_msg", {
            "group_id": int(group_id),
            "message": [{"type": "image", "data": {"file": self._as_base64(path)}}],
        })

    def send_private_image(self, user_id, path):
        return self._call("send_private_msg", {
            "user_id": int(user_id),
            "message": [{"type": "image", "data": {"file": self._as_base64(path)}}],
        })

    @staticmethod
    def _as_base64(path):
        p = Path(path)
        raw = p.read_bytes()
        if not raw:
            raise OneBotError("图片是空文件：%s" % p)
        if len(raw) > MAX_IMAGE_BYTES:
            raise OneBotError("图片过大（%d 字节 > %d）：%s" % (len(raw), MAX_IMAGE_BYTES, p))
        return "base64://" + base64.b64encode(raw).decode("ascii")
