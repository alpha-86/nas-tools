# -*- coding: utf-8 -*-
from urllib.parse import urlparse, quote

# 需要通过本地代理中转的域名后缀列表
_PROXY_DOMAINS = (
    "doubanio.com",
)


def wrap_image_url(url):
    """
    将需要代理的外部图片 URL 包装为本地 /img?url=... 代理地址。
    不在代理列表中的 URL 原样返回。
    """
    if not url:
        return url
    try:
        host = (urlparse(url).hostname or "").lower()
        for suffix in _PROXY_DOMAINS:
            if host.endswith(suffix):
                return f"/img?url={quote(url, safe='')}"
    except Exception:
        pass
    return url
