# Plan 010: 新增 Kodi（MySQL）媒体服务器支持

> 目标：让 NAStools 支持以 Kodi MySQL 视频库作为媒体服务器，实现媒体存在性检查、同步与通知，且完全不依赖 Kodi 本体运行状态（不调用 JSON-RPC）。

---

## 1. 背景与约束

### 1.1 为什么选 MySQL 而非 JSON-RPC

Kodi 的 MySQL 视频库是持续可用的（通常由独立 MySQL/MariaDB 实例托管），而 Kodi 应用本身可能未启动。因此本方案**只读 MySQL**，放弃所有 JSON-RPC 调用。

> **关键约束**：Kodi 应用可能未运行，所有功能必须仅基于 MySQL 数据实现。

### 1.2 Kodi MySQL 视频库结构

Kodi 视频库数据库名随版本变化（如 `MyVideos119`、`MyVideos131`），典型表结构如下：

| 表 | 说明 | 关键字段 |
|---|---|---|
| `movie` | 电影 | `idMovie`, `c00`(标题), `premiered`(首映日期), `c16`(原始标题) |
| `tvshow` | 剧集 | `idShow`, `c00`(标题), `c05`(首播日期), `c09`(原始标题), `c15`(排序标题) |
| `episode` | 单集 | `idEpisode`, `idShow`, `c00`(标题), `c12`(季号), `c13`(集号) |
| `seasons` | 季 | `idSeason`, `idShow`, `season`(季号) |
| `uniqueid` | 外部 ID 映射 | `media_id`, `media_type`, `type`('tmdb'/'imdb'), `value` |
| `files` | 文件 | `idFile`, `idPath`, `strFilename` |
| `path` | 路径 | `idPath`, `strPath` |
| `tvshowlinkpath` | 剧集-路径关联 | `idShow`, `idPath` |

> **注意**：`uniqueid` 表（Kodi 17+）是获取 TMDB/IMDB ID 的标准入口，不同版本字段位置一致，优先查此表。

### 1.3 与现有媒体服务器的差异

| 能力 | Emby/Jellyfin/Plex | Kodi（MySQL） |
|---|---|---|
| 在线刷新媒体库 | 支持 | **不支持**（Kodi 未启动） |
| 获取播放链接 | 支持 | **不支持** |
| Webhook 事件 | 支持 | **不支持** |
| 活动日志 | 支持 | **不支持** |
| 正在播放会话 | 支持 | **不支持** |
| 远程图片 URL | 服务器提供 | **不支持**（需从 TMDB 获取） |
| 用户系统 | 支持 | **不支持** |

---

## 2. 技术设计

### 2.1 架构定位

Kodi 作为媒体服务器接入现有架构，遵循与 Emby/Jellyfin/Plex 相同的模式：

- 继承 `_IMediaClient` 抽象基类
- 由 `SubmoduleHelper` 自动发现并注册
- 通过 `MediaServer.sync_mediaserver()` 将 MySQL 数据同步到本地 SQLite
- 查重走本地 `MEDIASYNCITEMS` 表（与现有服务器一致）

### 2.2 图片获取策略

Kodi 无对外图片服务，图片**全部走 TMDB**：

- 查 MySQL `uniqueid` 表获取 `tmdbid`
- 调用项目已有 `app.media.Media` 模块获取 TMDB 图片 URL：
  - `Media().get_tmdb_backdrop(mtype, tmdbid)` → 背景图
  - `Media().get_tmdb_info(mtype, tmdbid)` → 取 `poster_path` 构造海报 URL
  - `Config().get_tmdbimage_url(path, prefix)` → 构造完整 TMDB CDN URL

> **关键约束**：无 TMDB ID 的媒体无法提供图片，返回 `None`。

### 2.3 各方法实现策略

