from flask_login import UserMixin
from werkzeug.security import check_password_hash
from operator import itemgetter
from urllib.parse import urlparse
import base64
import copy
import hashlib
import json
import os

from cryptography.fernet import Fernet

from app.helper import DbHelper
from config import Config
from app.conf import ModuleConf

class IndexerConf:
    """
    索引器配置
    """
    def __init__(self, id="", name="", url="", domain="",
                 search=False, proxy=False, render=False,
                 cookie="", ua="", token="",
                 order=0, pri=False, rule=None,
                 public=False, builtin=False,
                 tags=None, category=None,
                 language=None, parser=None, batch=None, browse=None,
                 torrents=None):
        self.id = id
        self.name = name
        self.url = url
        # domain auto-derived from url if not provided
        if domain:
            self.domain = domain
        elif url:
            parsed = urlparse(url)
            self.domain = f"{parsed.scheme}://{parsed.netloc}"
        else:
            self.domain = ""
        self.search = search
        self.proxy = proxy
        self.render = render
        self.cookie = cookie
        self.ua = ua
        self.token = token
        self.order = order
        self.pri = pri
        self.rule = rule
        self.public = public
        self.builtin = builtin
        self.tags = tags or []
        self.category = category
        # Additional fields used by _spider.py / builtin.py
        self.language = language
        self.parser = parser
        self.batch = batch or {}
        self.browse = browse or {}
        self.torrents = torrents or {}


