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
| `movie` | 电影 | `idMovie`, `c00`(标题), `c07`(年份), `c16`(原始标题) |
| `tvshow` | 剧集 | `idShow`, `c00`(标题), `c05`(年份), `c15`(原始标题) |
| `episode` | 单集 | `idEpisode`, `idShow`, `c00`(标题), `c12`(季号), `c13`(集号) |
| `seasons` | 季 | `idSeason`, `idShow`, `season`(季号) |
| `uniqueid` | 外部 ID 映射 | `media_id`, `media_type`, `type`('tmdb'/'imdb'), `value` |
| `files` | 文件 | `idFile`, `idPath`, `strFilename` |
| `path` | 路径 | `idPath`, `strPath` |

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
| `get_movies(title, year)` | `SELECT c00, c07 FROM movie WHERE ...` | |
| `get_tv_episodes(item_id, title, year, tmdbid, season)` | 联查 `tvshow` → `episode` | 无 `item_id` 时先按标题查 `idShow` |
| `get_no_exists_episodes()` | 同 Emby 模式：已有集号 → 算差集 | |
| `get_libraries()` | `SELECT DISTINCT strPath FROM path` 聚合 | 或从 `movie.idPath` / `tvshow.idPath` 推断 |
| `get_items(parent)` | `SELECT * FROM movie` / `tvshow` → yield 标准字典 | 包含 `uniqueid` 联查获取 tmdbid/imdbid |
| `get_play_url()` | 返回 `""` | 不支持 |
| `get_playing_sessions()` | 返回 `[]` | 不支持 |
| `get_webhook_message()` | 返回 `None` | 不支持 |
| `refresh_root_library()` | 返回 `False` | 不支持 |
| `refresh_library_by_items()` | 返回 `None` | 不支持 |
| `get_remote_image_by_id()` | 查 `uniqueid` 取 tmdbid → `Media().get_tmdb_backdrop()` / `get_tmdb_info()` | |
| `get_local_image_by_id()` | 同上 | 与 `get_remote_image_by_id` 行为一致 |
| `get_episode_image_by_id()` | 查 tvshow 的 tmdbid → `Media().get_episode_images()` | |

### 2.4 `get_items()` 返回的数据格式

`MediaServer.sync_mediaserver()` 会把 `get_items()` 的结果写入本地 SQLite。返回格式必须与其他服务器一致：

```python
yield {
    "id": movie.idMovie,           # Kodi 内部 ID
    "library": movie.idPath,       # 路径ID（作为 library 标识）
    "type": "Movie",               # Kodi 是 'Movie'，同步逻辑兼容
    "title": movie.c00,            # 标题
    "originalTitle": movie.c16,    # 原始标题
    "year": movie.c07,             # 年份
    "tmdbid": tmdb_id,             # 从 uniqueid 表查
    "imdbid": imdb_id,             # 从 uniqueid 表查
    "path": full_path,             # path.strPath + files.strFilename
    "json": str({...})             # 额外信息序列化（如 season/episode）
}
```

### 2.5 路径映射

Kodi `files` / `path` 表中的路径是 Kodi 所在机器的路径。如果 NAStools 与 Kodi 不在同一台机器/容器上，需要考虑路径映射转换（类似 Emby 的 `__get_emby_library_id_by_item` 逻辑）。

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
| 确认/安装 `pymysql` | `requirements.txt` | 如缺失则添加 |

### Phase 2: Kodi 客户端实现 [P0]

| 任务 | 文件 | 说明 |
|---|---|---|
| 新建 `Kodi` 类 | `app/mediaserver/client/kodi.py` | 继承 `_IMediaClient`，纯 MySQL 查询 |
| 实现基础方法 | `kodi.py` | `get_status`, `get_user_count`, `get_medias_count`, `get_movies` |
| 实现剧集方法 | `kodi.py` | `get_tv_episodes`, `get_no_exists_episodes` |
| 实现库遍历方法 | `kodi.py` | `get_libraries`, `get_items` |
| 实现图片方法 | `kodi.py` | `get_remote_image_by_id`, `get_local_image_by_id`, `get_episode_image_by_id` |
| 空实现不支持方法 | `kodi.py` | `get_play_url`, `get_playing_sessions`, `get_activity_log`, `get_webhook_message`, `refresh_root_library`, `refresh_library_by_items` |