| 方法 | 实现方式 | 备注 |
|---|---|---|
| `get_status()` | 连接 MySQL，`SELECT 1` | |
| `get_user_count()` | 固定返回 `1` | Kodi 无用户系统 |
| `get_activity_log()` | 返回 `[]` | 不支持 |
| `get_medias_count()` | `COUNT(movie)` / `COUNT(tvshow)` | |
| `get_movies(title, year)` | 查 `movie` 表，`c00` 匹配标题，`premiered` 提取年份匹配 | |
| `get_tv_episodes(item_id, title, year, tmdbid, season)` | 联查 `tvshow` → `episode` | 需先解析 `item_id` 前缀（如 `tvshow:1` → `1`）；无 `item_id` 时先按标题查 `idShow` |
| `get_no_exists_episodes()` | 同 Emby 模式：已有集号 → 算差集 | |
| `get_libraries()` | 从 `path` 表聚合，区分电影/剧集路径 | 见 2.5 节具体 SQL；返回 `{id, name, type, path, ...}` |
| `get_items(parent)` | 按 `parent`（`path.idPath`）过滤后查 `movie` / `tvshow` → yield 标准字典 | `type` 必须为 `"Movie"` 或 `"Series"`；包含 `uniqueid` 联查 |
| `get_play_url()` | 返回 `""` | 不支持 |
| `get_playing_sessions()` | 返回 `[]` | 不支持 |
| `get_webhook_message()` | 返回 `None` | 不支持 |
| `refresh_root_library()` | 返回 `False` | 不支持 |
| `refresh_library_by_items()` | 返回 `None` | 不支持 |
| `get_remote_image_by_id()` | 查 `uniqueid` 取 tmdbid → `Media().get_tmdb_backdrop()` / `get_tmdb_info()` | 需先解析 `item_id` 前缀 |
| `get_local_image_by_id()` | 同上 | 与 `get_remote_image_by_id` 行为一致；需先解析 `item_id` 前缀 |
| `get_episode_image_by_id()` | 查 tvshow 的 tmdbid → `Media().get_episode_images()` | 需先解析 `item_id` 前缀 |
| `get_iteminfo()` | 查 `movie` / `tvshow` 返回详情 dict | `MediaServer` 直接调用，非抽象方法但需提供；需先解析 `item_id` 前缀 |
| `get_resume()` | 返回 `[]` | Kodi 无播放进度跨设备同步，空实现 |
| `get_latest()` | 返回 `[]` | 可选实现（见 5.5 节）；第一版空实现 |

### 2.4 `get_items()` 返回的数据格式

`MediaServer.sync_mediaserver()` 会把 `get_items()` 的结果写入本地 SQLite。`get_items(parent)` 接收 `parent` 参数（即 `path.idPath`），只返回该 library 下的媒体。返回格式必须与其他服务器一致：

```python
yield {
    "id": f"movie:{movie.idMovie}",   # 命名空间前缀，避免 movie/tvshow ID 冲突
    "library": path_id,               # path.idPath（作为 library 标识）
    "type": "Movie",                  # 必须为 "Movie" 或 "Series"
    "title": movie.c00,               # 标题
    "originalTitle": movie.c16,       # 原始标题
    "year": movie.premiered[:4],      # 从 premiered 提取年份
    "tmdbid": tmdb_id,                # 从 uniqueid 表查
    "imdbid": imdb_id,                # 从 uniqueid 表查
    "path": full_path,                # path.strPath + files.strFilename
    "json": str({...})                # 额外信息序列化（如 season/episode）
}
# 剧集同理："id": f"tvshow:{tvshow.idShow}"
```

> **关键**：`type` 必须为 `"Movie"` 或 `"Series"`。`media_server.py:250` 只对 `['Movie', 'movie']` 和 `['Series', 'show']` 获取季/集信息；返回 `"TV"` 或 `"tvshow"` 会导致 `check_item_exists()` 缺少 episode JSON。

> **ID 命名空间**：Kodi 的 `idMovie` 和 `idShow` 是各自独立的自增序列，可能重合（如电影 id=1 和剧集 idShow=1）。`MediaDb.insert()` 按 `SERVER + ITEM_ID` 唯一键删除后插入，同名 ID 会互相覆盖。因此 Kodi 的 `get_items()` 返回的 `id` 必须带前缀，如 `movie:1`、`tvshow:1`。所有接收 `item_id` 的 Kodi 方法（`get_iteminfo`、`get_remote_image_by_id`、`get_local_image_by_id`、`get_episode_image_by_id`、`get_play_url`、`get_tv_episodes`）都必须能解析该前缀，提取原始数字 ID。

> **Library 过滤**：`parent` 即 `get_libraries()` 返回的 `path.idPath`。电影通过 `files.idPath = parent` 过滤；剧集通过 `tvshowlinkpath.idPath = parent` 过滤。

### 2.5 `get_libraries()` 实现与路径映射

Kodi 的表结构**没有** `movie.idPath` 或 `tvshow.idPath` 字段：
- **Movie**：通过 `movie.idFile → files.idPath → path.idPath` 关联
- **TV Show**：通过 `tvshowlinkpath.idShow → tvshowlinkpath.idPath → path.idPath` 关联
- **Episode**：通过 `episode.idFile → files.idPath → path.idPath` 关联

