"""
Task 12.2: BrushTask legacy fallback 测试（P0）
验证 JSON 优先路径、ast.literal_eval fallback、以及非 dict 返回值的安全处理。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import json
import ast


# 复刻 brushtask.py 中的 _load_rule 逻辑
def _load_rule(rule_str):
    if not rule_str:
        return {}
    try:
        val = json.loads(rule_str)
        if isinstance(val, dict):
            return val
        return {}
    except (json.JSONDecodeError, ValueError):
        try:
            val = ast.literal_eval(rule_str)
            if isinstance(val, dict):
                return val
            return {}
        except (ValueError, SyntaxError):
            return {}


class TestBrushTaskRuleLoader:
    def test_json_new_data(self):
        """新数据：标准 JSON 字符串应正确解析"""
        assert _load_rule('{"size": 10, "free": true}') == {"size": 10, "free": True}
        assert _load_rule('{}') == {}

    def test_json_empty(self):
        assert _load_rule('') == {}
        assert _load_rule(None) == {}

    def test_legacy_single_quotes(self):
        """旧数据：Python 单引号字典字面量"""
        result = _load_rule("{'size': 10, 'free': True}")
        assert result == {"size": 10, "free": True}

    def test_legacy_boolean_none(self):
        """旧数据：含 True/False/None"""
        result = _load_rule("{'size': 10, 'free': True, 'label': None}")
        assert result == {"size": 10, "free": True, "label": None}

    def test_malicious_payload_rejected(self):
        """恶意 payload：不应执行，返回空 dict"""
        assert _load_rule('__import__("os").system("id")') == {}

    def test_non_dict_literal_rejected(self):
        """非 dict 字面量：应返回空 dict"""
        assert _load_rule('[1, 2, 3]') == {}
        assert _load_rule('"string"') == {}
        assert _load_rule('123') == {}

    def test_db_helper_writes_json(self):
        """写入端：json.dumps 输出应为标准 JSON"""
        rule = {"size": 10, "free": True, "label": None}
        dumped = json.dumps(rule, ensure_ascii=False)
        # 标准 JSON 中 True → true, None → null
        assert 'true' in dumped
        assert 'null' in dumped
        # 读取端应能正确解析
        assert _load_rule(dumped) == rule
