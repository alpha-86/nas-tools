# -*- coding: utf-8 -*-
import hashlib
import os
import re
import threading
import time
from itertools import cycle
from urllib.parse import urlparse, urlunparse

from app.utils.commons import singleton
from app.utils.http_utils import RequestUtils

# 各域名专用 headers 映射
_DOMAIN_HEADERS = {
    "doubanio.com": {
        "User-Agent": "MicroMessenger/",
        "Referer": "https://servicewechat.com/wx2f9b06c1de1ccfca/91/page-frame.html"
    },
}

# 豆瓣图片 CDN 域名列表，用于负载均衡
_DOUBAN_CDN_HOSTS = [
    "img1.doubanio.com",
    "img2.doubanio.com",
    "img3.doubanio.com",
    "img9.doubanio.com",
    "qnmob3.doubanio.com",
]

# 默认缓存 TTL（秒）
_DEFAULT_TTL = 30 * 24 * 3600


def _normalize_douban_host(url):
    """
    将 img{N}.doubanio.com / qnmob3.doubanio.com 统一替换为
    img.doubanio.com，保证同一图片在不同 CDN 域名下共享同一个缓存文件。
    """
    return re.sub(r'://(?:qnmob\d+|img\d+)\.doubanio\.com',
                  '://img.doubanio.com', url)


def _assign_douban_host(url, host):
    """
    将任意 doubanio.com 主机替换为指定 CDN 域名。
    """
    parsed = urlparse(url)
    if not (parsed.hostname or "").lower().endswith("doubanio.com"):
        return url
    return urlunparse(parsed._replace(netloc=host))


@singleton
class ImageCache:
    """
    通用图片磁盘缓存。
    - 按 URL SHA-256 存储到 <config_dir>/cache/images/
    - 命中缓存直接返回，不重新拉取
    - doubanio.com 多 CDN 域名归一化缓存 + 轮询负载均衡
    - 信号量控制并发，避免触发远端限流
    - 自动为特定域名注入专用 UA / Referer
    """

    # 最大并发请求数
    _MAX_CONCURRENCY = 5

    def __init__(self):
        from config import Config
        self._cache_dir = os.path.join(Config().get_config_path(), "cache", "images")
        os.makedirs(self._cache_dir, exist_ok=True)
        self._ttl = _DEFAULT_TTL
        # 信号量：限制同时发往远端的请求数
        self._sem = threading.Semaphore(self._MAX_CONCURRENCY)
        # 轮询迭代器：并发请求分配不同 CDN 域名
        self._cdn_cycle = cycle(_DOUBAN_CDN_HOSTS)

    # ------------------------------------------------------------------ #
    #  公开接口
    # ------------------------------------------------------------------ #
    # 最大重试次数
    _MAX_RETRIES = 3

    def get(self, url):
        """
        获取图片二进制内容。
        优先从磁盘缓存读取；未命中或已过期则发起 HTTP 请求并写入缓存。
        失败时自动重试，每次使用不同的 CDN 域名。
        """
        # 缓存 key 使用归一化后的 URL（doubanio CDN 域名统一）
        cache_key_url = _normalize_douban_host(url)
        path = self._cache_path(cache_key_url)

        # 命中缓存：文件存在且未过期
        if os.path.isfile(path):
            mtime = os.path.getmtime(path)
            if mtime + self._ttl > time.time():
                with open(path, "rb") as f:
                    return f.read()

        # 未命中：重试，每次轮询分配不同 CDN 域名
        for attempt in range(self._MAX_RETRIES):
            host = next(self._cdn_cycle)
            fetch_url = _assign_douban_host(url, host)
            content = self._fetch(fetch_url)
            if content:
                self._write(path, content)
                return content
            # 失败后短暂等待再重试
            if attempt < self._MAX_RETRIES - 1:
                time.sleep(0.5 * (attempt + 1))
        return None

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
        通过信号量控制并发数，避免触发远端限流。
        doubanio.com 等域名自动使用专用 UA / Referer，其余使用系统默认 UA。
        """
        from config import Config
        headers = self._domain_headers(url)
        if headers:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        proxies = Config().get_proxies() or None
        self._sem.acquire()
        try:
            resp = RequestUtils(
                headers=headers or None,
                proxies=proxies,
            ).get_res(url)
            if resp and resp.status_code == 200:
                return resp.content
        except Exception:
            pass
        finally:
            self._sem.release()
        return None

    def _write(self, path, content):
        """原子写入：先写 .tmp 再 rename，避免读到半截文件。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
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