### Phase 3: 测试与验证 [P1]

| 任务 | 文件 | 说明 |
|---|---|---|
| 单元测试 | `tests/test_kodi_mediaserver.py` | 模拟 MySQL 数据测试各方法返回格式 |
| 连接测试 | `kodi.py` | `get_status()` 连通性验证 |
| 同步测试 | `media_server.py` | 验证 `sync_mediaserver()` 可正常将 Kodi 数据写入 `MEDIASYNCITEMS` |
| 查重测试 | `media_server.py` | 验证 `check_item_exists()` 对 Kodi 数据生效 |
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

---

## 6. 验收标准

- [ ] 在 `app/mediaserver/client/` 下新增 `kodi.py`，带 `client_id = "kodi"`
- [ ] `SubmoduleHelper` 自动加载 Kodi 类，无需修改 `media_server.py`
- [ ] Web 设置页可配置 Kodi MySQL 连接参数，测试连接按钮返回成功
- [ ] `sync_mediaserver()` 可将 Kodi MySQL 中的电影/剧集数据同步到本地 `MEDIASYNCITEMS`
- [ ] `check_item_exists()` 对 Kodi 同步的数据生效，可正确识别已存在媒体
- [ ] 图片通过 TMDB ID 获取，通知消息中 Kodi 媒体可显示海报/背景图
- [ ] 不支持的方法（刷新、播放链接、Webhook）做空实现，不报错
- [ ] 单元测试覆盖 `get_movies`, `get_tv_episodes`, `get_items`, `get_medias_count`

---

## 7. 附录

### 7.1 核心 SQL 参考

```sql
-- 电影列表（含路径和外部ID）
SELECT
    m.idMovie, m.c00 AS title, m.c07 AS year, m.c16 AS original_title,
    p.strPath, f.strFilename,
    (SELECT value FROM uniqueid WHERE media_id = m.idMovie AND media_type = 'movie' AND type = 'tmdb' LIMIT 1) AS tmdbid,
    (SELECT value FROM uniqueid WHERE media_id = m.idMovie AND media_type = 'movie' AND type = 'imdb' LIMIT 1) AS imdbid
FROM movie m
JOIN files f ON m.idFile = f.idFile
JOIN path p ON f.idPath = p.idPath;

-- 剧集列表
SELECT
    t.idShow, t.c00 AS title, t.c05 AS year, t.c15 AS original_title,
    (SELECT value FROM uniqueid WHERE media_id = t.idShow AND media_type = 'tvshow' AND type = 'tmdb' LIMIT 1) AS tmdbid,
    (SELECT value FROM uniqueid WHERE media_id = t.idShow AND media_type = 'tvshow' AND type = 'imdb' LIMIT 1) AS imdbid
FROM tvshow t;

-- 某剧集的集信息
SELECT c12 AS season, c13 AS episode, c00 AS title
FROM episode
WHERE idShow = ? AND c12 = ?;

-- 媒体数量统计
SELECT
    (SELECT COUNT(*) FROM movie) AS movie_count,
    (SELECT COUNT(*) FROM tvshow) AS tv_count;
```

### 7.2 Kodi 版本与数据库名对照

| Kodi 版本 | 数据库名 | 说明 |
|---|---|---|
| Kodi 18 (Leia) | `MyVideos116` | |
| Kodi 19 (Matrix) | `MyVideos119` | |
| Kodi 20 (Nexus) | `MyVideos121` | |
| Kodi 21 (Omega) | `MyVideos131` | |
