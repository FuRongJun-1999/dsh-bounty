# -*- coding: utf-8 -*-
"""图片压缩：渲染产物 -> 适合 QQ 上传的体积。

为什么要压：NapCat 的 uploadSpeedKBps 默认 256 KB/s，而本机渲染出的 PNG
在 2~3.5 MB，base64 后 2.7~4.7 MB —— 上传要 11~18 秒，超过 baseTimeout(10s)，
表现为「send_group_msg 失败：timed out」或整条渲染超时。

策略（纯 Pillow，不引入外部命令）：
  1. 先试 PNG 调色板量化（保留透明），质量档 0-100 由配置给；
  2. 仍超目标体积 => 退化为 JPEG（无透明需求时体积极小）；
  3. 都失败则原样返回（宁可大，也不能没图）。
"""
from __future__ import annotations

from pathlib import Path

#: 目标体积上限（字节）——留足 base64 膨胀与网络抖动余量
DEFAULT_TARGET = 900 * 1024


def compress_png(path, target_bytes=DEFAULT_TARGET, quality=82, allow_jpeg=True):
    """把 path 压到 target_bytes 以内（就地覆盖同后缀的副本）。

    返回 (新路径, 是否压缩成功)。失败时返回 (原路径, False)，绝不抛。
    """
    src = Path(path)
    try:
        size = src.stat().st_size
    except OSError:
        return str(src), False
    if size <= target_bytes:
        return str(src), False
    try:
        from PIL import Image
    except Exception:
        return str(src), False

    try:
        im = Image.open(src)
        im.load()
    except Exception:
        return str(src), False

    # ① PNG 调色板量化（保住透明）
    try:
        alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
        work = im.convert("RGBA") if alpha else im.convert("RGB")
        for colors in (256, 192, 128, 96, 64):
            q = work.quantize(colors=colors, method=Image.MEDIANCUT)
            buf = src.with_name(src.stem + ".__q.png")
            q.save(buf, "PNG", optimize=True, bits=8)
            if buf.stat().st_size <= target_bytes:
                buf.replace(src)
                return str(src), True
            buf.unlink(missing_ok=True)
        # 量化后仍大：取最小的一版先留着
        q = work.quantize(colors=64, method=Image.MEDIANCUT)
        q.save(src, "PNG", optimize=True, bits=8)
        if src.stat().st_size <= target_bytes:
            return str(src), True
    except Exception:
        pass

    # ② 仍超 => JPEG（卡面是深色木纹，JPEG 压缩率极高）
    if allow_jpeg:
        try:
            im2 = Image.open(src)
            im2.load()
            if im2.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", im2.size, (24, 14, 8))
                rgba = im2.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                im2 = bg
            else:
                im2 = im2.convert("RGB")
            out = src.with_suffix(".jpg")
            for qy in (quality, 70, 60, 50):
                im2.save(out, "JPEG", quality=qy, optimize=True, progressive=True)
                if out.stat().st_size <= target_bytes:
                    src.unlink(missing_ok=True)
                    return str(out), True
            # JPEG 也压不到目标：用最小那版（仍比原 PNG 小就换）
            if out.stat().st_size < size:
                src.unlink(missing_ok=True)
                return str(out), True
            out.unlink(missing_ok=True)
        except Exception:
            pass

    return str(src), False
