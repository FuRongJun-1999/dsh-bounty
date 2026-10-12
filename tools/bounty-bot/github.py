# -*- coding: utf-8 -*-
"""GitHub 抓取（标准库，无第三方依赖）。

一号机实测网络：
    raw.githubusercontent.com  X 不可达（IPv6 无路由）
    api.github.com             OK 200
    ghproxy.net                OK 200
    cdn.jsdelivr.net           OK 200

取数链：
  · 文件（结算表）：api.github.com/contents -> ghproxy -> jsdelivr（逐级回落）
  · issue（悬赏）：api.github.com REST（/search 限流更紧，故走列表接口）

未配 token 时 GitHub API 限 60 次/小时——靠 ETag/If-None-Match 条件请求
（304 不计费）+ 本地缓存兜住；配了 token 提到 5000/小时。
"""
from __future__ import annotations

import base64
import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "bounty-bot/1.0 (+group bot)"
TIMEOUT = 25
API = "https://api.github.com"

#: 读体失败（IncompleteRead）与网络抖动的重试次数
RETRIES = 3
#: 单次响应的读体上限，防呆
MAX_BODY = 16 * 1024 * 1024

#: 这些异常都表示「传输层没把体读全」，重试有意义
_RETRYABLE = (http.client.IncompleteRead, http.client.HTTPException,
              socket.timeout, TimeoutError, ConnectionError)


class GitHubError(RuntimeError):
    pass


def _open_once(req, etag):
    """一次请求。成功返回 (状态码, body, etag)；读体不全则抛可重试异常。"""
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        code = int(resp.getcode())
        new_etag = resp.headers.get("ETag")
        try:
            body = resp.read()
        except http.client.IncompleteRead as e:
            # 体没读全：把已到的部分拼上再重试一次整体（半截 JSON 不能解析）
            raise
        if len(body) > MAX_BODY:
            raise GitHubError("响应体过大（>%d 字节）：%s" % (MAX_BODY, req.full_url))
        return code, body, new_etag


def _request(url, token="", etag=None, accept=None):
    """返回 (状态码, body bytes, ETag)。304 时 body 为空。

    为什么带重试：api.github.com 在返回大 JSON（issue 列表带正文）时，
    偶发 IncompleteRead——一次失败不该让整轮同步报错。
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": accept or "application/vnd.github+json, text/plain, */*",
        "Accept-Encoding": "identity",       # 不要 gzip：少一层解压，少一类半截体
    })
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if etag:
        req.add_header("If-None-Match", etag)

    last = None
    for attempt in range(RETRIES):
        try:
            return _open_once(req, etag)
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return 304, b"", etag
            if e.code >= 500 and attempt < RETRIES - 1:      # 5xx 抖动可重试
                last = e
                time.sleep(0.6 * (attempt + 1))
                continue
            try:
                detail = e.read()[:400]
            except Exception:
                detail = b""
            return int(e.code), detail, None
        except _RETRYABLE as e:
            last = e
            if attempt < RETRIES - 1:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise GitHubError("读取响应失败（已重试 %d 次）：%s（%s）" % (RETRIES, url, e)) from e
        except urllib.error.URLError as e:
            last = e
            if attempt < RETRIES - 1:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise GitHubError("网络不可达：%s（%s）" % (url, e.reason)) from e
    raise GitHubError("请求失败：%s（%s）" % (url, last))


# ---------------------------------------------------------------- 文件

def fetch_text(repo, path, branch="main", token="", etag=None):
    """取仓库某文件的文本。返回 (状态码, 文本, 新 ETag)。304 时文本为空。

    路径需 URL 编码（结算表文件名含中文）。
    """
    q = urllib.parse.quote(path)
    url = "%s/repos/%s/contents/%s?ref=%s" % (API, repo, q, branch)
    code, body, new_etag = _request(url, token, etag)
    if code == 304:
        return 304, "", etag
    if code == 200:
        try:
            payload = json.loads(body.decode("utf-8"))
            content = base64.b64decode(payload.get("content") or "").decode("utf-8", "replace")
            return 200, content, payload.get("sha") or new_etag
        except Exception as exc:
            raise GitHubError("解析 API 响应失败：%s" % exc) from exc
    if code == 404:
        raise GitHubError("仓库内没有这个文件：%s@%s/%s" % (repo, branch, path))
    last_err = "api.github.com -> HTTP %s" % code

    url2 = "https://ghproxy.net/https://raw.githubusercontent.com/%s/%s/%s" % (repo, branch, q)
    code2, body2, etag2 = _request(url2)
    if code2 == 200:
        return 200, body2.decode("utf-8", "replace"), etag2
    last_err += "; ghproxy -> HTTP %s" % code2

    url3 = "https://cdn.jsdelivr.net/gh/%s@%s/%s" % (repo, branch, q)
    code3, body3, etag3 = _request(url3)
    if code3 == 200:
        return 200, body3.decode("utf-8", "replace"), etag3
    last_err += "; jsdelivr -> HTTP %s" % code3

    raise GitHubError("取数失败：%s" % last_err)


# ---------------------------------------------------------------- JSON / 列表

def fetch_json_url(url, token="", etag=None):
    """取一个 JSON 端点。返回 (状态码, 对象 或 None, 新 ETag)。"""
    code, body, new_etag = _request(url, token, etag)
    if code == 304:
        return 304, None, etag
    if code != 200:
        raise GitHubError("接口返回 HTTP %s：%s" % (code, url))
    try:
        return 200, json.loads(body.decode("utf-8")), new_etag
    except ValueError as exc:
        raise GitHubError("接口响应不是 JSON：%s" % exc) from exc


def list_issues(repo, token="", state="open", labels=None, per_page=100, max_pages=3):
    """列 issue（**不含 PR**：接口会把 PR 混进来，这里按 pull_request 字段剔除）。

    返回 (issues, truncated)。truncated=True 表示还有更多页未取。

    per_page 自适应：issue 带正文时整页 JSON 可能上 MB，实测 api.github.com 会
    偶发 IncompleteRead——页太大就自动减半重试，而不是把整轮同步判失败。
    """
    out, page, pp = [], 1, max(1, min(int(per_page), 100))
    while page <= max_pages:
        q = {"state": state, "per_page": str(pp), "page": str(page),
             "sort": "updated", "direction": "desc"}
        if labels:
            q["labels"] = labels
        url = "%s/repos/%s/issues?%s" % (API, repo, urllib.parse.urlencode(q))
        try:
            _code, data, _etag = fetch_json_url(url, token)
        except GitHubError:
            if pp > 10:                  # 页太大 => 减半再来同页
                pp //= 2
                continue
            raise
        if not isinstance(data, list):
            raise GitHubError("issue 列表响应不是数组")
        out.extend(i for i in data if isinstance(i, dict) and "pull_request" not in i)
        if len(data) < pp:
            return out, False
        page += 1
    return out, True


# ---------------------------------------------------------------- 用户

def canonical_login(login, token=""):
    """取 GitHub 上的规范大小写名；不存在返回 None。"""
    login = (login or "").strip()
    if not login:
        return None
    url = "%s/users/%s" % (API, urllib.parse.quote(login))
    try:
        code, body, _ = _request(url, token)
        if code != 200:
            return None
        return json.loads(body.decode("utf-8")).get("login")
    except Exception:
        return None


def user_exists(login, token=""):
    """校验 GitHub 用户名真实存在（大小写不敏感）。"""
    return canonical_login(login, token) is not None