`get_libraries()` 返回格式（`media_server.py:238` 期望 dict 列表）：

```python
[
    {
        "id": path_id,           # path.idPath
        "name": path_name,       # path.strPath 最后一级目录名
        "path": strPath,
        "type": "movie" | "tv",  # 根据该路径下媒体类型推断
        "image": "",             # 本地图片，Kodi 无对外服务，留空
        "link": ""               # 播放链接，Kodi 无 Web 界面，留空
    }
]
```

路径推断策略：
1. 收集所有 `path` 记录
2. 根据 `files` + `movie` 关联标记含电影的路径
3. 根据 `tvshowlinkpath` 关联标记含剧集的路径
4. 同名路径合并为一个 library dict

路径映射：Kodi `path.strPath` 中的路径是 Kodi 所在机器的路径。如果 NAStools 与 Kodi 不在同一台机器/容器上，需要考虑路径映射转换（类似 Emby 的 `__get_emby_library_id_by_item` 逻辑）。

> **注意**：路径映射可能需要在配置中提供 `path_mapping` 字段，将 Kodi 路径映射到 NAStools 可见路径。第一版可先不做，标注为后续增强。

---

## 3. 配置设计

### 3.1 `app/utils/types.py` — 添加类型枚举

```python
class MediaServerType(Enum):
    JELLYFIN = "Jellyfin"
    EMBY = "Emby"
    PLEX = "Plex"
    KODI = "Kodi"           # 新增
```

### 3.2 `app/conf/moduleconf.py` — 添加配置项

```python
"kodi": {
    "name": "Kodi",
    "img_url": "../static/img/mediaserver/kodi.png",
    "background": "bg-blue",
    "test_command": "app.mediaserver.client.kodi|Kodi",
    "config": {
        "mysql_host": {
            "id": "kodi.mysql_host",
            "required": True,
            "title": "MySQL 服务器地址",
            "type": "text",
            "placeholder": "127.0.0.1"
        },
        "mysql_port": {
            "id": "kodi.mysql_port",
            "required": True,
            "title": "MySQL 端口",
            "type": "text",
            "placeholder": "3306"
        },
        "mysql_user": {
            "id": "kodi.mysql_user",
            "required": True,
            "title": "MySQL 用户名",
            "type": "text"
        },
        "mysql_password": {
            "id": "kodi.mysql_password",
            "required": True,
            "title": "MySQL 密码",
            "type": "password"
        },
        "mysql_db": {
            "id": "kodi.mysql_db",
            "required": True,
            "title": "数据库名",
            "tooltip": "如 MyVideos119，需与 Kodi 版本对应",
            "type": "text",
            "placeholder": "MyVideos119"
        }
    }
}
```

### 3.3 `config/config.yaml` — 添加默认配置

```yaml
media:
  media_server: emby   # 可改为 kodi

kodi:
  mysql_host: 127.0.0.1
  mysql_port: 3306
  mysql_user: kodi
  mysql_password:
  mysql_db: MyVideos119
```

### 3.4 依赖

- `pymysql` 用于连接 MySQL（如项目未包含需安装）

---

## 4. 实现计划

### Phase 1: 基础设施 [P0]

| 任务 | 文件 | 说明 |
|---|---|---|
| 添加 `MediaServerType.KODI` | `app/utils/types.py` | 枚举新增 |
| 添加 `MEDIASERVER_CONF["kodi"]` | `app/conf/moduleconf.py` | UI 配置表单 |
| 添加默认 `kodi` 配置 | `config/config.yaml` | 默认连接参数 |
| 更新测试连接白名单 | `web/action.py` | import `Kodi` 类并加入 `MEDIA_SERVER_MAP` |
| 确认/安装 `pymysql` | `requirements.txt` | 如缺失则添加 |

**web/action.py 白名单修改详情**：

```python
# 1. 新增 import（line 33 附近）
from app.mediaserver.client.kodi import Kodi

# 2. MEDIA_SERVER_MAP 新增条目（line 1636 附近）
MEDIA_SERVER_MAP = {
    "app.mediaserver.client.emby|Emby": Emby,
    "app.mediaserver.client.jellyfin|Jellyfin": Jellyfin,
    "app.mediaserver.client.plex|Plex": Plex,
    "app.mediaserver.client.kodi|Kodi": Kodi,  # 新增
}
```

### Phase 2: Kodi 客户端实现 [P0]

