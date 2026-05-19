"""
Task 12.4: Telegram webhook 认证测试（P1）
验证 secret_token / X-Telegram-Bot-Api-Secret-Token 机制，
以及 query apikey 短期兼容路径。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import MagicMock, patch


API_KEY = "test-api-key-12345"


class MockRequest:
    """模拟 Flask request 对象"""
    def __init__(self, headers=None, args=None, json_data=None, remote_addr="1.1.1.1"):
        self.headers = headers or {}
        self.args = args or {}
        self._json = json_data or {}
        self.remote_addr = remote_addr

    def get_json(self):
        return self._json


def _check_telegram_auth(req, api_key):
    """
    复刻 web/main.py 中 telegram webhook 的认证逻辑
    """
    secret_token = req.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_token != api_key:
        secret_token = req.args.get("apikey")
        if secret_token != api_key:
            return False, "secret_token 不匹配"
    return True, "通过"


class TestTelegramWebhookAuth:
    def test_correct_secret_token(self):
        req = MockRequest(headers={"X-Telegram-Bot-Api-Secret-Token": API_KEY})
        ok, msg = _check_telegram_auth(req, API_KEY)
        assert ok is True

    def test_wrong_secret_token(self):
        req = MockRequest(headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-key"})
        ok, msg = _check_telegram_auth(req, API_KEY)
        assert ok is False

    def test_no_secret_token_fallback_to_query(self):
        """无 secret_token 时回退到 query apikey（短期兼容）"""
        req = MockRequest(args={"apikey": API_KEY})
        ok, msg = _check_telegram_auth(req, API_KEY)
        assert ok is True

    def test_wrong_query_apikey(self):
        req = MockRequest(args={"apikey": "wrong-key"})
        ok, msg = _check_telegram_auth(req, API_KEY)
        assert ok is False

    def test_no_auth_at_all(self):
        req = MockRequest()
        ok, msg = _check_telegram_auth(req, API_KEY)
        assert ok is False

    def test_x_api_key_not_accepted_for_telegram(self):
        """关键：Telegram 路径不接受 X-API-Key 替代 secret_token"""
        req = MockRequest(headers={"X-API-Key": API_KEY})
        ok, msg = _check_telegram_auth(req, API_KEY)
        assert ok is False
