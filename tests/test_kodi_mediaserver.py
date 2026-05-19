"""
Kodi MySQL 媒体服务器客户端单元测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import MagicMock, patch


class MockCursor:
    """Mock PyMySQL cursor for testing, supports multiple query results sequentially"""
    def __init__(self, query_results_list=None):
        self._query_results = query_results_list or [[]]
        self._query_index = -1
        self._row_index = 0
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._row_index = 0
        self._query_index = min(self._query_index + 1, len(self._query_results) - 1)

    def fetchone(self):
        current = self._query_results[self._query_index]
        if self._row_index < len(current):
            result = current[self._row_index]
            self._row_index += 1
            return result
        return None

    def fetchall(self):
        current = self._query_results[self._query_index]
        return current

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockConnection:
    """Mock PyMySQL connection for testing"""
    def __init__(self, query_results_list=None):
        self._query_results = query_results_list or [[]]

    def cursor(self):
        return MockCursor(self._query_results)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def make_kodi(mock_config_dict):
    """Helper: create a Kodi instance with mocked config"""
    with patch('app.mediaserver.client.kodi.Config') as MockConfig:
        MockConfig.return_value.get_config.return_value = mock_config_dict
        from app.mediaserver.client.kodi import Kodi
        return Kodi()


class TestKodiClient:
    """Kodi 客户端单元测试"""

    def test_match(self):
        from app.mediaserver.client.kodi import Kodi
        assert Kodi.match("kodi")
        assert Kodi.match("Kodi")
        assert not Kodi.match("emby")
        assert not Kodi.match("plex")

    def test_get_type(self):
        from app.utils.types import MediaServerType
        from app.mediaserver.client.kodi import Kodi
        kodi = make_kodi({})
        assert kodi.get_type() == MediaServerType.KODI

    def test_parse_item_id(self):
        from app.mediaserver.client.kodi import Kodi
        assert Kodi._Kodi__parse_item_id("movie:1") == ("movie", 1)
        assert Kodi._Kodi__parse_item_id("tvshow:42") == ("tvshow", 42)
        assert Kodi._Kodi__parse_item_id("123") == (None, 123)
        assert Kodi._Kodi__parse_item_id(None) == (None, None)
        assert Kodi._Kodi__parse_item_id("") == (None, None)
        assert Kodi._Kodi__parse_item_id("invalid") == (None, None)

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_status_success(self, mock_connect):
        mock_conn = MockConnection([[{'1': 1}]])
        mock_connect.return_value = mock_conn
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        assert kodi.get_status() is True
        mock_connect.assert_called_once()

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_status_failure(self, mock_connect):
        mock_connect.side_effect = Exception("Connection refused")
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        assert kodi.get_status() is False

    def test_get_user_count(self):
        kodi = make_kodi({})
        assert kodi.get_user_count() == 1

    def test_unsupported_methods(self):
        kodi = make_kodi({})
        assert kodi.get_activity_log(10) == []
        assert kodi.get_playing_sessions() == []
        assert kodi.get_webhook_message({}) is None
        assert kodi.refresh_root_library() is False
        assert kodi.refresh_library_by_items([]) is None
        assert kodi.get_play_url("movie:1") == ""
        assert kodi.get_resume() == []
        assert kodi.get_latest() == []

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_medias_count(self, mock_connect):
        mock_conn = MockConnection([
            [{'cnt': 100}],
            [{'cnt': 50}]
        ])
        mock_connect.return_value = mock_conn
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        result = kodi.get_medias_count()
        assert result == {"MovieCount": 100, "SeriesCount": 50, "SongCount": 0}

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_movies_found(self, mock_connect):
        mock_conn = MockConnection([
            [{'title': 'Test Movie', 'premiered': '2023-01-01'}]
        ])
        mock_connect.return_value = mock_conn
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        result = kodi.get_movies('Test Movie', 2023)
        assert result == [{'title': 'Test Movie', 'year': '2023'}]

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_movies_not_found(self, mock_connect):
        mock_conn = MockConnection([[]])
        mock_connect.return_value = mock_conn
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        result = kodi.get_movies('Nonexistent')
        assert result == []

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_tv_episodes_by_item_id(self, mock_connect):
        mock_conn = MockConnection([
            [{'season_num': 1, 'episode_num': 1},
             {'season_num': 1, 'episode_num': 2},
             {'season_num': 1, 'episode_num': 3}]
        ])
        mock_connect.return_value = mock_conn
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        result = kodi.get_tv_episodes(item_id="tvshow:1", season=1)
        assert len(result) == 3
        assert result[0]['episode_num'] == 1

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_libraries(self, mock_connect):
        mock_conn = MockConnection([
            # First query: movie paths
            [{'idPath': 1, 'strPath': '/movies', 'media_type': 'movie'}],
            # Second query: tv paths
            [{'idPath': 2, 'strPath': '/tvshows', 'media_type': 'tv'}]
        ])
        mock_connect.return_value = mock_conn
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        result = kodi.get_libraries()
        assert len(result) == 2
        names = {lib['name'] for lib in result}
        assert names == {'movies', 'tvshows'}

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_items_movies(self, mock_connect):
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        mock_conn = MockConnection([
            # movie query
            [{'idMovie': 1, 'title': 'Test Movie', 'premiered': '2023-01-01',
              'original_title': 'Original', 'strPath': '/movies', 'strFilename': 'test.mkv'}],
            # tvshow query (empty)
            []
        ])
        mock_connect.return_value = mock_conn
        items = list(kodi.get_items(parent=1))
        items = [i for i in items if i]
        assert len(items) >= 1
        assert items[0]['type'] == 'Movie'
        assert items[0]['id'] == 'movie:1'

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_items_tvshows(self, mock_connect):
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        mock_conn = MockConnection([
            # movie query (empty)
            [],
            # tvshow query
            [{'idShow': 1, 'title': 'Test Show', 'premiered': '2023-01-01', 'original_title': 'Original'}]
        ])
        mock_connect.return_value = mock_conn
        items = list(kodi.get_items(parent=2))
        items = [i for i in items if i]
        assert len(items) >= 1
        assert items[0]['type'] == 'Series'
        assert items[0]['id'] == 'tvshow:1'

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_iteminfo_movie(self, mock_connect):
        mock_conn = MockConnection([
            [{'idMovie': 1, 'title': 'Test Movie', 'premiered': '2023-01-01', 'original_title': 'Original'}]
        ])
        mock_connect.return_value = mock_conn
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        result = kodi.get_iteminfo("movie:1")
        assert result['title'] == 'Test Movie'
        assert result['year'] == '2023'

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_iteminfo_tvshow(self, mock_connect):
        mock_conn = MockConnection([
            [{'idShow': 1, 'title': 'Test Show', 'premiered': '2023-01-01', 'original_title': 'Original'}]
        ])
        mock_connect.return_value = mock_conn
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        result = kodi.get_iteminfo("tvshow:1")
        assert result['title'] == 'Test Show'

    def test_get_iteminfo_invalid(self):
        kodi = make_kodi({})
        assert kodi.get_iteminfo("") == {}
        assert kodi.get_iteminfo(None) == {}
        assert kodi.get_iteminfo("invalid") == {}

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_no_exists_episodes(self, mock_connect):
        mock_conn = MockConnection([
            # First query: find show
            [{'idShow': 1, 'title': 'Test Show', 'premiered': '2023-01-01'}],
            # Second query: episodes
            [{'season_num': 1, 'episode_num': 1},
             {'season_num': 1, 'episode_num': 3}]
        ])
        mock_connect.return_value = mock_conn
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })

        class MockMetaInfo:
            title = 'Test Show'
            year = 2023
            tmdb_id = 12345

        result = kodi.get_no_exists_episodes(MockMetaInfo(), season=1, total_num=5)
        assert result == [2, 4, 5]