| 任务 | 文件 | 说明 |
|---|---|---|
| 新建 `Kodi` 类 | `app/mediaserver/client/kodi.py` | 继承 `_IMediaClient`，纯 MySQL 查询 |
| 实现基础方法 | `kodi.py` | `get_status`, `get_user_count`, `get_medias_count`, `get_movies` |
| 实现剧集方法 | `kodi.py` | `get_tv_episodes`, `get_no_exists_episodes` |
| 实现库遍历方法 | `kodi.py` | `get_libraries`, `get_items` |
| 实现图片方法 | `kodi.py` | `get_remote_image_by_id`, `get_local_image_by_id`, `get_episode_image_by_id` |
| 实现 `get_iteminfo` | `kodi.py` | `MediaServer` 直接调用，非抽象但必须提供 |
| 实现 ID 前缀解析 | `kodi.py` | 私有方法 `__parse_item_id(item_id)`，统一处理 `movie:N` / `tvshow:N` → `(type, raw_id)` |
| 空实现不支持方法 | `kodi.py` | `get_play_url`, `get_playing_sessions`, `get_activity_log`, `get_webhook_message`, `refresh_root_library`, `refresh_library_by_items`, `get_resume`, `get_latest` |

### Phase 3: 测试与验证 [P1]

| 任务 | 文件 | 说明 |
|---|---|---|
| 单元测试 | `tests/test_kodi_mediaserver.py` | 模拟 MySQL 数据测试各方法返回格式 |
| 连接测试 | `kodi.py` | `get_status()` 连通性验证 |
| 同步测试 | `media_server.py` | 验证 `sync_mediaserver()` 可正常将 Kodi 数据写入 `MEDIASYNCITEMS` |
| 查重测试 | `media_server.py` | 验证 `check_item_exists()` 对 Kodi 数据生效 |
| 更新白名单测试 | `tests/test_test_connection_whitelist.py` | `MEDIA_SERVER_MAP` 新增 `app.mediaserver.client.kodi\|Kodi` |
| UI 配置测试 | 手工 | 在 Web 设置页配置 Kodi，测试连接按钮 |

### Phase 4: 文档 [P1]

| 任务 | 文件 | 说明 |
|---|---|---|
| 更新配置文档 | `docs/` 或 `README` | 说明 Kodi MySQL 配置方法 |
| 数据库版本对照 | `docs/` | 列出常见 Kodi 版本对应的数据库名 |

---

## 5. 风险与决策

### 5.1 MySQL 数据库版本兼容性

| 风险 | 等级 | 说明 |
|---|---|---|
| 表结构变化 | **中** | Kodi 18/19/20/21 的数据库结构略有差异，`uniqueid` 表在 Kodi 17+ 引入 |

**决策**：
- 第一版以 Kodi 19+（`MyVideos119`）为目标，要求用户填写正确的数据库名
- 在配置 tooltip 中提示用户查看 Kodi `advancedsettings.xml` 中的数据库名

### 5.2 无 TMDB ID 的媒体

| 风险 | 等级 | 说明 |
|---|---|---|
| 图片缺失 | **低** | 无 `uniqueid` 记录的媒体无法提供 TMDB 图片 |

**决策**：
- 图片方法返回 `None`，通知消息不配图（与现有逻辑兼容）
- 不影响查重和同步功能

### 5.3 路径不一致

| 风险 | 等级 | 说明 |
|---|---|---|
| 刷新逻辑失效 | **低** | `refresh_library_by_items()` 空实现，下载完成后不会通知 Kodi 扫描 |

**决策**：
- 接受此限制，在文档中注明：Kodi 模式不支持自动刷新，需用户手动在 Kodi 中更新库
- 后续可考虑通过 OS 文件系统事件或独立脚本触发 Kodi 扫描（非本计划范围）

### 5.4 是否跳过本地 SQLite 同步

| 方案 | 优缺点 |
|---|---|
| **A: 同步到 SQLite**（推荐） | 与现有架构一致，`check_item_exists()` 无需特殊处理；MySQL 挂不影响已同步数据 |
| B: 实时查 MySQL | 需在 `MediaServer.check_item_exists()` 加 Kodi 分支，破坏通用层一致性 |

**决策**：采用方案 A，保留同步逻辑。Kodi MySQL 查询比 HTTP API 快，同步成本很低。

### 5.5 `get_resume` / `get_latest` 是否支持

`MediaServer.get_resume()` 和 `get_latest()` 直接调用客户端方法（非抽象方法）。

| 能力 | 现状 | 决策 |
|---|---|---|
| `get_resume`（继续观看） | Kodi 无跨设备播放进度同步，返回 `[]` | **第一版空实现** |
| `get_latest`（最近添加） | 可通过 MySQL `files.dateAdded` 排序查询实现 | **第一版空实现，标注为 P1 增强** |

