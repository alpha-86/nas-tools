# -*- coding: utf-8 -*-
import hashlib
import os
import time
from urllib.parse import urlparse

from app.utils.commons import singleton
from app.utils.http_utils import RequestUtils

# 各域名专用 headers 映射
_DOMAIN_HEADERS = {
    "doubanio.com": {
        "User-Agent": "MicroMessenger/",
        "Referer": "https://servicewechat.com/wx2f9b06c1de1ccfca/91/page-frame.html"
    },
}

# 默认缓存 TTL（秒）
_DEFAULT_TTL = 30 * 24 * 3600


@singleton
class ImageCache:
    """
    通用图片磁盘缓存。
    - 按 URL SHA-256 存储到 <config_dir>/cache/images/
    - 命中缓存直接返回，不重新拉取
    - 自动为特定域名（如 doubanio.com）注入专用 UA / Referer
    """

    def __init__(self):
        from config import Config
        self._cache_dir = os.path.join(Config().get_config_path(), "cache", "images")
        os.makedirs(self._cache_dir, exist_ok=True)
        self._ttl = _DEFAULT_TTL

    # ------------------------------------------------------------------ #
    #  公开接口
    # ------------------------------------------------------------------ #
    def get(self, url):
        """
        获取图片二进制内容。
        优先从磁盘缓存读取；未命中或已过期则发起 HTTP 请求并写入缓存。
        """
        path = self._cache_path(url)

        # 命中缓存：文件存在且未过期
        if os.path.isfile(path):
            mtime = os.path.getmtime(path)
            if mtime + self._ttl > time.time():
                with open(path, "rb") as f:
                    return f.read()

        # 未命中：发起请求
        content = self._fetch(url)
        if content:
            self._write(path, content)
        return content

    # ------------------------------------------------------------------ #
    #  内部方法
    # ------------------------------------------------------------------ #
    def _cache_path(self, url):
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return os.path.join(self._cache_dir, key)

    def _domain_headers(self, url):
        """根据 URL 域名返回专用 headers，无匹配则返回 {}。"""
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            return {}
        for suffix, headers in _DOMAIN_HEADERS.items():
            if host.endswith(suffix):
                return headers
        return {}

    def _fetch(self, url):
        """
        发起带完整 headers 的 HTTP GET 请求。
        doubanio.com 等域名自动使用专用 UA / Referer，其余使用系统默认 UA。
        同时使用用户配置的代理（如有）。
        """
        from config import Config
        headers = self._domain_headers(url)
        if headers:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        proxies = Config().get_proxies() or None
        try:
            resp = RequestUtils(
                headers=headers or None,
                proxies=proxies,
            ).get_res(url)
            if resp and resp.status_code == 200:
                return resp.content
        except Exception:
            pass
        return None

    @staticmethod
    def _write(path, content):
        """原子写入：先写 .tmp 再 rename，避免读到半截文件。"""
        tmp = path + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(content)
            os.rename(tmp, path)
        except Exception:
            # 清理残留临时文件
            try:
                os.remove(tmp)
            except OSError:
                pass
