"""
Task 12.3: __test_connection 白名单测试（P0）
验证 Media Server 固定映射和网络测试白名单正确工作，
所有攻击 payload 均被拒绝。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import MagicMock, patch


# 白名单逻辑直接复刻（不依赖项目初始化）
NETTEST_WHITELIST = {
    "www.themoviedb.org", "image.tmdb.org", "webservice.fanart.tv",
    "api.telegram.org", "qyapi.weixin.qq.com", "www.opensubtitles.org"
}
MEDIA_SERVER_MAP = {
    "app.mediaserver.client.emby|Emby",
    "app.mediaserver.client.jellyfin|Jellyfin",
    "app.mediaserver.client.plex|Plex",
    "app.mediaserver.client.kodi|Kodi",
}


def is_allowed(cmd):
    if "|" in cmd:
        return cmd in MEDIA_SERVER_MAP
    return cmd in NETTEST_WHITELIST


class TestTestConnectionWhitelist:
    """白名单策略单元测试（不依赖 Flask / Config 初始化）"""

    def test_media_server_allowed(self):
        assert is_allowed("app.mediaserver.client.emby|Emby")
        assert is_allowed("app.mediaserver.client.jellyfin|Jellyfin")
        assert is_allowed("app.mediaserver.client.plex|Plex")
        assert is_allowed("app.mediaserver.client.kodi|Kodi")

    def test_media_server_rejected(self):
        assert not is_allowed("app.utils.system_utils|SystemUtils")
        assert not is_allowed("os|system")
        assert not is_allowed("app.mediaserver.client.emby|System")
        assert not is_allowed("__import__('os').system('id')")

    def test_network_allowed(self):
        assert is_allowed("www.themoviedb.org")
        assert is_allowed("api.telegram.org")
        assert is_allowed("image.tmdb.org")

    def test_ssrf_rejected(self):
        assert not is_allowed("127.0.0.1:22")
        assert not is_allowed("localhost:3000")
        assert not is_allowed("169.254.169.254")
        assert not is_allowed("10.0.0.1")
        assert not is_allowed("192.168.1.1")
        assert not is_allowed("internal.service.local")

    def test_rce_payload_rejected(self):
        assert not is_allowed('__import__("os").system("id")')
        assert not is_allowed('open("/etc/passwd").read()')
        assert not is_allowed('().__class__.__bases__[0].__subclasses__()')

    @patch('web.action.RequestUtils')
    @patch('web.action.Config')
    @patch('web.action.Emby')
    def test_webaction_emby_allowed(self, mock_emby_cls, mock_config, mock_req):
        """端到端：合法 Emby 测试应通过（mock）"""
        from web.action import WebAction
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = True
        mock_instance.init_config = MagicMock()
        mock_emby_cls.return_value = mock_instance
        ret = WebAction._WebAction__test_connection({"command": "app.mediaserver.client.emby|Emby"})
        assert ret["code"] == 0

    @patch('web.action.Config')
    def test_webaction_ssrf_rejected(self, mock_config):
        """端到端：SSRF payload 应被拒绝"""
        from web.action import WebAction
        ret = WebAction._WebAction__test_connection({"command": "127.0.0.1:22"})
        assert ret["code"] == 1

    @patch('web.action.Config')
    def test_webaction_rce_rejected(self, mock_config):
        """端到端：RCE payload 应被拒绝"""
        from web.action import WebAction
        ret = WebAction._WebAction__test_connection({"command": '__import__("os").system("id")'})
        assert ret["code"] == 1
