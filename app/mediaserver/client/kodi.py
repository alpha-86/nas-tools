import os

import pymysql
from cachetools import TTLCache, cached

import log
from app.mediaserver.client._base import _IMediaClient
from app.media import Media
from app.utils import ExceptionUtils
from app.utils.types import MediaType, MediaServerType
from config import Config


class Kodi(_IMediaClient):
    # 媒体服务器ID
    client_id = "kodi"
    # 媒体服务器类型
    client_type = MediaServerType.KODI
    # 媒体服务器名称
    client_name = MediaServerType.KODI.value

    # 私有属性
    _client_config = {}
    _dbhost = None
    _dbport = 3306
    _dbuser = None
    _dbpassword = None
    _dbname = None

    # 类级别缓存（TTL 300s）用于首页实时数据，避免每次刷新都查 MySQL
    _cache = TTLCache(maxsize=16, ttl=300)

    @staticmethod
    def _cache_key(method, *args, **kwargs):
        return f"{method}:{args}:{sorted(kwargs.items())}"

    def __init__(self, config=None):
        if config:
            self._client_config = config
        else:
            self._client_config = Config().get_config('kodi')
        self.init_config()

    def init_config(self):
        if self._client_config:
            self._dbhost = self._client_config.get('mysql_host')
            try:
                self._dbport = int(self._client_config.get('mysql_port', 3306))
            except (ValueError, TypeError):
                self._dbport = 3306
            self._dbuser = self._client_config.get('mysql_user')
            self._dbpassword = self._client_config.get('mysql_password')
            self._dbname = self._client_config.get('mysql_db')

    @classmethod
    def match(cls, ctype):
        return True if ctype in [cls.client_id, cls.client_type, cls.client_name] else False

    def get_type(self):
        return self.client_type

    def _get_connection(self):
        """
        获取MySQL连接
        """
        if not self._dbhost or not self._dbuser or not self._dbname:
            return None
        try:
            return pymysql.connect(
                host=self._dbhost,
                port=self._dbport,
                user=self._dbuser,
                password=self._dbpassword,
                database=self._dbname,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5
            )
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】连接MySQL失败：{str(e)}")
            return None

    def get_status(self):
        """
        测试连通性
        """
        conn = self._get_connection()
        if not conn:
            return False
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                return True
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】MySQL连通性测试失败：{str(e)}")
            return False
        finally:
            conn.close()

    def get_user_count(self):
        """
        获得用户数量
        Kodi无用户系统，固定返回1
        """
        return 1

    def get_activity_log(self, num):
        """
        获取活动记录
        优先从本地 SQLite 缓存查询，无数据时回退到 MySQL
        """
        cache_key = f"activity:{num}"
        if cache_key in Kodi._cache:
            return list(Kodi._cache[cache_key])
        try:
            from app.db import MediaDb
            items = MediaDb().get_activity_items(self.client_id, num)
            if items:
                ret_array = []
                for item in items:
                    ret_array.append({
                        "type": "PL",
                        "event": item.TITLE or "",
                        "date": item.LAST_PLAYED or ""
                    })
                Kodi._cache[cache_key] = ret_array
                return ret_array
        except Exception:
            pass
        # 回退到 MySQL 查询
        conn = self._get_connection()
        if not conn:
            return []
        try:
            with conn.cursor() as cursor:
                ret_array = []
                cursor.execute(
                    "SELECT m.c00 AS title, f.lastPlayed "
                    "FROM movie m JOIN files f ON m.idFile = f.idFile "
                    "WHERE f.lastPlayed IS NOT NULL AND f.lastPlayed != '' "
                    "ORDER BY f.lastPlayed DESC "
                    "LIMIT %s",
                    (num,)
                )
                for row in cursor.fetchall():
                    ret_array.append({"type": "PL", "event": row['title'], "date": row['lastPlayed']})
                cursor.execute(
                    "SELECT e.c00 AS title, t.c00 AS show_title, f.lastPlayed "
                    "FROM episode e JOIN files f ON e.idFile = f.idFile "
                    "JOIN tvshow t ON e.idShow = t.idShow "
                    "WHERE f.lastPlayed IS NOT NULL AND f.lastPlayed != '' "
                    "ORDER BY f.lastPlayed DESC "
                    "LIMIT %s",
                    (num,)
                )
                for row in cursor.fetchall():
                    title = f"{row['show_title']} - {row['title']}" if row['show_title'] else row['title']
                    ret_array.append({"type": "PL", "event": title, "date": row['lastPlayed']})
                ret_array.sort(key=lambda x: x['date'], reverse=True)
                result = ret_array[:num]
                Kodi._cache[cache_key] = result
                return result
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】获取活动记录失败：{str(e)}")
            return []
        finally:
            conn.close()

    def get_medias_count(self):
        """
        获得电影、电视剧媒体数量
        :return: MovieCount SeriesCount SongCount
        """
        conn = self._get_connection()
        if not conn:
            return {}
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM movie")
                movie_count = cursor.fetchone().get('cnt', 0)
                cursor.execute("SELECT COUNT(*) AS cnt FROM tvshow")
                tv_count = cursor.fetchone().get('cnt', 0)
                return {
                    "MovieCount": movie_count,
                    "SeriesCount": tv_count,
                    "SongCount": 0
                }
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】获取媒体数量失败：{str(e)}")
            return {}
        finally:
            conn.close()

    @staticmethod
    def __parse_item_id(item_id):
        """
        解析带命名空间前缀的item_id
        :param item_id: 如 "movie:1" 或 "tvshow:1"
        :return: (media_type, raw_id) 如 ("movie", 1) 或 ("tvshow", 1)
        """
        if not item_id:
            return None, None
        if isinstance(item_id, str) and ':' in item_id:
            parts = item_id.split(':', 1)
            try:
                return parts[0], int(parts[1])
            except (ValueError, IndexError):
                return None, None
        try:
            return None, int(item_id)
        except (ValueError, TypeError):
            return None, None

    def __get_tmdb_id(self, media_id, media_type):
        """
        从uniqueid表查询TMDB ID
        """
        conn = self._get_connection()
        if not conn:
            return None
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT value FROM uniqueid WHERE media_id = %s AND media_type = %s AND type = 'tmdb' LIMIT 1",
                    (media_id, media_type)
                )
                result = cursor.fetchone()
                return result.get('value') if result else None
        except Exception:
            return None
        finally:
            conn.close()

    def __get_imdb_id(self, media_id, media_type):
        """
        从uniqueid表查询IMDB ID
        """
        conn = self._get_connection()
        if not conn:
            return None
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT value FROM uniqueid WHERE media_id = %s AND media_type = %s AND type = 'imdb' LIMIT 1",
                    (media_id, media_type)
                )
                result = cursor.fetchone()
                return result.get('value') if result else None
        except Exception:
            return None
        finally:
            conn.close()

    def get_movies(self, title, year=None):
        """
        根据标题和年份，检查电影是否存在，存在则返回列表
        :param title: 标题
        :param year: 年份，可以为空
        :return: 含title、year属性的字典列表
        """
        conn = self._get_connection()
        if not conn:
            return None
        try:
            with conn.cursor() as cursor:
                sql = "SELECT c00 AS title, premiered FROM movie WHERE c00 = %s"
                params = [title]
                if year:
                    sql += " AND premiered LIKE %s"
                    params.append(f"{year}%")
                cursor.execute(sql, params)
                results = cursor.fetchall()
                if results:
                    return [{'title': r['title'], 'year': str(r['premiered'][:4]) if r['premiered'] else ''}
                            for r in results]
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】查询电影失败：{str(e)}")
            return None
        finally:
            conn.close()
        return []

    def get_tv_episodes(self,
                        item_id=None,
                        title=None,
                        year=None,
                        tmdbid=None,
                        season=None,
                        **kwargs):
        """
        根据标题和年份和季，返回剧集列表
        :param item_id: 媒体源ID（带前缀如 tvshow:1）
        :param title: 标题
        :param year: 年份
        :param tmdbid: TMDBID
        :param season: 季
        :return: 集号的列表
        """
        # 向后兼容：旧的 tmdb_id 参数
        if tmdbid is None and 'tmdb_id' in kwargs:
            tmdbid = kwargs['tmdb_id']
        conn = self._get_connection()
        if not conn:
            return None
        try:
            with conn.cursor() as cursor:
                show_id = None
                if item_id:
                    media_type, raw_id = self.__parse_item_id(item_id)
                    if media_type == 'tvshow':
                        show_id = raw_id
                else:
                    # 通过标题和年份查找show_id
                    sql = "SELECT idShow, c00 AS title, c05 AS premiered FROM tvshow WHERE c00 = %s"
                    params = [title]
                    if year:
                        sql += " AND c05 LIKE %s"
                        params.append(f"{year}%")
                    cursor.execute(sql, params)
                    result = cursor.fetchone()
                    if result:
                        show_id = result['idShow']

                if not show_id:
                    return []

                # 验证tmdbid是否相同
                if tmdbid:
                    item_tmdbid = self.__get_tmdb_id(show_id, 'tvshow')
                    if item_tmdbid and str(tmdbid) != str(item_tmdbid):
                        return []

                # 查询集信息
                sql = "SELECT c12 AS season_num, c13 AS episode_num FROM episode WHERE idShow = %s"
                params = [show_id]
                if season:
                    sql += " AND c12 = %s"
                    params.append(str(season))
                cursor.execute(sql, params)
                results = cursor.fetchall()
                return [{'season_num': int(r['season_num'] or 0), 'episode_num': int(r['episode_num'] or 0)}
                        for r in results]
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】查询剧集失败：{str(e)}")
            return None
        finally:
            conn.close()

    def get_no_exists_episodes(self, meta_info, season, total_num):
        """
        根据标题、年份、季、总集数，查询缺少哪几集
        :param meta_info: 已识别的需要查询的媒体信息
        :param season: 季号
        :param total_num: 该季的总集数
        :return: 该季不存在的集号列表
        """
        if not season:
            season = 1
        exists_episodes = self.get_tv_episodes(title=meta_info.title,
                                               year=meta_info.year,
                                               tmdbid=meta_info.tmdb_id,
                                               season=season)
        if not isinstance(exists_episodes, list):
            return None
        exists_episodes = [episode.get("episode_num") for episode in exists_episodes]
        total_episodes = [episode for episode in range(1, total_num + 1)]
        return list(set(total_episodes).difference(set(exists_episodes)))

    def get_libraries(self):
        """
        获取媒体服务器所有媒体库列表
        Kodi 按视频类型分为电影和剧集两个库
        """
        return [
            {
                'id': 'movies',
                'name': '电影',
                'path': '',
                'type': MediaType.MOVIE.value,
                'image': '',
                'link': '',
                'navpage': 'library_browse?library=movies&name=电影'
            },
            {
                'id': 'tvshows',
                'name': '剧集',
                'path': '',
                'type': MediaType.TV.value,
                'image': '',
                'link': '',
                'navpage': 'library_browse?library=tvshows&name=剧集'
            }
        ]

    def get_items(self, parent):
        """
        获取媒体库中的所有媒体
        :param parent: 'movies' 或 'tvshows'
        """
        if not parent:
            yield {}
        conn = self._get_connection()
        if not conn:
            yield {}
        try:
            with conn.cursor() as cursor:
                if parent == 'movies':
                    cursor.execute(
                        "SELECT m.idMovie, m.c00 AS title, m.premiered, m.c16 AS original_title, "
                        "p.strPath, f.strFilename, "
                        "MAX(CASE WHEN u.type = 'tmdb' THEN u.value END) AS tmdbid, "
                        "MAX(CASE WHEN u.type = 'imdb' THEN u.value END) AS imdbid, "
                        "MAX(CASE WHEN a.type = 'poster' THEN a.url END) AS poster "
                        "FROM movie m JOIN files f ON m.idFile = f.idFile "
                        "JOIN path p ON f.idPath = p.idPath "
                        "LEFT JOIN uniqueid u ON u.media_id = m.idMovie AND u.media_type = 'movie' "
                        "LEFT JOIN art a ON a.media_id = m.idMovie AND a.media_type = 'movie' "
                        "GROUP BY m.idMovie, m.c00, m.premiered, m.c16, p.strPath, f.strFilename"
                    )
                    for movie in cursor.fetchall():
                        path_str = movie['strPath'] or ''
                        filename = movie['strFilename'] or ''
                        full_path = os.path.join(path_str, filename) if filename else path_str
                        year = str(movie['premiered'][:4]) if movie['premiered'] else ''
                        yield {
                            'id': f"movie:{movie['idMovie']}",
                            'library': parent,
                            'type': 'Movie',
                            'title': movie['title'],
                            'originalTitle': movie['original_title'],
                            'year': year,
                            'tmdbid': movie.get('tmdbid'),
                            'imdbid': movie.get('imdbid'),
                            'poster': movie.get('poster'),
                            'path': full_path,
                            'json': str({})
                        }
                elif parent == 'tvshows':
                    cursor.execute(
                        "SELECT t.idShow, t.c00 AS title, t.c05 AS premiered, t.c09 AS original_title, "
                        "MAX(CASE WHEN u.type = 'tmdb' THEN u.value END) AS tmdbid, "
                        "MAX(CASE WHEN u.type = 'imdb' THEN u.value END) AS imdbid, "
                        "MAX(CASE WHEN a.type = 'poster' THEN a.url END) AS poster "
                        "FROM tvshow t "
                        "LEFT JOIN uniqueid u ON u.media_id = t.idShow AND u.media_type = 'tvshow' "
                        "LEFT JOIN art a ON a.media_id = t.idShow AND a.media_type = 'tvshow' "
                        "GROUP BY t.idShow, t.c00, t.c05, t.c09"
                    )
                    for tvshow in cursor.fetchall():
                        year = str(tvshow['premiered'][:4]) if tvshow['premiered'] else ''
                        yield {
                            'id': f"tvshow:{tvshow['idShow']}",
                            'library': parent,
                            'type': 'Series',
                            'title': tvshow['title'],
                            'originalTitle': tvshow['original_title'],
                            'year': year,
                            'tmdbid': tvshow.get('tmdbid'),
                            'imdbid': tvshow.get('imdbid'),
                            'poster': tvshow.get('poster'),
                            'path': '',
                            'json': str({})
                        }
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】获取媒体列表失败：{str(e)}")
        finally:
            conn.close()
        yield {}

    def get_play_url(self, item_id):
        """
        获取媒体播放链接
        返回 nastools 媒体详情页链接（需 TMDB ID）
        """
        media_type, raw_id = self.__parse_item_id(item_id)
        if not raw_id:
            return ""

        if media_type == 'movie':
            mtype = "MOV"
        elif media_type == 'tvshow':
            mtype = "TV"
        else:
            return ""

        tmdbid = self.__get_tmdb_id(raw_id, media_type)
        if not tmdbid:
            return ""

        domain = Config().get_domain()
        if domain:
            return f"{domain}/web#media_detail?id={tmdbid}&type={mtype}"
        return f"/web#media_detail?id={tmdbid}&type={mtype}"

    def get_playing_sessions(self):
        """
        获取正在播放的会话
        不支持
        """
        return []

    def get_webhook_message(self, message):
        """
        解析Webhook报文
        不支持
        """
        return None

    def refresh_root_library(self):
        """
        刷新整个媒体库
        不支持
        """
        return False

    def refresh_library_by_items(self, items):
        """
        按类型、名称、年份来刷新媒体库
        不支持
        """
        return None

    def get_remote_image_by_id(self, item_id, image_type):
        """
        根据ItemId查询远程图片地址
        :param item_id: 在服务器中的ID（带前缀）
        :param image_type: 图片的类型，poster或者backdrop等
        :return: 图片对应在TMDB中的URL
        """
        media_type, raw_id = self.__parse_item_id(item_id)
        if not raw_id:
            return None

        if media_type == 'movie':
            mtype = MediaType.MOVIE
            tmdbid = self.__get_tmdb_id(raw_id, 'movie')
        elif media_type == 'tvshow':
            mtype = MediaType.TV
            tmdbid = self.__get_tmdb_id(raw_id, 'tvshow')
        else:
            return None

        if not tmdbid:
            return None

        try:
            poster_types = {'poster', 'primary'}
            if image_type and image_type.lower() in poster_types:
                tmdb_info = Media().get_tmdb_info(mtype=mtype, tmdbid=tmdbid, chinese=False)
                if tmdb_info and tmdb_info.get('poster_path'):
                    return Config().get_tmdbimage_url(tmdb_info.get('poster_path'), prefix='w500')
                return None
            else:
                # backdrop 或其他类型
                return Media().get_tmdb_backdrop(mtype=mtype, tmdbid=tmdbid)
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return None

    def get_local_image_by_id(self, item_id):
        """
        根据ItemId查询本地图片地址
        Kodi无对外图片服务，行为与get_remote_image_by_id一致
        """
        return self.get_remote_image_by_id(item_id, "Primary")

    def get_episode_image_by_id(self, item_id, season_id, episode_id):
        """
        根据itemid、season_id、episode_id查询图片地址
        :param item_id: 在Kodi中的ID（带前缀如 tvshow:1）
        :param season_id: 季
        :param episode_id: 集
        :return: 图片对应在TMDB中的URL
        """
        media_type, raw_id = self.__parse_item_id(item_id)
        if media_type != 'tvshow' or not raw_id:
            return None

        tmdbid = self.__get_tmdb_id(raw_id, 'tvshow')
        if not tmdbid:
            return None

        try:
            return Media().get_episode_images(tv_id=tmdbid, season_id=season_id, episode_id=episode_id)
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return None

    def get_iteminfo(self, itemid):
        """
        获取单个项目详情
        :param itemid: 在服务器中的ID（带前缀）
        :return: 详情dict
        """
        media_type, raw_id = self.__parse_item_id(itemid)
        if not raw_id:
            return {}

        conn = self._get_connection()
        if not conn:
            return {}
        try:
            with conn.cursor() as cursor:
                if media_type == 'movie':
                    cursor.execute(
                        "SELECT idMovie, c00 AS title, premiered, c16 AS original_title "
                        "FROM movie WHERE idMovie = %s",
                        (raw_id,)
                    )
                    result = cursor.fetchone()
                    if result:
                        return {
                            'id': f"movie:{result['idMovie']}",
                            'title': result['title'],
                            'originalTitle': result['original_title'],
                            'year': str(result['premiered'][:4]) if result['premiered'] else '',
                            'tmdbid': self.__get_tmdb_id(raw_id, 'movie'),
                            'imdbid': self.__get_imdb_id(raw_id, 'movie')
                        }
                elif media_type == 'tvshow':
                    cursor.execute(
                        "SELECT idShow, c00 AS title, c05 AS premiered, c09 AS original_title "
                        "FROM tvshow WHERE idShow = %s",
                        (raw_id,)
                    )
                    result = cursor.fetchone()
                    if result:
                        return {
                            'id': f"tvshow:{result['idShow']}",
                            'title': result['title'],
                            'originalTitle': result['original_title'],
                            'year': str(result['premiered'][:4]) if result['premiered'] else '',
                            'tmdbid': self.__get_tmdb_id(raw_id, 'tvshow'),
                            'imdbid': self.__get_imdb_id(raw_id, 'tvshow')
                        }
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {}
        finally:
            conn.close()
        return {}

    def get_resume(self, num=12):
        """
        获得继续观看
        优先从本地 SQLite 缓存查询，无数据时回退到 MySQL bookmark 表
        """
        cache_key = f"resume:{num}"
        if cache_key in Kodi._cache:
            return list(Kodi._cache[cache_key])
        try:
            from app.db import MediaDb
            items = MediaDb().get_resume_items(self.client_id, num)
            if items:
                ret_resume = []
                domain = Config().get_domain() or ''
                for row in items:
                    tmdbid = row.TMDBID or ''
                    link = f"{domain}/web#media_detail?id={tmdbid}&type=MOV" if tmdbid else ""
                    mtype = row.ITEM_TYPE or ''
                    percent = round(row.PLAY_PERCENT or 0, 1)
                    ret_resume.append({
                        "id": row.ITEM_ID,
                        "name": row.TITLE or "",
                        "type": mtype,
                        "image": "",
                        "link": link,
                        "percent": percent
                    })
                Kodi._cache[cache_key] = ret_resume
                return ret_resume
        except Exception:
            pass
        # 回退到 MySQL 查询
        conn = self._get_connection()
        if not conn:
            return []
        try:
            with conn.cursor() as cursor:
                ret_resume = []
                domain = Config().get_domain() or ''
                cursor.execute(
                    "SELECT b.timeInSeconds, b.totalTimeInSeconds, "
                    "m.idMovie, m.c00 AS title, "
                    "MAX(CASE WHEN u.type = 'tmdb' THEN u.value END) AS tmdbid "
                    "FROM bookmark b JOIN movie m ON b.idFile = m.idFile "
                    "LEFT JOIN uniqueid u ON u.media_id = m.idMovie AND u.media_type = 'movie' AND u.type = 'tmdb' "
                    "WHERE b.type = 1 "
                    "GROUP BY b.idBookmark, m.idMovie, m.c00, b.timeInSeconds, b.totalTimeInSeconds "
                    "ORDER BY b.idBookmark DESC "
                    "LIMIT %s",
                    (num,)
                )
                for row in cursor.fetchall():
                    item_id = f"movie:{row['idMovie']}"
                    total = row['totalTimeInSeconds'] or 1
                    percent = round(row['timeInSeconds'] / total * 100, 1)
                    tmdbid = row.get('tmdbid') or ''
                    link = f"{domain}/web#media_detail?id={tmdbid}&type=MOV" if tmdbid else ""
                    ret_resume.append({
                        "id": item_id,
                        "name": row['title'],
                        "type": MediaType.MOVIE.value,
                        "image": "",
                        "link": link,
                        "percent": percent
                    })
                cursor.execute(
                    "SELECT b.timeInSeconds, b.totalTimeInSeconds, "
                    "e.idShow, e.c12 AS season, e.c13 AS episode, e.c00 AS title, "
                    "MAX(CASE WHEN u.type = 'tmdb' THEN u.value END) AS tmdbid "
                    "FROM bookmark b JOIN episode e ON b.idFile = e.idFile "
                    "LEFT JOIN uniqueid u ON u.media_id = e.idShow AND u.media_type = 'tvshow' AND u.type = 'tmdb' "
                    "WHERE b.type = 1 "
                    "GROUP BY b.idBookmark, e.idShow, e.c12, e.c13, e.c00, b.timeInSeconds, b.totalTimeInSeconds "
                    "ORDER BY b.idBookmark DESC "
                    "LIMIT %s",
                    (num,)
                )
                for row in cursor.fetchall():
                    item_id = f"tvshow:{row['idShow']}"
                    total = row['totalTimeInSeconds'] or 1
                    percent = round(row['timeInSeconds'] / total * 100, 1)
                    season = row['season'] or ''
                    episode = row['episode'] or ''
                    name = row['title'] or f"第{season}季第{episode}集"
                    tmdbid = row.get('tmdbid') or ''
                    link = f"{domain}/web#media_detail?id={tmdbid}&type=TV" if tmdbid else ""
                    ret_resume.append({
                        "id": item_id,
                        "name": name,
                        "type": MediaType.TV.value,
                        "image": "",
                        "link": link,
                        "percent": percent
                    })
                result = ret_resume[:num]
                Kodi._cache[cache_key] = result
                return result
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】获取继续观看失败：{str(e)}")
            return []
        finally:
            conn.close()

    def get_latest(self, num=20):
        """
        获得最近更新
        优先从本地 SQLite 缓存查询，无数据时回退到 MySQL
        """
        cache_key = f"latest:{num}"
        if cache_key in Kodi._cache:
            return list(Kodi._cache[cache_key])
        try:
            from app.db import MediaDb
            items = MediaDb().get_latest_items(self.client_id, num)
            if items:
                ret_latest = []
                domain = Config().get_domain() or ''
                for row in items:
                    tmdbid = row.TMDBID or ''
                    mtype = row.ITEM_TYPE or ''
                    link = f"{domain}/web#media_detail?id={tmdbid}&type=MOV" if tmdbid and mtype == 'Movie' else (f"{domain}/web#media_detail?id={tmdbid}&type=TV" if tmdbid else "")
                    ret_latest.append({
                        "id": row.ITEM_ID,
                        "name": row.TITLE or "",
                        "type": mtype,
                        "image": "",
                        "link": link
                    })
                Kodi._cache[cache_key] = ret_latest
                return ret_latest
        except Exception:
            pass
        # 回退到 MySQL 查询
        conn = self._get_connection()
        if not conn:
            return []
        try:
            with conn.cursor() as cursor:
                ret_latest = []
                domain = Config().get_domain() or ''
                cursor.execute(
                    "SELECT m.idMovie, m.c00 AS title, f.dateAdded, "
                    "MAX(CASE WHEN u.type = 'tmdb' THEN u.value END) AS tmdbid "
                    "FROM movie m JOIN files f ON m.idFile = f.idFile "
                    "LEFT JOIN uniqueid u ON u.media_id = m.idMovie AND u.media_type = 'movie' AND u.type = 'tmdb' "
                    "WHERE f.dateAdded IS NOT NULL AND f.dateAdded != '' "
                    "GROUP BY m.idMovie, m.c00, f.dateAdded "
                    "ORDER BY f.dateAdded DESC "
                    "LIMIT %s",
                    (num,)
                )
                for row in cursor.fetchall():
                    item_id = f"movie:{row['idMovie']}"
                    tmdbid = row.get('tmdbid') or ''
                    link = f"{domain}/web#media_detail?id={tmdbid}&type=MOV" if tmdbid else ""
                    ret_latest.append({
                        "id": item_id,
                        "name": row['title'],
                        "type": MediaType.MOVIE.value,
                        "image": "",
                        "link": link
                    })
                cursor.execute(
                    "SELECT t.idShow, t.c00 AS title, MAX(f.dateAdded) AS maxDate, "
                    "MAX(CASE WHEN u.type = 'tmdb' THEN u.value END) AS tmdbid "
                    "FROM tvshow t "
                    "JOIN episode e ON t.idShow = e.idShow "
                    "JOIN files f ON e.idFile = f.idFile "
                    "LEFT JOIN uniqueid u ON u.media_id = t.idShow AND u.media_type = 'tvshow' AND u.type = 'tmdb' "
                    "WHERE f.dateAdded IS NOT NULL AND f.dateAdded != '' "
                    "GROUP BY t.idShow, t.c00 "
                    "ORDER BY maxDate DESC "
                    "LIMIT %s",
                    (num,)
                )
                for row in cursor.fetchall():
                    item_id = f"tvshow:{row['idShow']}"
                    tmdbid = row.get('tmdbid') or ''
                    link = f"{domain}/web#media_detail?id={tmdbid}&type=TV" if tmdbid else ""
                    ret_latest.append({
                        "id": item_id,
                        "name": row['title'],
                        "type": MediaType.TV.value,
                        "image": "",
                        "link": link
                    })
                result = ret_latest[:num]
                Kodi._cache[cache_key] = result
                return result
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】获取最近添加失败：{str(e)}")
            return []
        finally:
            conn.close()

    def sync_extra_data(self):
        """
        同步 Kodi 的播放进度和时间戳到本地 SQLite 缓存
        由 MediaServer.sync_mediaserver() 在同步完成后调用
        """
        from app.db import MediaDb
        db = MediaDb()
        db.clear_extra(self.client_id)
        conn = self._get_connection()
        if not conn:
            return
        try:
            with conn.cursor() as cursor:
                # 电影：bookmark + files + uniqueid
                cursor.execute(
                    "SELECT m.idMovie, m.c00 AS title, "
                    "b.timeInSeconds, b.totalTimeInSeconds, "
                    "f.lastPlayed, f.dateAdded, "
                    "MAX(CASE WHEN u.type = 'tmdb' THEN u.value END) AS tmdbid "
                    "FROM movie m "
                    "LEFT JOIN bookmark b ON b.idFile = m.idFile AND b.type = 1 "
                    "LEFT JOIN files f ON f.idFile = m.idFile "
                    "LEFT JOIN uniqueid u ON u.media_id = m.idMovie AND u.media_type = 'movie' AND u.type = 'tmdb' "
                    "GROUP BY m.idMovie, m.c00, b.timeInSeconds, b.totalTimeInSeconds, f.lastPlayed, f.dateAdded"
                )
                for row in cursor.fetchall():
                    total = row['totalTimeInSeconds'] or 1
                    percent = round(row['timeInSeconds'] / total * 100, 1) if row['timeInSeconds'] else None
                    db.insert_extra(self.client_id, {
                        "id": f"movie:{row['idMovie']}",
                        "type": "Movie",
                        "title": row['title'],
                        "tmdbid": row.get('tmdbid') or '',
                        "last_played": row.get('lastPlayed') or '',
                        "date_added": row.get('dateAdded') or '',
                        "play_time": row.get('timeInSeconds'),
                        "play_total": row.get('totalTimeInSeconds'),
                        "play_percent": percent
                    })
                # 剧集：通过 episode 关联 bookmark + files + uniqueid
                cursor.execute(
                    "SELECT t.idShow, t.c00 AS title, "
                    "MAX(b.timeInSeconds) AS maxTime, MAX(b.totalTimeInSeconds) AS maxTotal, "
                    "MAX(f.lastPlayed) AS maxLastPlayed, MAX(f.dateAdded) AS maxDateAdded, "
                    "MAX(CASE WHEN u.type = 'tmdb' THEN u.value END) AS tmdbid "
                    "FROM tvshow t "
                    "LEFT JOIN episode e ON e.idShow = t.idShow "
                    "LEFT JOIN bookmark b ON b.idFile = e.idFile AND b.type = 1 "
                    "LEFT JOIN files f ON f.idFile = e.idFile "
                    "LEFT JOIN uniqueid u ON u.media_id = t.idShow AND u.media_type = 'tvshow' AND u.type = 'tmdb' "
                    "GROUP BY t.idShow, t.c00"
                )
                for row in cursor.fetchall():
                    total = row['maxTotal'] or 1
                    percent = round(row['maxTime'] / total * 100, 1) if row['maxTime'] else None
                    db.insert_extra(self.client_id, {
                        "id": f"tvshow:{row['idShow']}",
                        "type": "Series",
                        "title": row['title'],
                        "tmdbid": row.get('tmdbid') or '',
                        "last_played": row.get('maxLastPlayed') or '',
                        "date_added": row.get('maxDateAdded') or '',
                        "play_time": row.get('maxTime'),
                        "play_total": row.get('maxTotal'),
                        "play_percent": percent
                    })
            log.info(f"【{self.client_name}】额外数据同步完成")
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】同步额外数据失败：{str(e)}")
        finally:
            conn.close()

    def sync_posters(self):
        """
        从 TMDB 获取海报路径并下载到本地缓存
        遍历 MEDIASYNCITEMS 中有 TMDBID 但缺少本地海报的记录
        """
        from app.db import MediaDb
        from app.db.models import MEDIASYNCITEMS
        db = MediaDb()
        try:
            missing = db.session.query(MEDIASYNCITEMS).filter(
                MEDIASYNCITEMS.SERVER == self.client_id,
                MEDIASYNCITEMS.TMDBID.isnot(None),
                MEDIASYNCITEMS.TMDBID != '',
                (MEDIASYNCITEMS.POSTER.is_(None)) | (MEDIASYNCITEMS.POSTER == '')
            ).all()
        except Exception:
            missing = []
        if not missing:
            log.info(f"【{self.client_name}】无需更新海报")
            return

        media = Media()
        if not media.movie or not media.tv:
            log.warn(f"【{self.client_name}】TMDB 未配置，跳过海报同步")
            return

        log.info(f"【{self.client_name}】开始同步海报，待处理：{len(missing)}")
        updated = 0
        for item in missing:
            try:
                tmdbid = item.TMDBID
                if item.ITEM_TYPE == 'Movie':
                    details = media.movie.details(tmdbid)
                else:
                    details = media.tv.details(tmdbid)
                poster_path = details.get('poster_path') if hasattr(details, 'get') else getattr(details, 'poster_path', None)
                if not poster_path:
                    continue
                full_url = Config().get_tmdbimage_url(poster_path)
                local_poster = MediaDb._download_poster(full_url, item.ITEM_ID)
                if local_poster:
                    item.POSTER = local_poster
                    item.NOTE = poster_path
                    db.session.commit()
                    updated += 1
            except Exception:
                db.session.rollback()
                continue
        log.info(f"【{self.client_name}】海报同步完成，已更新：{updated}/{len(missing)}")