**决策**：第一版两者均空实现，确保不报错。`get_latest` 在 Phase 4 中可通过 `files.dateAdded` 联查 `movie`/`tvshow`/`episode` 实现，作为后续增强项。

> **理由**：`get_resume` 依赖 Kodi 的播放状态（`player` 表），而 Kodi 未启动时无实时播放数据；`get_latest` 虽然可从 MySQL 的 `dateAdded` 获取，但 `MediaServer` 层的调用链路需要完整测试，第一版优先保证核心同步和查重功能。

---

## 6. 验收标准

- [ ] 在 `app/mediaserver/client/` 下新增 `kodi.py`，带 `client_id = "kodi"`
- [ ] `SubmoduleHelper` 自动加载 Kodi 类，无需修改 `media_server.py`
- [ ] Web 设置页可配置 Kodi MySQL 连接参数，测试连接按钮返回成功
- [ ] `sync_mediaserver()` 可将 Kodi MySQL 中的电影/剧集数据同步到本地 `MEDIASYNCITEMS`
- [ ] `check_item_exists()` 对 Kodi 同步的数据生效，可正确识别已存在媒体
- [ ] 图片通过 TMDB ID 获取，媒体详情页和库视图中 Kodi 媒体可显示海报/背景图（通知消息因无 Webhook 不可触发）
- [ ] 不支持的方法（刷新、播放链接、Webhook）做空实现，不报错
- [ ] 单元测试覆盖 `get_movies`, `get_tv_episodes`, `get_items`, `get_medias_count`

---

## 7. 附录

### 7.1 核心 SQL 参考

```sql
-- 电影列表（含路径和外部ID）
-- movie 无 idPath，通过 movie.idFile -> files.idPath -> path 关联
-- parent 即 path.idPath，用 %s 占位（PyMySQL 参数风格）
SELECT
    m.idMovie, m.c00 AS title, m.premiered, m.c16 AS original_title,
    p.strPath, f.strFilename,
    (SELECT value FROM uniqueid WHERE media_id = m.idMovie AND media_type = 'movie' AND type = 'tmdb' LIMIT 1) AS tmdbid,
    (SELECT value FROM uniqueid WHERE media_id = m.idMovie AND media_type = 'movie' AND type = 'imdb' LIMIT 1) AS imdbid
FROM movie m
JOIN files f ON m.idFile = f.idFile
JOIN path p ON f.idPath = p.idPath
WHERE f.idPath = %s;

-- 剧集列表（tvshow 无 idPath，通过 tvshowlinkpath 关联）
-- parent 即 path.idPath，用 %s 占位
SELECT
    t.idShow, t.c00 AS title, t.c05 AS premiered, t.c09 AS original_title,
    (SELECT value FROM uniqueid WHERE media_id = t.idShow AND media_type = 'tvshow' AND type = 'tmdb' LIMIT 1) AS tmdbid,
    (SELECT value FROM uniqueid WHERE media_id = t.idShow AND media_type = 'tvshow' AND type = 'imdb' LIMIT 1) AS imdbid
FROM tvshow t
JOIN tvshowlinkpath tlp ON t.idShow = tlp.idShow
WHERE tlp.idPath = %s;

-- 某剧集的集信息（PyMySQL 参数风格）
SELECT c12 AS season, c13 AS episode, c00 AS title
FROM episode
WHERE idShow = %s AND c12 = %s;

-- 媒体数量统计
SELECT
    (SELECT COUNT(*) FROM movie) AS movie_count,
    (SELECT COUNT(*) FROM tvshow) AS tv_count;

-- 路径/library 推断（区分电影/剧集路径）
SELECT DISTINCT p.idPath, p.strPath, 'movie' AS media_type
FROM path p
JOIN files f ON p.idPath = f.idPath
JOIN movie m ON f.idFile = m.idFile
UNION
SELECT DISTINCT p.idPath, p.strPath, 'tv' AS media_type
FROM path p
JOIN tvshowlinkpath tlp ON p.idPath = tlp.idPath;
```

### 7.2 Kodi 版本与数据库名对照

| Kodi 版本 | 数据库名 | 说明 |
|---|---|---|
| Kodi 18 (Leia) | `MyVideos116` | |
| Kodi 19 (Matrix) | `MyVideos119` | |
| Kodi 20 (Nexus) | `MyVideos121` | |
| Kodi 21 (Omega) | `MyVideos131` | |
