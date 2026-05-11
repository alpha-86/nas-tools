# -*- coding: utf-8 -*-

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

# 在导入 Config 前设置必要的环境变量
_test_dir = tempfile.mkdtemp(prefix="media_mapping_test_root_")
_test_config = os.path.join(_test_dir, "config.yaml")
if not os.path.exists(_test_config):
    import shutil as _shutil
    _tpl = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    _shutil.copy(_tpl, _test_config)
os.environ.setdefault("NASTOOL_CONFIG", _test_config)

from config import Config


class MediaMappingTest(unittest.TestCase):
    """Config 媒体映射接口单元测试"""

    def setUp(self):
        # 使用临时目录避免污染真实配置
        self._tmpdir = tempfile.mkdtemp(prefix="media_mapping_test_")
        self._mapping_file = os.path.join(self._tmpdir, "media_mapping.yaml")

        # 保存原始状态
        cfg = Config()
        self._orig_get_file = cfg.get_media_mapping_file
        self._orig_mapping = dict(cfg._media_mapping)
        self._orig_mtime = cfg._media_mapping_mtime

        # 替换 get_media_mapping_file 指向临时文件
        cfg.get_media_mapping_file = lambda: self._mapping_file

        # 重置内存状态
        cfg._media_mapping = {}
        cfg._media_mapping_mtime = 0

    def tearDown(self):
        # 恢复原始状态
        cfg = Config()
        cfg.get_media_mapping_file = self._orig_get_file
        cfg._media_mapping = self._orig_mapping
        cfg._media_mapping_mtime = self._orig_mtime

        # 清理临时目录
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_normalize_media_mapping_key(self):
        cfg = Config()
        # 空值返回原值
        self.assertEqual(cfg.normalize_media_mapping_key(""), "")
        self.assertIsNone(cfg.normalize_media_mapping_key(None))
        # 空格转下划线 + 小写
        self.assertEqual(cfg.normalize_media_mapping_key("The Long Season"), "the_long_season")
        self.assertEqual(cfg.normalize_media_mapping_key("Climax"), "climax")
        self.assertEqual(cfg.normalize_media_mapping_key("漫长的季节"), "漫长的季节")

    def test_get_media_mapping_key_normalization(self):
        """get_media_mapping 应当通过规范化 key 命中"""
        cfg = Config()
        # 用未规范化的 key 保存
        result = cfg.set_media_mapping("The Long Season", {"title": "漫长的季节"})
        self.assertTrue(result)
        # 用不同大小写/空格风格的名称都应命中
        self.assertEqual(cfg.get_media_mapping("The Long Season"), {"title": "漫长的季节"})
        self.assertEqual(cfg.get_media_mapping("the long season"), {"title": "漫长的季节"})
        self.assertEqual(cfg.get_media_mapping("THE LONG SEASON"), {"title": "漫长的季节"})
        self.assertEqual(cfg.get_media_mapping("the_long_season"), {"title": "漫长的季节"})

    def test_save_title_only(self):
        """只保存 title 应成功"""
        cfg = Config()
        result = cfg.set_media_mapping("the_long_season", {"title": "漫长的季节"})
        self.assertTrue(result)
        mapping = cfg.get_media_mapping("the_long_season")
        self.assertEqual(mapping, {"title": "漫长的季节"})
        # 落盘后不应包含空值字段
        self.assertNotIn("type", mapping)
        self.assertNotIn("tmdbid", mapping)

    def test_save_title_and_type(self):
        """保存 title + type 应成功"""
        cfg = Config()
        result = cfg.set_media_mapping("test_movie", {"title": "测试电影", "type": "movie"})
        self.assertTrue(result)
        mapping = cfg.get_media_mapping("test_movie")
        self.assertEqual(mapping, {"title": "测试电影", "type": "movie"})

    def test_save_tmdbid_and_type(self):
        """保存 tmdbid + type 应成功，tmdbid 统一为 int"""
        cfg = Config()
        # string tmdbid
        result = cfg.set_media_mapping("climax", {"title": "Climax", "type": "tv", "tmdbid": "241860"})
        self.assertTrue(result)
        mapping = cfg.get_media_mapping("climax")
        self.assertEqual(mapping["title"], "Climax")
        self.assertEqual(mapping["type"], "tv")
        self.assertEqual(mapping["tmdbid"], 241860)
        self.assertIsInstance(mapping["tmdbid"], int)

        # int tmdbid
        result = cfg.set_media_mapping("climax2", {"type": "tv", "tmdbid": 241861})
        self.assertTrue(result)
        mapping = cfg.get_media_mapping("climax2")
        self.assertEqual(mapping["tmdbid"], 241861)
        self.assertIsInstance(mapping["tmdbid"], int)

    def test_save_tmdbid_without_type_fails(self):
        """保存 tmdbid 但缺 type 应失败"""
        cfg = Config()
        result = cfg.set_media_mapping("climax", {"title": "Climax", "tmdbid": "241860"})
        self.assertFalse(result)
        # 失败后不应有数据写入
        self.assertIsNone(cfg.get_media_mapping("climax"))

    def test_save_empty_title_and_tmdbid_fails(self):
        """同时空 title 和空 tmdbid 应失败"""
        cfg = Config()
        result = cfg.set_media_mapping("key", {"title": "", "tmdbid": ""})
        self.assertFalse(result)
        result = cfg.set_media_mapping("key", {"type": "tv"})
        self.assertFalse(result)
        result = cfg.set_media_mapping("key", {})
        self.assertFalse(result)
        self.assertIsNone(cfg.get_media_mapping("key"))

    def test_save_invalid_type_fails(self):
        """非 movie/tv 的 type 应失败"""
        cfg = Config()
        result = cfg.set_media_mapping("key", {"title": "Test", "type": "anime"})
        self.assertFalse(result)
        self.assertIsNone(cfg.get_media_mapping("key"))

    def test_save_invalid_tmdbid_fails(self):
        """非数字 tmdbid 应失败"""
        cfg = Config()
        result = cfg.set_media_mapping("key", {"title": "Test", "type": "tv", "tmdbid": "abc"})
        self.assertFalse(result)
        self.assertIsNone(cfg.get_media_mapping("key"))

    def test_save_empty_key_fails(self):
        """空 key 应失败"""
        cfg = Config()
        result = cfg.set_media_mapping("", {"title": "Test"})
        self.assertFalse(result)
        result = cfg.set_media_mapping(None, {"title": "Test"})
        self.assertFalse(result)

    def test_delete_mapping(self):
        """删除 mapping 后不应再命中"""
        cfg = Config()
        cfg.set_media_mapping("the_long_season", {"title": "漫长的季节"})
        self.assertIsNotNone(cfg.get_media_mapping("the_long_season"))
        cfg.delete_media_mapping("the_long_season")
        self.assertIsNone(cfg.get_media_mapping("the_long_season"))

    def test_delete_with_key_normalization(self):
        """删除时也按规范化 key"""
        cfg = Config()
        cfg.set_media_mapping("The Long Season", {"title": "漫长的季节"})
        cfg.delete_media_mapping("the long season")
        self.assertIsNone(cfg.get_media_mapping("The Long Season"))

    def test_get_media_mapping_returns_copy(self):
        """get_media_mapping 返回的 dict 应为副本，外部修改不影响内部"""
        cfg = Config()
        cfg.set_media_mapping("climax", {"title": "Climax", "type": "tv", "tmdbid": "241860"})
        mapping = cfg.get_media_mapping("climax")
        mapping["title"] = "Modified"
        # 再次读取应是原始值
        mapping2 = cfg.get_media_mapping("climax")
        self.assertEqual(mapping2["title"], "Climax")

    def test_list_media_mapping(self):
        """list 返回全部或单个映射"""
        cfg = Config()
        cfg.set_media_mapping("climax", {"title": "Climax", "type": "tv", "tmdbid": "241860"})
        cfg.set_media_mapping("the_long_season", {"title": "漫长的季节"})

        all_mappings = cfg.list_media_mapping()
        self.assertEqual(len(all_mappings), 2)
        self.assertIn("climax", all_mappings)
        self.assertIn("the_long_season", all_mappings)
        # tmdbid 应为 int
        self.assertEqual(all_mappings["climax"]["tmdbid"], 241860)

        single = cfg.list_media_mapping("Climax")
        self.assertEqual(len(single), 1)
        self.assertEqual(single["climax"]["title"], "Climax")

        # 不存在时返回空 dict
        empty = cfg.list_media_mapping("not_exist")
        self.assertEqual(empty, {})

    def test_tmdbid_int_in_yaml(self):
        """YAML 中 tmdbid 写 int 也应工作"""
        cfg = Config()
        # 写入 YAML
        import ruamel.yaml
        with open(self._mapping_file, mode='w', encoding='utf-8') as sf:
            ruamel.yaml.YAML().dump({
                "climax": {"title": "Climax", "type": "tv", "tmdbid": 241860}
            }, sf)
        # 强制重新加载
        cfg._media_mapping = {}
        cfg._media_mapping_mtime = 0
        mapping = cfg.get_media_mapping("climax")
        self.assertEqual(mapping["tmdbid"], 241860)
        self.assertIsInstance(mapping["tmdbid"], int)

    def test_tmdbid_string_in_yaml(self):
        """YAML 中 tmdbid 写 string 时运行时统一转为 int"""
        cfg = Config()
        import ruamel.yaml
        with open(self._mapping_file, mode='w', encoding='utf-8') as sf:
            ruamel.yaml.YAML().dump({
                "climax": {"title": "Climax", "type": "tv", "tmdbid": "241860"}
            }, sf)
        cfg._media_mapping = {}
        cfg._media_mapping_mtime = 0
        mapping = cfg.get_media_mapping("climax")
        self.assertEqual(mapping["tmdbid"], 241860)
        self.assertIsInstance(mapping["tmdbid"], int)

    def test_check_and_reload_on_file_removal(self):
        """文件被删除时内存映射应清空"""
        cfg = Config()
        cfg.set_media_mapping("climax", {"title": "Climax", "type": "tv", "tmdbid": "241860"})
        self.assertIsNotNone(cfg.get_media_mapping("climax"))
        # 删除文件
        os.remove(self._mapping_file)
        # 下次访问应清空
        self.assertIsNone(cfg.get_media_mapping("climax"))

    def test_get_media_mapping_empty_name(self):
        """空 name 返回 None"""
        cfg = Config()
        self.assertIsNone(cfg.get_media_mapping(""))
        self.assertIsNone(cfg.get_media_mapping(None))


if __name__ == '__main__':
    unittest.main()