MENU_CONF = {
    '我的媒体库': {
        'name': '我的媒体库',
        'level': 1,
        'page': 'index',
        'icon': '\n                      <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-home" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"></path><polyline points="5 12 3 12 12 3 21 12 19 12"></polyline><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-7"></path><path d="M9 21v-6a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v6"></path></svg>\n                    '
        },
    '探索': {
        'name': '探索',
        'level': 2,
        'list': [
                    {'name': '榜单推荐', 'level': 2, 'page': 'ranking', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-align-box-bottom-center" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M4 4m0 2a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2z"></path>\n                                <path d="M9 15v2"></path>\n                                <path d="M12 11v6"></path>\n                                <path d="M15 13v4"></path>\n                              </svg>\n                            '},
                    {'name': '豆瓣电影', 'level': 2, 'page': 'douban_movie', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-movie" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M4 4m0 2a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2z"></path>\n                                <path d="M8 4l0 16"></path>\n                                <path d="M16 4l0 16"></path>\n                                <path d="M4 8l4 0"></path>\n                                <path d="M4 16l4 0"></path>\n                                <path d="M4 12l16 0"></path>\n                                <path d="M16 8l4 0"></path>\n                                <path d="M16 16l4 0"></path>\n                              </svg>\n                            '},
                    {'name': '豆瓣电视剧', 'level': 2, 'page': 'douban_tv', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-device-tv" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M3 7m0 2a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v9a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2z"></path>\n                                <path d="M16 3l-4 4l-4 -4"></path>\n                              </svg>\n                            '},
                    {'name': 'TMDB电影', 'level': 2, 'page': 'tmdb_movie', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-movie" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M4 4m0 2a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2z"></path>\n                                <path d="M8 4l0 16"></path>\n                                <path d="M16 4l0 16"></path>\n                                <path d="M4 8l4 0"></path>\n                                <path d="M4 16l4 0"></path>\n                                <path d="M4 12l16 0"></path>\n                                <path d="M16 8l4 0"></path>\n                                <path d="M16 16l4 0"></path>\n                              </svg>\n                            '},
                    {'name': 'TMDB电视剧', 'level': 2, 'page': 'tmdb_tv', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-device-tv" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M3 7m0 2a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v9a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2z"></path>\n                                <path d="M16 3l-4 4l-4 -4"></path>\n                              </svg>\n                            '},
                    {'name': 'BANGUMI', 'level': 2, 'page': 'bangumi', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-device-tv-old" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                 <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                 <path d="M3 7m0 2a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v9a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2z"></path>\n                                 <path d="M16 3l-4 4l-4 -4"></path>\n                                 <path d="M15 7v13"></path>\n                                 <path d="M18 15v.01"></path>\n                                 <path d="M18 12v.01"></path>\n                              </svg>\n                            '}
        ]
    },
    '资源搜索': {
        'name': '资源搜索',
        'level': 2,
        'page': 'search',
        'icon': '\n                      <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-search" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"></path><circle cx="10" cy="10" r="7"></circle><line x1="21" y1="21" x2="15" y2="15"></line></svg>\n                    '
    },
    '站点管理': {
        'name': '站点管理',
        'level': 2,
        'list': [
                    {'name': '站点维护', 'level': 2, 'page': 'site', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-server-2" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"></path><rect x="3" y="4" width="18" height="8" rx="3"></rect><rect x="3" y="12" width="18" height="8" rx="3"></rect><line x1="7" y1="8" x2="7" y2="8.01"></line><line x1="7" y1="16" x2="7" y2="16.01"></line><path d="M11 8h6"></path><path d="M11 16h6"></path></svg>\n                            '},
                    {'name': '数据统计', 'level': 2, 'page': 'statistics', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-chart-pie" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                 <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                 <path d="M10 3.2a9 9 0 1 0 10.8 10.8a1 1 0 0 0 -1 -1h-6.8a2 2 0 0 1 -2 -2v-7a.9 .9 0 0 0 -1 -.8"></path>\n                                 <path d="M15 3.5a9 9 0 0 1 5.5 5.5h-4.5a1 1 0 0 1 -1 -1v-4.5"></path>\n                              </svg>\n                            '},
                    {'name': '刷流任务', 'level': 2, 'page': 'brushtask', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-check"list" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M9.615 20h-2.615a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2h8a2 2 0 0 1 2 2v8"></path>\n                                <path d="M14 19l2 2l4 -4"></path>\n                                <path d="M9 8h4"></path>\n                                <path d="M9 12h2"></path>\n                              </svg>\n                            '},
                    {'name': '站点资源', 'level': 2, 'page': 'sitelist', 'icon': '\n                              <svg xmlns="http: //www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-cloud-computing" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M6.657 16c-2.572 0 -4.657 -2.007 -4.657 -4.483c0 -2.475 2.085 -4.482 4.657 -4.482c.393 -1.762 1.794 -3.2 3.675 -3.773c1.88 -.572 3.956 -.193 5.444 1c1.488 1.19 2.162 3.007 1.77 4.769h.99c1.913 0 3.464 1.56 3.464 3.486c0 1.927 -1.551 3.487 -3.465 3.487h-11.878"></path>\n                                <path d="M12 16v5"></path>\n                                <path d="M16 16v4a1 1 0 0 0 1 1h4"></path>\n                                <path d="M8 16v4a1 1 0 0 1 -1 1h-4"></path>\n                              </svg>\n                            '}
        ]
    },
    '订阅管理': {
        'name': '订阅管理',
        'level': 2,
        'list': [
                {'name': '电影订阅', 'level': 2, 'page': 'movie_rss', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-movie" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M4 4m0 2a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2z"></path>\n                                <path d="M8 4l0 16"></path>\n                                <path d="M16 4l0 16"></path>\n                                <path d="M4 8l4 0"></path>\n                                <path d="M4 16l4 0"></path>\n                                <path d="M4 12l16 0"></path>\n                                <path d="M16 8l4 0"></path>\n                                <path d="M16 16l4 0"></path>\n                              </svg>\n                            '},
                {'name': '电视剧订阅', 'level': 2, 'page': 'tv_rss', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-device-tv" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M3 7m0 2a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v9a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2z"></path>\n                                <path d="M16 3l-4 4l-4 -4"></path>\n                              </svg>\n                            '},
                {'name': '自定义订阅', 'level': 2, 'page': 'user_rss', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-file-rss" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M14 3v4a1 1 0 0 0 1 1h4"></path>\n                                <path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z"></path>\n                                <path d="M12 17a3 3 0 0 0 -3 -3"></path>\n                                <path d="M15 17a6 6 0 0 0 -6 -6"></path>\n                                <path d="M9 17h.01"></path>\n                              </svg>\n                            '},
                {'name': '订阅日历', 'level': 2, 'page': 'rss_calendar', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-calendar" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M4 5m0 2a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2z"></path>\n                                <path d="M16 3l0 4"></path>\n                                <path d="M8 3l0 4"></path>\n                                <path d="M4 11l16 0"></path>\n                                <path d="M11 15l1 0"></path>\n                                <path d="M12 15l0 3"></path>\n                              </svg>\n                            '}
        ]
    },
    '下载管理': {
        'name': '下载管理',
        'level': 2,
        'list': [
                    {'name': '正在下载', 'level': 2, 'page': 'downloading', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-loader" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M12 6l0 -3"></path>\n                                <path d="M16.25 7.75l2.15 -2.15"></path>\n                                <path d="M18 12l3 0"></path>\n                                <path d="M16.25 16.25l2.15 2.15"></path>\n                                <path d="M12 18l0 3"></path>\n                                <path d="M7.75 16.25l-2.15 2.15"></path>\n                                <path d="M6 12l-3 0"></path>\n                                <path d="M7.75 7.75l-2.15 -2.15"></path>\n                              </svg>\n                            '},
                    {'name': '近期下载', 'level': 2, 'page': 'downloaded', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-download" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"></path><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2"></path><polyline points="7 11 12 16 17 11"></polyline><line x1="12" y1="4" x2="12" y2="16"></line></svg>\n                            '},
                    {'name': '自动删种', 'level': 2, 'page': 'torrent_remove', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-download-off" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 1.83 -1.19"></path>\n                                <path d="M7 11l5 5l2 -2m2 -2l1 -1"></path>\n                                <path d="M12 4v4m0 4v4"></path>\n                                <path d="M3 3l18 18"></path>\n                              </svg>\n                            '}
        ]
    },
    '媒体整理': {
        'name': '媒体整理',
        'level': 1,
        'list': [
                    {'name': '文件管理', 'level': 1, 'page': 'mediafile', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-file-pencil" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M14 3v4a1 1 0 0 0 1 1h4"></path>\n                                <path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z"></path>\n                                <path d="M10 18l5 -5a1.414 1.414 0 0 0 -2 -2l-5 5v2h2z"></path>\n                              </svg>\n                            '},
                    {'name': '手动识别', 'level': 1, 'page': 'unidentification', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-accessible" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0 -18 0"></path>\n                                <path d="M10 16.5l2 -3l2 3m-2 -3v-2l3 -1m-6 0l3 1"></path>\n                                <circle cx="12" cy="7.5" r=".5" fill="currentColor"></circle>\n                              </svg>\n                            '},
                    {'name': '历史记录', 'level': 1, 'page': 'history', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-history" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M12 8l0 4l2 2"></path>\n                                <path d="M3.05 11a9 9 0 1 1 .5 4m-.5 5v-5h5"></path>\n                              </svg>\n                            '},
                    {'name': 'TMDB黑名单', 'level': 1, 'page': 'tmdbblacklist', 'icon': '\n                      <svg t="1750296007713" class="icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="1529" width="128" height="128"><path d="M704 608a192 192 0 1 1 0 384 192 192 0 0 1 0-384z m96-544a64 64 0 0 1 64 64v416a32 32 0 0 1-63.776 3.744L800 544V128H224v736h192a32 32 0 0 1 3.744 63.776L416 928H224a64 64 0 0 1-64-64V128a64 64 0 0 1 64-64h576z m-96 608a128 128 0 1 0 0 256 128 128 0 0 0 0-256z m64 96a32 32 0 0 1 0 64h-128a32 32 0 0 1 0-64h128z m-256-224a32 32 0 0 1 0 64h-192a32 32 0 0 1 0-64h192z m192-160a32 32 0 0 1 0 64H320a32 32 0 0 1 0-64h384z m0-160a32 32 0 0 1 0 64H320a32 32 0 1 1 0-64h384z" fill="#000000" p-id="1530"></path></svg>                           '}
        ]
    },
    '服务': {
        'name': '服务',
        'level': 1,
        'page': 'service',
        'icon': '\n                      <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-layout-2" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"></path><rect x="4" y="4" width="6" height="5" rx="2"></rect><rect x="4" y="13" width="6" height="7" rx="2"></rect><rect x="14" y="4" width="6" height="7" rx="2"></rect><rect x="14" y="15" width="6" height="5" rx="2"></rect></svg>\n                    '
    },
    '系统设置': {
        'name': '系统设置',
        'also': '设置',
        'level': 1,
        'list': [
                    {'name': '基础设置', 'level': 1, 'page': 'basic', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-settings" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"></path><path d="M10.325 4.317c.426 -1.756 2.924 -1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543 -.94 3.31 .826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.756 .426 1.756 2.924 0 3.35a1.724 1.724 0 0 0 -1.066 2.573c.94 1.543 -.826 3.31 -2.37 2.37a1.724 1.724 0 0 0 -2.572 1.065c-.426 1.756 -2.924 1.756 -3.35 0a1.724 1.724 0 0 0 -2.573 -1.066c-1.543 .94 -3.31 -.826 -2.37 -2.37a1.724 1.724 0 0 0 -1.065 -2.572c-1.756 -.426 -1.756 -2.924 0 -3.35a1.724 1.724 0 0 0 1.066 -2.573c-.94 -1.543 .826 -3.31 2.37 -2.37c1 .608 2.296 .07 2.572 -1.065z"></path><circle cx="12" cy="12" r="3"></circle></svg>\n                            '},
                    {'name': '用户管理', 'level': 2, 'page': 'users', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-users" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M9 7m-4 0a4 4 0 1 0 8 0a4 4 0 1 0 -8 0"></path>\n                                <path d="M3 21v-2a4 4 0 0 1 4 -4h4a4 4 0 0 1 4 4v2"></path>\n                                <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>\n                                <path d="M21 21v-2a4 4 0 0 0 -3 -3.85"></path>\n                              </svg>\n                            '},
                    {'name': '媒体库', 'level': 1, 'page': 'library', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-stereo-glasses" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M8 3h-2l-3 9"></path>\n                                <path d="M16 3h2l3 9"></path>\n                                <path d="M3 12v7a1 1 0 0 0 1 1h4.586a1 1 0 0 0 .707 -.293l2 -2a1 1 0 0 1 1.414 0l2 2a1 1 0 0 0 .707 .293h4.586a1 1 0 0 0 1 -1v-7h-18z"></path>\n                                <path d="M7 16h1"></path>\n                                <path d="M16 16h1"></path>\n                              </svg>\n                            '},
                    {'name': '目录同步', 'level': 1, 'page': 'directorysync', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-refresh" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4"></path>\n                                <path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4"></path>\n                              </svg>\n                            '},
                    {'name': '消息通知', 'level': 2, 'page': 'notification', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-bell" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M10 5a2 2 0 0 1 4 0a7 7 0 0 1 4 6v3a4 4 0 0 0 2 3h-16a4 4 0 0 0 2 -3v-3a7 7 0 0 1 4 -6"></path>\n                                <path d="M9 17v1a3 3 0 0 0 6 0v-1"></path>\n                              </svg>\n                            '},
                    {'name': '过滤规则', 'level': 2, 'page': 'filterrule', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-filter" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M5.5 5h13a1 1 0 0 1 .5 1.5l-5 5.5l0 7l-4 -3l0 -4l-5 -5.5a1 1 0 0 1 .5 -1.5"></path>\n                              </svg>\n                            '},
                    {'name': '自定义识别词', 'level': 1, 'page': 'customwords', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-a-b" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M3 16v-5.5a2.5 2.5 0 0 1 5 0v5.5m0 -4h-5"></path>\n                                <path d="M12 6l0 12"></path>\n                                <path d="M16 16v-8h3a2 2 0 0 1 0 4h-3m3 0a2 2 0 0 1 0 4h-3"></path>\n                              </svg>\n                            '},
                    {'name': '索引器', 'level': 2, 'page': 'indexer', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-list-search" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M15 15m-4 0a4 4 0 1 0 8 0a4 4 0 1 0 -8 0"></path>\n                                <path d="M18.5 18.5l2.5 2.5"></path>\n                                <path d="M4 6h16"></path>\n                                <path d="M4 12h4"></path>\n                                <path d="M4 18h4"></path>\n                              </svg>\n                            '},
                    {'name': '下载器', 'level': 2, 'page': 'downloader', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-download" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2"></path>\n                                <path d="M7 11l5 5l5 -5"></path>\n                                <path d="M12 4l0 12"></path>\n                              </svg>\n                            '},
                    {'name': '媒体服务器', 'level': 2, 'page': 'mediaserver', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-server-cog" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                <path d="M3 4m0 3a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v2a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3z"></path>\n                                <path d="M12 20h-6a3 3 0 0 1 -3 -3v-2a3 3 0 0 1 3 -3h10.5"></path>\n                                <path d="M18 18m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"></path>\n                                <path d="M18 14.5v1.5"></path>\n                                <path d="M18 20v1.5"></path>\n                                <path d="M21.032 16.25l-1.299 .75"></path>\n                                <path d="M16.27 19l-1.3 .75"></path>\n                                <path d="M14.97 16.25l1.3 .75"></path>\n                                <path d="M19.733 19l1.3 .75"></path>\n                                <path d="M7 8v.01"></path>\n                                <path d="M7 16v.01"></path>\n                              </svg>\n                            '},
                    {'name': '插件', 'level': 1, 'page': 'plugin', 'icon': '\n                              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-brand-codesandbox" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                                 <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                                 <path d="M20 7.5v9l-4 2.25l-4 2.25l-4 -2.25l-4 -2.25v-9l4 -2.25l4 -2.25l4 2.25z"></path>\n                                 <path d="M12 12l4 -2.25l4 -2.25"></path>\n                                 <path d="M12 12l0 9"></path>\n                                 <path d="M12 12l-4 -2.25l-4 -2.25"></path>\n                                 <path d="M20 12l-4 2v4.75"></path>\n                                 <path d="M4 12l4 2l0 4.75"></path>\n                                 <path d="M8 5.25l4 2.25l4 -2.25"></path>\n                              </svg>\n                            '}
        ]
    }
}

SERVICE_CONF = {
    'rssdownload': {'name': '电影/电视剧订阅', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-cloud-download" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                         <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                         <path d="M19 18a3.5 3.5 0 0 0 0 -7h-1a5 4.5 0 0 0 -11 -2a4.6 4.4 0 0 0 -2.1 8.4"></path>\n                         <line x1="12" y1="13" x2="12" y2="22"></line>\n                         <polyline points="9 19 12 22 15 19"></polyline>\n                    </svg>', 'color': 'blue', 'level': 2},
    'subscribe_search_all': {'name': '订阅搜索', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-search" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                        <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                        <circle cx="10" cy="10" r="7"></circle>\n                        <line x1="21" y1="21" x2="15" y2="15"></line>\n                    </svg>', 'color': 'blue', 'level': 2},
    'pttransfer': {'name': '下载文件转移', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-replace" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                         <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                         <rect x="3" y="3" width="6" height="6" rx="1"></rect>\n                         <rect x="15" y="15" width="6" height="6" rx="1"></rect>\n                         <path d="M21 11v-3a2 2 0 0 0 -2 -2h-6l3 3m0 -6l-3 3"></path>\n                         <path d="M3 13v3a2 2 0 0 0 2 2h6l-3 -3m0 6l3 -3"></path>\n                    </svg>', 'color': 'green', 'level': 2},
    'sync': {'name': '目录同步', 'time': '实时监控', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-refresh" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                            <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                            <path d="M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4"></path>\n                            <path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4"></path>\n                    </svg>', 'color': 'orange', 'level': 1},
    'blacklist': {'name': '清理转移缓存', 'time': '手动', 'state': 'OFF', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-eraser" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                       <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                       <path d="M19 20h-10.5l-4.21 -4.3a1 1 0 0 1 0 -1.41l10 -10a1 1 0 0 1 1.41 0l5 5a1 1 0 0 1 0 1.41l-9.2 9.3"></path>\n                       <path d="M18 13.3l-6.3 -6.3"></path>\n                    </svg>', 'color': 'red', 'level': 1},
    'rsshistory': {'name': '清理RSS缓存', 'time': '手动', 'state': 'OFF', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-eraser" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                       <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                       <path d="M19 20h-10.5l-4.21 -4.3a1 1 0 0 1 0 -1.41l10 -10a1 1 0 0 1 1.41 0l5 5a1 1 0 0 1 0 1.41l-9.2 9.3"></path>\n                       <path d="M18 13.3l-6.3 -6.3"></path>\n                    </svg>', 'color': 'purple', 'level': 2},
    'nametest': {'name': '名称识别测试', 'time': '', 'state': 'OFF', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-alphabet-greek" width="40" height="40" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                       <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                       <path d="M10 10v7"></path>\n                       <rect x="5" y="10" width="5" height="7" rx="2"></rect>\n                       <path d="M14 20v-11a2 2 0 0 1 2 -2h1a2 2 0 0 1 2 2v1a2 2 0 0 1 -2 2a2 2 0 0 1 2 2v1a2 2 0 0 1 -2 2"></path>\n                    </svg>', 'color': 'lime', 'level': 1},
    'ruletest': {'name': '过滤规则测试', 'time': '', 'state': 'OFF', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-adjustments-horizontal" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                       <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                       <circle cx="14" cy="6" r="2"></circle>\n                       <line x1="4" y1="6" x2="12" y2="6"></line>\n                       <line x1="16" y1="6" x2="20" y2="6"></line>\n                       <circle cx="8" cy="12" r="2"></circle>\n                       <line x1="4" y1="12" x2="6" y2="12"></line>\n                       <line x1="10" y1="12" x2="20" y2="12"></line>\n                       <circle cx="17" cy="18" r="2"></circle>\n                       <line x1="4" y1="18" x2="15" y2="18"></line>\n                       <line x1="19" y1="18" x2="20" y2="18"></line>\n                    </svg>', 'color': 'yellow', 'level': 2},
    'nettest': {'name': '网络连通性测试', 'time': '', 'state': 'OFF', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-network" width="40" height="40" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                       <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                       <circle cx="12" cy="9" r="6"></circle>\n                       <path d="M12 3c1.333 .333 2 2.333 2 6s-.667 5.667 -2 6"></path>\n                       <path d="M12 3c-1.333 .333 -2 2.333 -2 6s.667 5.667 2 6"></path>\n                       <path d="M6 9h12"></path>\n                       <path d="M3 19h7"></path>\n                       <path d="M14 19h7"></path>\n                       <circle cx="12" cy="19" r="2"></circle>\n                       <path d="M12 15v2"></path>\n                    </svg>', 'color': 'cyan', 'targets': ModuleConf.NETTEST_TARGETS, 'level': 1},
    'backup': {'name': '备份&恢复', 'time': '', 'state': 'OFF', 'svg': '<svg t="1660720525544" class="icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="1559" width="16" height="16">\n                        <path d="M646 1024H100A100 100 0 0 1 0 924V258a100 100 0 0 1 100-100h546a100 100 0 0 1 100 100v31a40 40 0 1 1-80 0v-31a20 20 0 0 0-20-20H100a20 20 0 0 0-20 20v666a20 20 0 0 0 20 20h546a20 20 0 0 0 20-20V713a40 40 0 0 1 80 0v211a100 100 0 0 1-100 100z" fill="#ffffff" p-id="1560"></path>\n                        <path d="M924 866H806a40 40 0 0 1 0-80h118a20 20 0 0 0 20-20V100a20 20 0 0 0-20-20H378a20 20 0 0 0-20 20v8a40 40 0 0 1-80 0v-8A100 100 0 0 1 378 0h546a100 100 0 0 1 100 100v666a100 100 0 0 1-100 100z" fill="#ffffff" p-id="1561"></path>\n                        <path d="M469 887a40 40 0 0 1-27-10L152 618a40 40 0 0 1 1-60l290-248a40 40 0 0 1 66 30v128a367 367 0 0 0 241-128l94-111a40 40 0 0 1 70 35l-26 109a430 430 0 0 1-379 332v142a40 40 0 0 1-40 40zM240 589l189 169v-91a40 40 0 0 1 40-40c144 0 269-85 323-214a447 447 0 0 1-323 137 40 40 0 0 1-40-40v-83z" fill="#ffffff" p-id="1562"></path>\n                    </svg>', 'color': 'green', 'level': 1},
    'processes': {'name': '系统进程', 'time': '', 'state': 'OFF', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-terminal-2" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">\n                        <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>\n                        <path d="M8 9l3 3l-3 3"></path>\n                        <path d="M13 15l3 0"></path>\n                        <path d="M3 4m0 2a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2z"></path>\n                    </svg>', 'color': 'muted', 'level': 1}
}


class User(UserMixin):
    """
    用户
    """
    dbhelper = None
    admin_users = []

    def __init__(self, user=None):
        self.dbhelper = DbHelper()
        self._site_config = SiteConfigManager()
        self.id = None
        self.admin = 0
        self.username = None
        self.password_hash = None
        self.pris = ""
        self.level = 2
        self.search = 0
        if user:
            self.id = user.get('id')
            self.admin = user.get("admin", 0)
            self.username = user.get('name')
            self.password_hash = user.get('password')
            self.pris = user.get('pris', "")
            self.level = 2
            self.search = user.get("search", 0)
        self.admin_users = [{
            "id": 0,
            "admin": 1,
            "name": Config().get_config('app').get('login_user'),
            "password": Config().get_config('app').get('login_password')[6:],
            "pris": "我的媒体库,资源搜索,探索,站点管理,订阅管理,下载管理,媒体整理,服务,系统设置",
            "level": 2,
            'search': 1
        }]

    def verify_password(self, password):
        """
        验证密码
        """
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        """
        获取用户ID
        """
        return self.id

    def get_pris(self):
        """
        获取用户菜单权限
        """
        return self.pris

    def get(self, user_id):
        """
        根据用户ID获取用户实体，为 login_user 方法提供支持
        """
        if user_id is None:
            return None
        for user in self.admin_users:
            if user.get('id') == user_id:
                return User(user)
        for user in self.dbhelper.get_users():
            if not user:
                continue
            if user.ID == user_id:
                return User({"id": user.ID, "admin": 0, "name": user.NAME, "password": user.PASSWORD, "pris": user.PRIS, "level": 2, "search": 1})
        return None

    def get_user(self, user_name):
        """
        根据用户名获取用户对像
        """
        for user in self.admin_users:
            if user.get("name") == user_name:
                return User(user)
        for user in self.dbhelper.get_users():
            if user.NAME == user_name:
                return User({"id": user.ID, "admin": 0, "name": user.NAME, "password": user.PASSWORD, "pris": user.PRIS, "level": 2, "search": 1})
        return None

    def get_topmenus(self):
        """
        获取所有管理菜单
        """
        return self._site_config.get_topmenus()

    def get_usermenus(self, ignore=None):
        """
        获取用户菜单（委托 SiteConfigManager）
        """
        return self._site_config.get_menus(ignore=ignore, pris=self.get_pris())

    def get_services(self):
        """
        获取服务
        """
        return SERVICE_CONF

    def get_users(self):
        return self.dbhelper.get_users()

    def add_user(self, name, password, pris):
        return self.dbhelper.insert_user(name, password, pris)

    def delete_user(self, name):
        return self.dbhelper.delete_user(name)

    def get_authsites(self):
        """
        获取认证站点（认证移除后返回空）
        """
        return {}

    def check_user(self, site, params):
        """
        校验用户认证（认证移除后直接放行）
        """
        return True, ""

    def as_dict(self):
        """
        返回用户信息字典
        """
        return {
            "id": self.id,
            "name": self.username,
            "pris": self.pris
        }

    def get_indexer(self, url, siteid=None, cookie=None, ua=None,
                    name=None, rule=None, pri=None, public=None,
                    proxy=None, render=None):
        """
        获取索引器配置（委托 SiteConfigManager）
        """
        return self._site_config.get_indexer_conf(
            url=url, siteid=siteid, cookie=cookie, ua=ua,
            name=name, rule=rule, pri=pri, public=public,
            proxy=proxy, render=render
        )

    def get_brush_conf(self):
        """
        获取刷流配置（委托 SiteConfigManager）
        """
        return self._site_config.get_brush_conf()

    def get_public_sites(self):
        """
        获取公开站点列表（委托 SiteConfigManager）
        """
        return self._site_config.get_public_sites()


# 模块级单例：避免频繁 User() 实例化导致重复解密 user.sites.bin
_site_config_manager_instance = None


class SiteConfigManager:
    """
    站点配置管理器（原 .so 中 WlI5bfacg2 的替代实现）
    """

    def __new__(cls):
        global _site_config_manager_instance
        if _site_config_manager_instance is None:
            _site_config_manager_instance = super().__new__(cls)
            _site_config_manager_instance._sites_data = {}
            _site_config_manager_instance.init_config()
        return _site_config_manager_instance

    def init_config(self):
        """加载并解密站点配置"""
        bin_path = os.path.join(os.path.dirname(__file__), 'user.sites.bin')
        if not os.path.exists(bin_path):
            return
        try:
            with open(bin_path, 'rb') as f:
                ciphertext = f.read()
            plaintext = self.__decrypt(ciphertext)
            self._sites_data = self.__load_sites_data(plaintext)
        except Exception as e:
            print(f"[SiteConfigManager] Failed to load sites config: {e}")
            self._sites_data = {}

    def __decrypt(self, ciphertext):
        """Fernet 解密

        The Fernet key was extracted from the compiled .so binary
        (string analysis found: LB_uTK_lJ4KUb5EKMjOVohDwNZjA8ALRQSxBgbxYJME=).
        """
        fernet_key = b"LB_uTK_lJ4KUb5EKMjOVohDwNZjA8ALRQSxBgbxYJME="
        f = Fernet(fernet_key)
        return f.decrypt(ciphertext)

    @staticmethod
    def __load_sites_data(plaintext):
        """将解密后的数据转换为可 JSON 序列化的 dict"""
        import pickle
        data = pickle.loads(plaintext)
        # Convert ruamel.yaml CommentedMap/CommentedSeq to plain dict/list
        return SiteConfigManager.__yaml_to_dict(data)

    @staticmethod
    def __yaml_to_dict(obj):
        """递归转换 ruamel.yaml 对象为标准 Python 类型"""
        from ruamel.yaml.comments import CommentedMap, CommentedSeq
        if isinstance(obj, CommentedMap):
            return {k: SiteConfigManager.__yaml_to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, CommentedSeq):
            return [SiteConfigManager.__yaml_to_dict(v) for v in obj]
        elif isinstance(obj, dict):
            return {k: SiteConfigManager.__yaml_to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [SiteConfigManager.__yaml_to_dict(v) for v in obj]
        else:
            return obj

    def get_topmenus(self):
        """返回可分配的权限名称列表"""
        return ["我的媒体库", "探索", "资源搜索", "站点管理",
                "订阅管理", "下载管理", "媒体整理", "服务", "系统设置"]

    def get_topmenus_string(self):
        """返回逗号分隔的权限字符串"""
        return ",".join(self.get_topmenus())

    def get_menus(self, ignore=None, pris=None):
        """根据权限过滤 MENU_CONF，深拷贝后操作

        Args:
            ignore: list of page names to exclude
            pris: comma-separated menu names the user has access to
        """
        if ignore is None:
            ignore = []
        menu_conf = copy.deepcopy(MENU_CONF)
        # Filter by user pris if provided
        if pris:
            allowed = set(pris.split(","))
            menu_conf = {k: v for k, v in menu_conf.items() if k in allowed}
        result = []
        for key, value in menu_conf.items():
            if value.get('page', 'null') in ignore:
                continue
            if 'list' in value:
                value['list'] = [page for page in value['list']
                                if page.get('page') not in ignore]
                if not value['list']:
                    continue
            result.append(value)
        return result

    def get_indexer_conf(self, url, siteid=None, cookie=None, ua=None,
                         name=None, rule=None, pri=None, public=None,
                         proxy=None, render=None):
        """根据 URL 查找站点配置并构造 IndexerConf

        运行时传入参数优先，_sites_data 中的静态配置做补全。
        传入参数：cookie, ua, proxy, render, rule, pri, public, name, siteid
        站点配置：search, parser, language, browse, batch, torrents, category, domain
        """
        site_data = self.__find_site_by_url(url)
        if site_data:
            search = site_data.get("search", False)
            batch = search.get("batch", {}) if isinstance(search, dict) else {}
            # 运行时参数优先，显式 False 不应被站点配置的 True 覆盖
            indexer = IndexerConf(
                id=siteid or site_data.get("id", ""),
                name=name or site_data.get("name", ""),
                url=url,
                domain=site_data.get("domain", ""),
                search=search,
                proxy=proxy if proxy is not None else site_data.get("proxy", False),
                render=render if render is not None else site_data.get("render", False),
                cookie=cookie or "",
                ua=ua or "",
                rule=rule,
                pri=pri if pri is not None else (site_data.get("public", False) is False),
                public=public if public is not None else site_data.get("public", False),
                builtin=True,
                category=site_data.get("category"),
                language=site_data.get("language"),
                parser=site_data.get("parser"),
                batch=batch,
                browse=site_data.get("browse"),
                torrents=site_data.get("torrents")
            )
            return indexer
        # Fallback: construct from parameters only
        return IndexerConf(
            id=siteid or "", name=name or "", url=url,
            cookie=cookie or "", ua=ua or "", rule=rule,
            pri=pri if pri is not None else False,
            public=public if public is not None else False,
            proxy=proxy if proxy is not None else False,
            render=render if render is not None else False
        )

    def __find_site_by_url(self, url):
        """通过 URL 在 _sites_data 中查找站点配置

        基于 urlparse 提取 netloc 做精确匹配，避免 query/path 导致的误命中。
        """
        if not url or not self._sites_data:
            return None
        url_host = urlparse(url).netloc.lower()
        if not url_host:
            return None
        for site in self._sites_data.values():
            domain = site.get("domain", "")
            domain_host = urlparse(domain).netloc.lower()
            if not domain_host:
                continue
            # 精确匹配或子域名匹配（如 pt.example.com 匹配 example.com 的站点）
            if url_host == domain_host or url_host.endswith("." + domain_host):
                return site
        return None

    @staticmethod
    def __css_to_xpath(css_selector):
        """将简单 CSS 选择器转换为 xpath（支持 tag.class 和 tag#id 形式）"""
        if not css_selector or css_selector == "*":
            return None
        # Handle #id selector: tag#id or #id
        if "#" in css_selector:
            parts = css_selector.split("#", 1)
            tag = parts[0] if parts[0] else "*"
            id_val = parts[1]
            return f"//{tag}[@id='{id_val}']"
        # Handle .class selector: tag.class or .class
        if "." in css_selector:
            parts = css_selector.split(".")
            tag = parts[0] if parts[0] else "*"
            classes = ".".join(parts[1:])
            return f"//{tag}[contains(@class, '{classes}')]"
        # Tag only
        return f"//{css_selector}"

    def get_brush_conf(self):
        """返回刷流配置 {domain_url: brush_config}

        从 _sites_data 的 torrents.fields 中提取 FREE/2XFREE/HR 信息，
        转换为 xpath 格式返回。

        返回的每个 brush_config 始终包含以下 key（值为空列表表示无匹配规则）：
            FREE, 2XFREE, HR, PEER_COUNT
        调用方 siteconf.py 会直接遍历这些 key，空列表保证不会因 None 抛 TypeError。
        """
        brush_conf = {}
        for site in self._sites_data.values():
            domain = site.get("domain", "").rstrip("/")
            if not domain:
                continue
            fields = site.get("torrents", {}).get("fields", {})
            dvf = fields.get("downloadvolumefactor", {})
            uvf = fields.get("uploadvolumefactor", {})

            free_xpaths = []
            twofree_xpaths = []
            hr_xpaths = []
            peer_count_xpaths = []

            # Extract FREE css selectors (dvf value == 0)
            if isinstance(dvf, dict) and "case" in dvf:
                for sel, val in dvf["case"].items():
                    if val == 0 and sel != "*":
                        xp = self.__css_to_xpath(sel)
                        if xp:
                            free_xpaths.append(xp)

            # Extract 2XFREE: selectors where uvf == 2
            if isinstance(uvf, dict) and "case" in uvf:
                for sel, val in uvf["case"].items():
                    if val == 2 and sel != "*":
                        xp = self.__css_to_xpath(sel)
                        if xp:
                            twofree_xpaths.append(xp)

            # Extract HR
            if "hr_days" in fields:
                hr_xpaths.append("//span[contains(text(),'H&R')]")
                hr_xpaths.append("//img[contains(@title,'H&R')]")

            # PEER_COUNT: 目前数据中没有直接对应的 xpath，留空列表占位
            # 若将来 sites_data 补充了 peers 相关字段，可在此扩展

            brush_entry = {
                "FREE": free_xpaths,
                "2XFREE": twofree_xpaths,
                "HR": hr_xpaths,
                "PEER_COUNT": peer_count_xpaths,
            }
            if site.get("render"):
                brush_entry["RENDER"] = True

            brush_conf[domain] = brush_entry

        return brush_conf

    def get_public_sites(self):
        """返回公开站点 URL 列表

        Called from app/indexer/client/builtin.py.
        """
        public_sites = []
        for site_conf in self._sites_data.values():
            if site_conf.get("public", False):
                domain = site_conf.get("domain", "")
                if domain:
                    public_sites.append(domain)
        return public_sites
