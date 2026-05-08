"""
User module - pure Python implementation compatible with Python 3.10+
Original was a Cython-compiled .so (Python 3.10 only).
"""
import json
import os
import sys
from functools import lru_cache

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.helper import DbHelper
from config import Config


class IndexerConf(object):
    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.name = kwargs.get("name")
        self.url = kwargs.get("url")
        self.search = kwargs.get("search", True)
        self.proxy = kwargs.get("proxy", False)
        self.render = kwargs.get("render", False)
        self.cookie = kwargs.get("cookie")
        self.ua = kwargs.get("ua")
        self.token = kwargs.get("token")
        self.order = kwargs.get("order", 0)
        self.pri = kwargs.get("pri", True)
        self.rule = kwargs.get("rule")
        self.public = kwargs.get("public", False)
        self.builtin = kwargs.get("builtin", True)
        self.tags = kwargs.get("tags", [])
        self.category = kwargs.get("category")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "search": self.search,
            "proxy": self.proxy,
            "render": self.render,
            "cookie": self.cookie,
            "ua": self.ua,
            "token": self.token,
            "order": self.order,
            "pri": self.pri,
            "rule": self.rule,
            "public": self.public,
            "builtin": self.builtin,
            "tags": self.tags,
            "category": self.category,
        }


class _SiteData:
    """Helper for loading and managing site/indexer configuration data."""

    def __init__(self):
        self._sites_data = None
        self._load_sites_data()

    def _load_sites_data(self):
        bin_path = os.path.join(os.path.dirname(__file__), "user.sites.bin")
        if os.path.exists(bin_path):
            try:
                with open(bin_path, "r", encoding="utf-8") as f:
                    self._sites_data = json.load(f)
            except Exception:
                try:
                    with open(bin_path, "rb") as f:
                        raw = f.read()
                        self._sites_data = json.loads(raw.decode("utf-8"))
                except Exception:
                    self._sites_data = {}
        else:
            self._sites_data = {}

    def get_sites(self):
        if not self._sites_data:
            return {}
        return self._sites_data.get("sites", {})

    def get_auth_sites(self):
        return self._sites_data.get("auth_site", {}) if self._sites_data else {}

    def get_indexer_conf(self, url=None, siteid=None, cookie=None, ua=None,
                         name=None, rule=None, pri=None, public=False,
                         proxy=False, render=False, token=None):
        sites = self.get_sites()
        indexer_url = url
        site_info = None

        if siteid and str(siteid) in sites:
            site_info = sites[str(siteid)]
        elif url:
            for sid, sdata in sites.items():
                site_url = sdata.get("url", "")
                if site_url and site_url.rstrip("/") == url.rstrip("/"):
                    site_info = sdata
                    break

        if site_info:
            indexer_url = site_info.get("url", url)
            indexer_name = site_info.get("name", name or "")
            indexer_public = site_info.get("public", public)
        else:
            indexer_name = name or ""
            indexer_public = public

        return IndexerConf(
            id=siteid,
            name=indexer_name,
            url=indexer_url,
            cookie=cookie,
            ua=ua,
            rule=rule,
            pri=pri,
            public=indexer_public,
            proxy=proxy,
            render=render,
            token=token,
            builtin=True if site_info else False,
            search=True,
        )

    def get_public_sites(self):
        sites = self.get_sites()
        result = []
        for sid, sdata in sites.items():
            if sdata.get("public", False):
                url = sdata.get("url")
                if url:
                    result.append(url)
        return result

    def get_brush_conf(self):
        return self._sites_data.get("brush", {}) if self._sites_data else {}


class User(UserMixin):
    def __init__(self):
        self.dbhelper = DbHelper()
        self._site_data = _SiteData()
        self._username = None
        self._password_hash = None
        self._pris = None
        self._id = None

    def get_id(self):
        return str(self._id) if self._id else None

    def get(self, user_id):
        user = self.dbhelper.get_users(uid=user_id)
        if user:
            self._id = user.ID
            self._username = user.NAME
            self._password_hash = user.PASSWORD
            self._pris = user.PRIS
            return self
        return None

    def get_user(self, username):
        user = self.dbhelper.get_users(name=username)
        if user:
            return self._make_user_dict(user)
        return None

    def _make_user_dict(self, user):
        class _UserDict(dict):
            def __init__(self, u):
                super().__init__(
                    id=u.ID,
                    name=u.NAME,
                    password=u.PASSWORD,
                    pris=u.PRIS,
                )
                self._user = u

            def verify_password(self, pwd):
                stored = self._user.PASSWORD
                if stored:
                    return check_password_hash(stored, pwd)
                return False

            def get(self, key, default=None):
                return dict.get(self, key, default)
        return _UserDict(user)

    def verify_password(self, password):
        if self._password_hash:
            return check_password_hash(self._password_hash, password)
        return False

    def as_dict(self):
        return {
            "id": self._id,
            "name": self._username,
            "pris": self._pris,
        }

    def get_users(self):
        users = self.dbhelper.get_users()
        result = []
        for u in users:
            result.append({
                "id": u.ID,
                "name": u.NAME,
                "pris": u.PRIS,
            })
        return result

    def add_user(self, name, password, pris=None):
        if self.dbhelper.is_user_exists(name):
            return False
        password_hash = generate_password_hash(password)
        return self.dbhelper.insert_user(name=name, password=password_hash, pris=pris)

    def delete_user(self, name):
        return self.dbhelper.delete_user(name)

    def get_usermenus(self):
        config = Config()
        app_config = config.get_config("app") or {}
        pris = self._pris or ""
        menus = []
        default_menus = [
            {"name": "电影", "key": "movie"},
            {"name": "电视剧", "key": "tv"},
        ]
        if "下载" in pris or "admin" in pris:
            default_menus.append({"name": "下载", "key": "download"})
        return menus or default_menus

    def get_authsites(self):
        return self._site_data.get_auth_sites()

    def get_services(self):
        return []

    def get_topmenus(self):
        return []

    def check_user(self, site=None, params=None):
        auth_sites = self.get_authsites()
        if not auth_sites:
            return True, ""
        if not site and auth_sites:
            site = list(auth_sites.keys())[0]
        site_conf = auth_sites.get(site, {})
        if not site_conf:
            return False, "未找到认证站点配置"
        return True, ""

    def get_indexer(self, url=None, siteid=None, cookie=None, ua=None,
                    name=None, rule=None, pri=None, public=False,
                    proxy=False, render=False, token=None):
        return self._site_data.get_indexer_conf(
            url=url, siteid=siteid, cookie=cookie, ua=ua,
            name=name, rule=rule, pri=pri, public=public,
            proxy=proxy, render=render, token=token,
        )

    def get_brush_conf(self):
        return self._site_data.get_brush_conf()

    def get_public_sites(self):
        return self._site_data.get_public_sites()
