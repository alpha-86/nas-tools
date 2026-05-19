"""
Kodi MySQL 媒体服务器客户端单元测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('NASTOOL_CONFIG', os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml'))

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
    def test_get_tv_episodes_tmdbid_param(self, mock_connect):
        """验证 tmdbid 关键字参数不会抛 TypeError，且旧的 tmdb_id 仍兼容"""
        # 使用 side_effect 让主连接和 __get_tmdb_id 使用不同的 MockConnection
        mock_connect.side_effect = [
            # 主连接：episode 查询
            MockConnection([
                [{'season_num': 1, 'episode_num': 1}]
            ]),
            # __get_tmdb_id 连接：uniqueid 查询
            MockConnection([
                [{'value': '12345'}]
            ]),
            # 向后兼容测试：同样结构
            MockConnection([
                [{'season_num': 1, 'episode_num': 1}]
            ]),
            MockConnection([
                [{'value': '12345'}]
            ]),
        ]
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        # 新的 tmdbid 参数
        result = kodi.get_tv_episodes(item_id="tvshow:1", tmdbid=12345, season=1)
        assert isinstance(result, list)
        assert result[0]['episode_num'] == 1
        # 旧的 tmdb_id 参数（向后兼容）
        result2 = kodi.get_tv_episodes(item_id="tvshow:1", tmdb_id=12345, season=1)
        assert isinstance(result2, list)
        assert result2[0]['episode_num'] == 1

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
            # movie query with LEFT JOIN uniqueid
            [{'idMovie': 1, 'title': 'Test Movie', 'premiered': '2023-01-01',
              'original_title': 'Original', 'strPath': '/movies', 'strFilename': 'test.mkv',
              'tmdbid': '999', 'imdbid': 'tt123'}],
            # tvshow query (empty)
            []
        ])
        mock_connect.return_value = mock_conn
        items = list(kodi.get_items(parent=1))
        items = [i for i in items if i]
        assert len(items) >= 1
        assert items[0]['type'] == 'Movie'
        assert items[0]['id'] == 'movie:1'
        assert items[0]['tmdbid'] == '999'
        assert items[0]['imdbid'] == 'tt123'

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
            # tvshow query with LEFT JOIN uniqueid
            [{'idShow': 1, 'title': 'Test Show', 'premiered': '2023-01-01',
              'original_title': 'Original', 'tmdbid': '888', 'imdbid': 'tt456'}]
        ])
        mock_connect.return_value = mock_conn
        items = list(kodi.get_items(parent=2))
        items = [i for i in items if i]
        assert len(items) >= 1
        assert items[0]['type'] == 'Series'
        assert items[0]['id'] == 'tvshow:1'
        assert items[0]['tmdbid'] == '888'
        assert items[0]['imdbid'] == 'tt456'

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    def test_get_items_no_extra_connects(self, mock_connect):
        """验证 get_items 不会为每条 item 额外调用 pymysql.connect"""
        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        mock_conn = MockConnection([
            # movie query returns 3 movies
            [
                {'idMovie': 1, 'title': 'M1', 'premiered': '2020-01-01',
                 'original_title': 'O1', 'strPath': '/m', 'strFilename': '1.mkv',
                 'tmdbid': '1', 'imdbid': 'tt1'},
                {'idMovie': 2, 'title': 'M2', 'premiered': '2021-01-01',
                 'original_title': 'O2', 'strPath': '/m', 'strFilename': '2.mkv',
                 'tmdbid': '2', 'imdbid': 'tt2'},
                {'idMovie': 3, 'title': 'M3', 'premiered': '2022-01-01',
                 'original_title': 'O3', 'strPath': '/m', 'strFilename': '3.mkv',
                 'tmdbid': '3', 'imdbid': 'tt3'},
            ],
            # tvshow query returns 2 shows
            [
                {'idShow': 10, 'title': 'S1', 'premiered': '2020-01-01',
                 'original_title': 'OS1', 'tmdbid': '10', 'imdbid': 'tt10'},
                {'idShow': 11, 'title': 'S2', 'premiered': '2021-01-01',
                 'original_title': 'OS2', 'tmdbid': '11', 'imdbid': 'tt11'},
            ]
        ])
        mock_connect.return_value = mock_conn
        items = list(kodi.get_items(parent=1))
        items = [i for i in items if i]
        assert len(items) == 5  # 3 movies + 2 shows
        # 整个 get_items 只应建立 1 次连接（_get_connection 调用 1 次）
        assert mock_connect.call_count == 1

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
    @patch('app.mediaserver.client.kodi.Media')
    @patch('app.mediaserver.client.kodi.Config')
    def test_get_local_image_by_id_primary_is_poster(self, mock_config_cls, mock_media_cls, mock_connect):
        """get_local_image_by_id('movie:1') 应调用 get_tmdb_info 返回 poster URL，而非 get_tmdb_backdrop"""
        # Setup MySQL mock: return a tmdbid
        mock_conn = MockConnection([
            [{'value': '99999'}]
        ])
        mock_connect.return_value = mock_conn

        # Setup Media mock
        mock_media = MagicMock()
        mock_media.get_tmdb_info.return_value = {'poster_path': '/poster.jpg'}
        mock_media_cls.return_value = mock_media

        # Setup Config mock
        mock_config = MagicMock()
        mock_config.get_tmdbimage_url.return_value = 'https://image.tmdb.org/t/p/w500/poster.jpg'
        mock_config_cls.return_value = mock_config

        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        result = kodi.get_local_image_by_id("movie:1")
        assert result == 'https://image.tmdb.org/t/p/w500/poster.jpg'
        mock_media.get_tmdb_info.assert_called_once()
        mock_media.get_tmdb_backdrop.assert_not_called()

    @patch('app.mediaserver.client.kodi.pymysql.connect')
    @patch('app.mediaserver.client.kodi.Media')
    @patch('app.mediaserver.client.kodi.Config')
    def test_get_remote_image_backdrop(self, mock_config_cls, mock_media_cls, mock_connect):
        """get_remote_image_by_id with Backdrop should call get_tmdb_backdrop"""
        mock_conn = MockConnection([
            [{'value': '99999'}]
        ])
        mock_connect.return_value = mock_conn

        mock_media = MagicMock()
        mock_media.get_tmdb_backdrop.return_value = 'https://image.tmdb.org/t/p/original/backdrop.jpg'
        mock_media_cls.return_value = mock_media

        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config

        kodi = make_kodi({
            'mysql_host': '127.0.0.1',
            'mysql_port': '3306',
            'mysql_user': 'kodi',
            'mysql_password': 'pass',
            'mysql_db': 'MyVideos119'
        })
        result = kodi.get_remote_image_by_id("movie:1", "Backdrop")
        assert result == 'https://image.tmdb.org/t/p/original/backdrop.jpg'
        mock_media.get_tmdb_backdrop.assert_called_once()
        mock_media.get_tmdb_info.assert_not_called()

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
