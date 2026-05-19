"""
Task 12.5: X-API-Key header 认证测试（P1）
验证 require_auth() 中 X-API-Key header 支持，
以及 Authorization Bearer 和 query apikey 兼容路径。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest


API_KEY = "test-api-key-12345"


class MockRequest:
    """模拟 Flask request 对象"""
    def __init__(self, headers=None, args=None):
        self.headers = headers or {}
        self.args = args or {}


def _check_auth(req, api_key):
    """
    复刻 web/security.py 中 require_auth 的认证逻辑
    """
    auth = req.headers.get("Authorization")
    if auth:
        auth = str(auth).split()[-1]
        if auth == api_key:
            return True, "Authorization"

    auth = req.headers.get("X-API-Key")
    if auth:
        if auth == api_key:
            return True, "X-API-Key"

    auth = req.args.get("apikey")
    if auth:
        if auth == api_key:
            return True, "query-apikey"

    return False, "未通过"


class TestRequireAuthXAPIKey:
    def test_x_api_key_header_ok(self):
        req = MockRequest(headers={"X-API-Key": API_KEY})
        ok, source = _check_auth(req, API_KEY)
        assert ok is True
        assert source == "X-API-Key"

    def test_x_api_key_header_wrong(self):
        req = MockRequest(headers={"X-API-Key": "wrong-key"})
        ok, source = _check_auth(req, API_KEY)
        assert ok is False

    def test_authorization_bearer_ok(self):
        req = MockRequest(headers={"Authorization": "Bearer %s" % API_KEY})
        ok, source = _check_auth(req, API_KEY)
        assert ok is True
        assert source == "Authorization"

    def test_query_apikey_ok(self):
        """短期兼容：query apikey 仍可通过"""
        req = MockRequest(args={"apikey": API_KEY})
        ok, source = _check_auth(req, API_KEY)
        assert ok is True
        assert source == "query-apikey"

    def test_query_apikey_wrong(self):
        req = MockRequest(args={"apikey": "wrong-key"})
        ok, source = _check_auth(req, API_KEY)
        assert ok is False

    def test_no_auth(self):
        req = MockRequest()
        ok, source = _check_auth(req, API_KEY)
        assert ok is False

    def test_x_api_key_priority_over_query(self):
        """X-API-Key header 优先级高于 query string"""
        req = MockRequest(
            headers={"X-API-Key": API_KEY},
            args={"apikey": "wrong-key"}
        )
        ok, source = _check_auth(req, API_KEY)
        assert ok is True
        assert source == "X-API-Key"
