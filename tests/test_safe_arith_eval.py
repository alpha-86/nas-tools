import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from app.helper.words_helper import safe_arith_eval


def test_safe_arith_eval_basic():
    assert safe_arith_eval("5+1") == 6
    assert safe_arith_eval("10-2") == 8
    assert safe_arith_eval("3*4") == 12
    assert safe_arith_eval("-5") == -5
    assert safe_arith_eval("10//3") == 3


def test_safe_arith_eval_ep_context():
    """模拟 EP+1/EP-2 场景（EP 已在前端替换为数字）"""
    assert safe_arith_eval("5+1") == 6   # EP=5, EP+1
    assert safe_arith_eval("10-2") == 8  # EP=10, EP-2
    assert safe_arith_eval("3*3") == 9   # EP=3, EP*3


def test_safe_arith_eval_rejects_import():
    with pytest.raises(ValueError):
        safe_arith_eval('__import__("os").system("id")')


def test_safe_arith_eval_rejects_open():
    with pytest.raises(ValueError):
        safe_arith_eval('open("/etc/passwd")')


def test_safe_arith_eval_rejects_attribute():
    with pytest.raises(ValueError):
        safe_arith_eval('(1).__class__')


def test_safe_arith_eval_rejects_string():
    with pytest.raises(ValueError):
        safe_arith_eval('"hello" + 1')


def test_safe_arith_eval_rejects_list():
    with pytest.raises(ValueError):
        safe_arith_eval('[]')


def test_safe_arith_eval_rejects_dict():
    with pytest.raises(ValueError):
        safe_arith_eval('{}')


def test_safe_arith_eval_rejects_subscript():
    with pytest.raises(ValueError):
        safe_arith_eval('()["__class__"]')
