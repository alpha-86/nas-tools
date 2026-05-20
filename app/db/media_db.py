import json
import os
import threading
import time

import requests
from cachetools import cached, TTLCache
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool

from app.db.models import BaseMedia, MEDIASYNCITEMS, MEDIASYNCSTATISTIC, KODISYNCEXTRA
from app.utils import ExceptionUtils
from config import Config

lock = threading.Lock()
_Engine = create_engine(
    f"sqlite:///{os.path.join(Config().get_config_path(), 'media.db')}?check_same_thread=False",
    echo=False,
    poolclass=QueuePool,
    pool_pre_ping=True,
    pool_size=100,
    pool_recycle=60 * 10,
    max_overflow=0
)
_Session = scoped_session(sessionmaker(bind=_Engine,
                                       autoflush=True,
                                       autocommit=False))


class MediaDb:

    @property
    def session(self):
        return _Session()

    @staticmethod
    def init_db():
        with lock:
            BaseMedia.metadata.create_all(_Engine)
            # 增量迁移：为已有表添加新列
            try:
                with _Engine.connect() as conn:
                    conn.execute(text("ALTER TABLE MEDIASYNC_ITEMS ADD COLUMN POSTER TEXT"))
                    conn.commit()
            except Exception:
                pass  # 列已存在则忽略

    @staticmethod
    def _download_poster(poster_url, item_id):
        """
        从 TMDB 下载海报到本地缓存目录，返回相对路径（如 /posters/movie_123.jpg）
        若文件已存在则跳过下载
        """
        if not poster_url or not item_id:
            return None
        try:
            poster_dir = os.path.join(Config().get_config_path(), 'posters')
            os.makedirs(poster_dir, exist_ok=True)
            filename = item_id.replace(':', '_') + '.jpg'
            local_path = os.path.join(poster_dir, filename)
            if not os.path.exists(local_path):
                resp = requests.get(poster_url, timeout=10, headers={'User-Agent': 'NAStools/1.0'})
                if resp.status_code == 200:
                    with open(local_path, 'wb') as f:
                        f.write(resp.content)
                else:
                    return None
            return f'/posters/{filename}'
        except Exception:
            return None

    def insert(self, server_type, iteminfo, seasoninfo):
        if not server_type or not iteminfo:
            return False
        try:
            # 处理海报：TMDB 相对路径需转为完整 URL 并下载到本地
            # 跳过 NFS/SMB 等本地网络路径（Kodi art 表存储的）
            raw_poster = iteminfo.get("poster") or ''
            if raw_poster.startswith('/'):
                full_url = Config().get_tmdbimage_url(raw_poster)
                poster_path = self._download_poster(full_url, iteminfo.get("id"))
            elif raw_poster.startswith('http'):
                poster_path = self._download_poster(raw_poster, iteminfo.get("id"))
            else:
                # NFS/SMB 等路径不存储，留给 sync_posters 从 TMDB 获取
                poster_path = None
            # NOTE 字段存储原始 TMDB 海报路径，用于显示时回退下载
            raw_poster_path = raw_poster if raw_poster.startswith('/') else None

            self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                      MEDIASYNCITEMS.ITEM_ID == iteminfo.get("id")).delete()
            self.session.flush()
            self.session.add(MEDIASYNCITEMS(
                SERVER=server_type,
                LIBRARY=iteminfo.get("library"),
                ITEM_ID=iteminfo.get("id"),
                ITEM_TYPE=iteminfo.get("type"),
                TITLE=iteminfo.get("title"),
                ORGIN_TITLE=iteminfo.get("originalTitle"),
                YEAR=iteminfo.get("year"),
                TMDBID=iteminfo.get("tmdbid"),
                IMDBID=iteminfo.get("imdbid"),
                POSTER=poster_path,
                NOTE=raw_poster_path,
                PATH=iteminfo.get("path"),
                JSON=json.dumps(seasoninfo)
            ))
            self.session.commit()
            return True
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            self.session.rollback()
        return False

    def empty(self, server_type=None, library=None):
        try:
            if server_type and library:
                self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                          MEDIASYNCITEMS.LIBRARY == library).delete()
            elif server_type:
                self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type).delete()
            else:
                self.session.query(MEDIASYNCITEMS).delete()
            self.session.commit()
            return True
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            self.session.rollback()
        return False

    def statistics(self, server_type, total_count, movie_count, tv_count):
        if not server_type:
            return False
        try:
            self.session.query(MEDIASYNCSTATISTIC).filter(MEDIASYNCSTATISTIC.SERVER == server_type).delete()
            self.session.flush()
            self.session.add(MEDIASYNCSTATISTIC(
                SERVER=server_type,
                TOTAL_COUNT=total_count,
                MOVIE_COUNT=movie_count,
                TV_COUNT=tv_count,
                UPDATE_TIME=time.strftime('%Y-%m-%d %H:%M:%S',
                                          time.localtime(time.time()))
            ))
            self.session.commit()
            return True
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            self.session.rollback()
        return False

    @cached(cache=TTLCache(maxsize=128, ttl=60))
    def query(self, server_type, title, year, tmdbid):
        if not server_type or not title:
            return {}

        if tmdbid:
            item = self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                             MEDIASYNCITEMS.TMDBID == tmdbid).first()
            if item:
                return item

        if year:
            item = self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                             MEDIASYNCITEMS.TITLE == title,
                                                             MEDIASYNCITEMS.YEAR == year).first()
        else:
            item = self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                             MEDIASYNCITEMS.TITLE == title).first()
        if item:
            if tmdbid and (not item.TMDBID or item.TMDBID != str(tmdbid)):
                return {}
        return item

    def get_statistics(self, server_type):
        if not server_type:
            return None
        return self.session.query(MEDIASYNCSTATISTIC).filter(MEDIASYNCSTATISTIC.SERVER == server_type).first()

    def list_by_library(self, server_type, library=None, item_type=None, limit=100, offset=0):
        """
        按库列出同步的媒体项目
        """
        if not server_type:
            return []
        try:
            query = self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type)
            if library:
                query = query.filter(MEDIASYNCITEMS.LIBRARY == library)
            if item_type:
                query = query.filter(MEDIASYNCITEMS.ITEM_TYPE == item_type)
            return query.order_by(MEDIASYNCITEMS.ID.desc()).limit(limit).offset(offset).all()
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return []

    def clear_extra(self, server_type):
        """清空 Kodi 额外缓存数据"""
        if not server_type:
            return False
        try:
            self.session.query(KODISYNCEXTRA).filter(KODISYNCEXTRA.SERVER == server_type).delete()
            self.session.commit()
            return True
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            self.session.rollback()
            return False

    def insert_extra(self, server_type, iteminfo):
        """插入/更新 Kodi 额外缓存数据"""
        if not server_type or not iteminfo:
            return False
        try:
            self.session.query(KODISYNCEXTRA).filter(
                KODISYNCEXTRA.SERVER == server_type,
                KODISYNCEXTRA.ITEM_ID == iteminfo.get("id")
            ).delete()
            self.session.flush()
            self.session.add(KODISYNCEXTRA(
                SERVER=server_type,
                ITEM_ID=iteminfo.get("id"),
                ITEM_TYPE=iteminfo.get("type"),
                TITLE=iteminfo.get("title"),
                TMDBID=iteminfo.get("tmdbid"),
                LAST_PLAYED=iteminfo.get("last_played"),
                DATE_ADDED=iteminfo.get("date_added"),
                PLAY_TIME=iteminfo.get("play_time"),
                PLAY_TOTAL=iteminfo.get("play_total"),
                PLAY_PERCENT=iteminfo.get("play_percent"),
            ))
            self.session.commit()
            return True
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            self.session.rollback()
            return False

    def get_resume_items(self, server_type, num=12):
        """从本地缓存获取继续观看（按 PLAY_TIME 降序）"""
        if not server_type:
            return []
        try:
            return self.session.query(KODISYNCEXTRA).filter(
                KODISYNCEXTRA.SERVER == server_type,
                KODISYNCEXTRA.PLAY_TIME.isnot(None)
            ).order_by(KODISYNCEXTRA.PLAY_TIME.desc()).limit(num).all()
        except Exception:
            return []

    def get_latest_items(self, server_type, num=20):
        """从本地缓存获取最近添加（按 DATE_ADDED 降序）"""
        if not server_type:
            return []
        try:
            return self.session.query(KODISYNCEXTRA).filter(
                KODISYNCEXTRA.SERVER == server_type,
                KODISYNCEXTRA.DATE_ADDED.isnot(None)
            ).order_by(KODISYNCEXTRA.DATE_ADDED.desc()).limit(num).all()
        except Exception:
            return []

    def get_activity_items(self, server_type, num=30):
        """从本地缓存获取活动记录（按 LAST_PLAYED 降序）"""
        if not server_type:
            return []
        try:
            return self.session.query(KODISYNCEXTRA).filter(
                KODISYNCEXTRA.SERVER == server_type,
                KODISYNCEXTRA.LAST_PLAYED.isnot(None)
            ).order_by(KODISYNCEXTRA.LAST_PLAYED.desc()).limit(num).all()
        except Exception:
            return []
