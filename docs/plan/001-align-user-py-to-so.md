# Plan 001: user.py 功能对齐至 .so 版本

> 目标：将 `web/backend/user.py`（基础版）功能补全，使其与 `user.cpython-310-x86_64-linux-gnu.so`（迭代版）行为一致，支持 Python 3.10/3.12 双版本运行。认证系统将在本次迭代中完整移除，所有用户视为已认证（level=2）。

---

## 一、项目背景

### 1.1 nas-tools 是什么

nas-tools 是一个 NAS 媒体管理工具，提供 Web UI 用于管理 PT（Private Tracker）站点、自动订阅、下载、媒体整理等功能。项目基于 Flask + Flask-Login 构建 Web 层。

### 1.2 为什么需要替换 .so 文件

原始项目 alpha-86/nas-tools 将 `web/backend/user.py` 通过 Cython 编译为 `.so`（`user.cpython-310-x86_64-linux-gnu.so`），以保护站点加密密钥和配置数据。**问题：** Cython 编译的 `.so` 只能在匹配的 Python 主版本上加载（3.10 的 .so 无法在 3.12 上运行）。

当前 Docker 镜像使用 Python 3.12，无法加载该 .so。因此需要将其逆向还原为纯 Python 实现。

### 1.3 两个版本的来源关系

| 版本 | 来源 | 说明 |
|------|------|------|
| `user.py`（基础版） | GitHub fork `linyuan0213/nas-tools` | 原始开源版本，仅含基础用户管理，221 行 |
| `.so`（迭代版） | alpha-86/nas-tools 仓库 | 在基础版上大幅迭代，增加了站点加密、索引器配置、认证系统等，约 2200 行等价 Python |

**关键理解：** .so 不是简单的"方法增加"，而是对原有方法的逻辑也做了迭代。同名方法的行为可能不同。

### 1.4 .so 的内部架构

`.so` 包含 3 个类，采用委托模式：

```
User（对外接口类，被 Flask-Login 使用）
  ├─ __systemconfig: SystemConfig 实例（系统配置）
  ├─ __admin_user: 管理员用户信息
  ├─ __user_uuid: 设备唯一标识
  └─ 委托 → WlI5bfacg2（核心实现类，名称混淆）
       ├─ __user_uuid: UUID
       ├─ __brushconf: 刷流配置缓存
       ├─ 站点数据（从 user.sites.bin 解密加载）
       └─ 加密体系（Fernet + AES + nexusphp_encrypt）

IndexerConf（数据类，表示单个索引器配置）
```

**本项目将 `WlI5bfacg2` 重命名为 `SiteConfigManager`**（认证逻辑移除后，其核心职责是"加载站点配置数据并提供查询接口"）。

### 1.5 加密数据文件

`web/backend/user.sites.bin`（779KB）是 Fernet 加密的 JSON 文件（`gAAAAAB` 前缀），包含所有 PT 站点的配置数据（URL、Cookie、UA、规则等）。`SiteConfigManager` 在运行时解密此文件获取站点信息。

加密密钥来源（从 .so 逆向提取的硬编码常量）：
- **AES key**: `0f941adc1ca38b0d`
- **IV/nonce**: `3pEeF0dx5IT7Seo2`
- **Hash**: `45b0433d77e880c4547905abc000ec08`
- **Fernet key**: 从 AES key 派生（需逆向确认具体派生方式）

### 1.6 认证系统：确认需要完整移除

原始 .so 包含一套 PT 站点合作认证系统（UUID 注册、向合作站点 API 发送认证请求等），**本次迭代将完整移除该系统**。

**核心策略：所有用户 `level` 统一设为 2**

通过将 `level` 统一设为 2，认证相关的 UI 和逻辑将自动失效，无需修改模板或 JS 文件：

| 认证组件 | 位置 | `level=2` 时的行为（预期） |
|---------|------|-------------------|
| 认证弹窗自动弹出 | `navigation.html:1225` — `{% elif current_user.level == 1 %}` | 条件不满足，不弹出 |
| 导航栏认证按钮 | `navbar/index.js:162` — `layout_userlevel > 1` | 走 else 分支，显示版本信息而非认证按钮 |
| 认证弹窗 HTML | `navigation.html:1123-1167` | `get_authsites` 返回 `{}`，弹窗内容为空 |
| `check_user` 方法 | `action.py:4763` | 直接返回 `(True, "")` |
| 插件权限过滤 | `plugin_manager.py:230-231` — `plugin.auth_level > auth_level` | `level=2` ≥ 所有插件的 `auth_level`(1或2)，全部可见 |
| 基础设置页面 | `setting/basic.html:433,611` — `level >= 2` | 条件满足，显示完整设置 |
| 启动时认证 | `run.py:107` — `WebAction.auth_user_level()` | 移除此调用 |

**将要移除的逻辑（不实现）：**
- UUID 生成/注册（`__random_uuid`、`__register_uuid`）
- 合作站点认证请求（13 个 API 端点，见附录 C）
- `__requestauth` / `__get_playload` / `__check_result`
- `get_auth_level`
- `get_uuid`

**需要保留的空壳方法（向后兼容，避免调用方报错）：**
- `check_user(site, params)` → 返回 `(True, "")`
- `get_authsites()` → 返回 `{}`

**需要同步修改的调用方：**
- `run.py:107` — 移除 `WebAction.auth_user_level()` 启动调用

### 1.7 level 属性在系统中的作用

`level` 是用户等级属性，控制功能可见性：

| level 值 | 含义 | 影响 |
|---------|------|------|
| 1 | 未认证用户 | 导航页弹出认证弹窗；导航栏显示认证按钮；插件按 `auth_level` 过滤 |
| 2 | 已认证用户 | 无认证弹窗；显示版本信息；基础设置完全可见；所有插件可见 |
| 99 | 超级管理员（frostyleave fork） | 不采用 |

插件的 `auth_level` 定义（来自 `app/plugins/modules/`）：
- `auth_level = 1`：autobackup, chinesesubfinder, customreleasegroups, customization, opensubtitles, customhosts
- `auth_level = 2`：autosignin, cookiecloud, libraryrefresh, speedlimiter, autosub, movielike, doubanrank

---

## 二、Flask-Login 集成与数据流

### 2.1 User 类与 Flask-Login 的关系

Flask-Login 通过 `UserMixin` 提供会话管理。关键集成点：

```python
# web/main.py:100-102 — user_loader 回调
@LoginManager.user_loader
def load_user(user_id):
    return User().get(user_id)  # 返回 User 对象或 None

# web/main.py:185-191 — 登录流程
user_info = User().get_user(username)     # 返回 User 对象
if user_info.verify_password(password):   # 校验密码
    login_user(user_info)                 # Flask-Login 创建会话
```

**`current_user` 代理对象：** Flask-Login 在每个请求中将当前登录用户的 `User` 实例注入为 `current_user`。模板中通过 `CurrentUser=current_user` 传递。

### 2.2 模板上下文变量流转

| 变量 | 设置位置 | 来源方法 | 模板使用方式 |
|------|---------|---------|------------|
| `CurrentUser` | `main.py:223` | Flask-Login `current_user` | `.level`, `.admin`, `.name`, `.username`, `.pris`, `.search` |
| `Menus` | `main.py:219,237` | `WebAction().get_user_menus().get("menus")` → `current_user.get_usermenus(ignore=ignore)` | `navigation.html:1242` 遍历渲染侧边栏菜单 |
| `TopMenus` | `main.py:975,979` | `WebAction().get_top_menus().get("menus")` → `current_user.get_topmenus()` | `setting/users.html:84` 渲染权限 checkbox |
| `CooperationSites` | `main.py:218,235` | `current_user.get_authsites()` | `navigation.html:1136,1142` 渲染认证站点下拉框（`.items()` 遍历） |
| `Services` | `main.py:679` | `current_user.get_services()` | `service()` 路由中用 key 检查（`"rssdownload" in Services`） |

### 2.3 ignore 参数流转

`get_usermenus` 的 `ignore` 参数由 `web/action.py:4725-4741` 的 `get_user_menus()` 方法决定：

```python
def get_user_menus():
    ignore = []
    # 查询最早加入PT站的时间，不足一个月则隐藏刷流任务
    first_pt_site = SiteUserInfo().get_pt_site_min_join_date()
    if not first_pt_site or not StringUtils.is_one_month_ago(first_pt_site):
        ignore.append('brushtask')
    menus = current_user.get_usermenus(ignore=ignore)
    return {"code": 0, "menus": menus, "level": current_user.level}
```

`ignore` 目前只有 `'brushtask'` 一个值，用于隐藏新用户的刷流任务菜单。

### 2.4 权限字符串（pris）机制

`pris` 是逗号分隔的中文菜单名字符串，控制用户可访问的菜单：

```
"我的媒体库,资源搜索,探索,站点管理,订阅管理,下载管理,媒体整理,服务,系统设置"
```

- 管理员用户的 `pris` 包含所有 9 个顶级菜单名
- 普通用户的 `pris` 由管理员在"用户管理"页面通过 checkbox 分配
- `get_usermenus` 用 `pris` 从 `MENU_CONF` 中筛选菜单
- 模板 `navigation.html:107,112,117,122` 用 `pris` 做底部导航栏权限判断：`{% if "我的媒体库" in CurrentUser.pris %}`

### 2.5 admin_users 与 login_password 说明

```python
self.admin_users = [{
    "id": 0,
    "admin": 1,
    "name": Config().get_config('app').get('login_user'),
    "password": Config().get_config('app').get('login_password')[6:],  # [6:] 跳过 "pbkdf2:" 前缀
    "pris": "我的媒体库,资源搜索,探索,站点管理,订阅管理,下载管理,媒体整理,服务,系统设置",
    "level": 2,
    'search': 1
}]
```

- `admin_users` 是内存中的管理员用户列表（仅含 config.yaml 中配置的默认管理员）
- `login_password` 在 config.yaml 中存储为 werkzeug hash 格式（如 `pbkdf2:sha256:...`），`[6:]` 跳过 `pbkdf2:` 前缀以适配 `check_password_hash`
- 数据库中的普通用户通过 `dbhelper.get_users()` 查询 `CONFIGUSERS` 表

---

## 三、方法详细对比

### 3.1 User 类属性对比

| 属性 | user.py | .so | 差异说明 |
|------|:-------:|:---:|---------|
| `dbhelper` | ✅ DbHelper 实例 | ❌ 不存在 | .so 不使用数据库 helper（仅 `get_users`/`add_user`/`delete_user` 需要） |
| `admin_users` | ✅ 列表，从 Config 读取 | `__admin_user` 私有属性 | .so 用私有属性存储 |
| `id` | ✅ 来自 user dict | ✅ | 一致 |
| `admin` | ✅ 来自 user dict | ✅ | 模板中用于判断 `layout-useradmin`（`navbar/index.js:77,161`） |
| `username` | ✅ 来自 user dict | `name` | 属性名可能不同 |
| `password_hash` | ✅ 来自 user dict | ✅ PASSWORD | 一致 |
| `pris` | ✅ 来自 user dict | ✅ PRIS | 权限字符串，逗号分隔中文菜单名 |
| `level` | ✅ 来自 user dict | ✅ | **统一设为 2**（认证移除） |
| `search` | ✅ 来自 user dict | ✅ | 模板中用于 `layout-search` 属性 |
| `__systemconfig` | ❌ | ✅ SystemConfig 实例 | 新增，用于读写系统配置 |
| `__user_uuid` | ❌ | ✅ 设备 UUID | 认证相关，移除 |

### 3.2 User 类方法对比

> **说明：** "需迭代"表示同名方法在 .so 中有逻辑变化；"缺失"表示 user.py 中没有。"❓" 表示 .so 中未通过 strings 检测到，但可能存在于混淆后的代码中。

| 方法 | user.py | .so | 调用者 | 实现策略 |
|------|:-------:|:---:|--------|---------|
| `__init__` | ✅ | ✅ | 所有实例化 | **需迭代**：初始化 `SiteConfigManager`，`level` 统一设为 2 |
| `get_id` | ✅ | ❓ | Flask-Login 内部 | 保留不变 |
| `get` | ✅ | ❓ | `main.py:102` (user_loader) | 保留不变，`level` 改为 2 |
| `get_user` | ✅ | ❓ | `main.py:185,297`; `apiv1.py:90,126` | 保留不变，`level` 改为 2 |
| `verify_password` | ✅ | ✅ | `main.py:189`; `apiv1.py:94` | 保留不变（都用 `check_password_hash`） |
| `get_pris` | ✅ | ❌ | 内部 `get_usermenus` | 保留不变 |
| `as_dict` | ❌ | ✅ | **当前无外部调用者** | 新增，返回 `{id, name, pris}` |
| `get_users` | ✅ | ❓ | `action.py:3930` | 保留不变 |
| `add_user` | ✅ | ❓ | `action.py:1698` | 保留不变 |
| `delete_user` | ✅ | ❓ | `action.py:1700` | 保留不变 |
| `get_topmenus` | ✅ | ✅ | `action.py:4750` → `users.html` | **需迭代**：委托 `SiteConfigManager.get_topmenus()` |
| `get_usermenus` | ✅ | ✅ | `action.py:4736` → `navigation.html` | **需迭代且有 bug**：委托 `SiteConfigManager.get_menus(ignore)` |
| `get_services` | ✅ | ✅ | `main.py:679` | **保持硬编码** `SERVICE_CONF` |
| `get_authsites` | ❌ | ✅ | `main.py:218` → `navigation.html` | **新增空壳**：返回 `{}` |
| `get_indexer` | ❌ | ✅ | `builtin.py:75,101,121` | **新增**：委托 `SiteConfigManager`，返回 `IndexerConf` |
| `get_brush_conf` | ❌ | ✅ | `siteconf.py:93,94` | **新增**：委托 `SiteConfigManager` |
| `get_public_sites` | ❌ | ✅ | `builtin.py:120` | **新增**：委托 `SiteConfigManager` |
| `check_user` | ❌ | ✅ | `action.py:4763` | **新增空壳**：返回 `(True, "")` |

### 3.3 同名方法逻辑差异详解

#### `__init__`

```python
# user.py 当前实现
def __init__(self, user=None):
    self.dbhelper = DbHelper()
    if user:
        self.id = user.get('id')
        self.admin = user.get("admin")
        ...
    self.admin_users = [{
        "id": 0, "admin": 1,
        "name": Config().get_config('app').get('login_user'),
        "password": Config().get_config('app').get('login_password')[6:],
        "pris": "我的媒体库,资源搜索,探索,站点管理,订阅管理,下载管理,媒体整理,服务,系统设置",
        "level": 2, 'search': 1
    }]

# 迭代后
# - 保留 DbHelper（get_users/add_user/delete_user 需要）
# - 保留 admin_users 初始化
# - 所有用户 level 统一为 2
# - 新增 SiteConfigManager 实例初始化（self._site_config = SiteConfigManager()）
```

#### `get_topmenus`

```python
# user.py 当前实现
def get_topmenus(self):
    return self.admin_users[0]["pris"].split(",")
    # 返回固定列表：["我的媒体库","资源搜索","探索","站点管理","订阅管理","下载管理","媒体整理","服务","系统设置"]

# 迭代后：委托 SiteConfigManager.get_topmenus()
# 返回格式不变（list of str），模板 users.html 直接遍历渲染 checkbox
```

#### `get_usermenus`（**有 bug，需修复**）

```python
# user.py 当前实现
def get_usermenus(self, ignore=None):
    user_pris_list = self.get_pris().split(",")
    for menu_key, menu_value in MENU_CONF.items():
        if menu_value.get('page', 'null') in ignore:
            MENU_CONF.pop(menu_key)  # BUG: 修改全局变量 + 遍历中 pop
        for index, page in enumerate(menu_value.get('list', [])):
            if page['page'] in ignore:
                MENU_CONF[menu_key]['list'].pop(index)  # BUG: 遍历中 pop
    menu_list = list(itemgetter(*user_pris_list)(MENU_CONF))
    return menu_list

# BUG：
# 1. MENU_CONF 是模块级全局变量，pop() 永久删除菜单项
# 2. 遍历中修改 dict 会导致 RuntimeError 或跳过元素
# 3. 单个匹配时 itemgetter 返回 dict 而非 list

# 迭代后：委托 SiteConfigManager.get_menus(ignore)
# 内部使用深拷贝操作，不修改原始 MENU_CONF
```

#### `get_services`

```python
# user.py 当前实现（保持不变）
def get_services(self):
    return SERVICE_CONF
    # 返回硬编码的服务配置 dict，key 为服务 ID（如 'rssdownload', 'pttransfer'）
    # 模板通过 key 检查存在性：`"rssdownload" in Services`

# 决策：保持硬编码。理由：
# 1. 动态实现需引入 Sync/TorrentRemover/PluginManager 等重量级依赖
# 2. user.py 在 Flask-Login user_loader 中被频繁调用，重量级初始化影响性能
# 3. SERVICE_CONF 的 state/time 字段是静态默认值，不影响功能
# 4. mysll/0xforee fork 的动态实现（~250行）可作为后续增强参考
```

---

## 四、MENU_CONF 结构说明

`MENU_CONF` 是模块级全局字典（`web/backend/user.py:9-97`），定义了完整的侧边栏菜单结构：

```python
MENU_CONF = {
    '我的媒体库': {                        # 顶级菜单名（也是 pris 的值）
        'name': '我的媒体库',
        'level': 1,                       # 权限等级（1=基础，2=高级）
        'page': 'index',                  # 页面标识（用于 ignore 过滤）
        'icon': '<svg>...</svg>'          # SVG 图标
    },
    '探索': {
        'name': '探索',
        'level': 2,
        'list': [                         # 子菜单列表
            {'name': '榜单推荐', 'level': 2, 'page': 'ranking', 'icon': '...'},
            {'name': '豆瓣电影', 'level': 2, 'page': 'douban_movie', 'icon': '...'},
            {'name': 'BANGUMI', 'level': 2, 'page': 'bangumi', 'icon': '...'},
            # ... 共 6 个子菜单
        ]
    },
    '资源搜索': {'name': '资源搜索', 'level': 2, 'page': 'search', 'icon': '...'},
    '站点管理': {'name': '站点管理', 'level': 2, 'list': [...]},  # 4 个子菜单
    '订阅管理': {'name': '订阅管理', 'level': 2, 'list': [...]},  # 4 个子菜单
    '下载管理': {'name': '下载管理', 'level': 2, 'list': [...]},  # 3 个子菜单
    '媒体整理': {'name': '媒体整理', 'level': 1, 'list': [...]},  # 4 个子菜单
    '服务': {'name': '服务', 'level': 1, 'page': 'service', 'icon': '...'},
    '系统设置': {
        'name': '系统设置',
        'also': '设置',                   # 别名（用于权限匹配）
        'level': 1,
        'list': [...]                     # 11 个子菜单
    }
}
```

**共 9 个顶级菜单**，对应 `pris` 权限字符串中的值。每个菜单可有 `page`（叶子页面）或 `list`（子菜单列表），但不会同时存在。

### 4.1 SERVICE_CONF 结构说明

```python
SERVICE_CONF = {
    'rssdownload': {'name': '电影/电视剧订阅', 'svg': '...', 'color': 'blue', 'level': 2},
    'subscribe_search_all': {'name': '订阅搜索', 'svg': '...', 'color': 'blue', 'level': 2},
    'pttransfer': {'name': '下载文件转移', 'svg': '...', 'color': 'green', 'level': 2},
    'sync': {'name': '目录同步', 'time': '实时监控', 'svg': '...', 'color': 'orange', 'level': 1},
    'blacklist': {'name': '清理转移缓存', 'time': '手动', 'state': 'OFF', 'svg': '...', 'color': 'red', 'level': 1},
    'rsshistory': {'name': '清理RSS缓存', 'time': '手动', 'state': 'OFF', 'svg': '...', 'color': 'purple', 'level': 2},
    'nametest': {'name': '名称识别测试', 'time': '', 'state': 'OFF', 'svg': '...', 'color': 'lime', 'level': 1},
    'ruletest': {'name': '过滤规则测试', 'time': '', 'state': 'OFF', 'svg': '...', 'color': 'yellow', 'level': 2},
    'nettest': {'name': '网络连通性测试', 'time': '', 'state': 'OFF', 'svg': '...', 'color': 'cyan', 'targets': ModuleConf.NETTEST_TARGETS, 'level': 1},
    'backup': {'name': '备份&恢复', 'time': '', 'state': 'OFF', 'svg': '...', 'color': 'green', 'level': 1},
    'processes': {'name': '系统进程', 'time': '', 'state': 'OFF', 'svg': '...', 'color': 'muted', 'level': 1}
}
```

模板 `service()` 路由中用 key 检查：`if "rssdownload" in Services:` 来决定是否渲染对应的服务卡片。

---

## 五、IndexerConf 类规范

`.so` 中的 `IndexerConf` 仅含 `__init__`，是纯数据类。

### 5.1 属性列表

| 属性 | 类型 | 说明 | 调用者使用方式 |
|------|------|------|--------------|
| `id` | str | 索引器 ID | `builtin.py:112,122` 哈希映射过滤 |
| `name` | str | 索引器名称 | `builtin.py:116` 显示用（可被覆盖） |
| `url` | str | 索引器 URL | 核心标识 |
| `domain` | str | 索引器域名（含 scheme） | `builtin.py:114,124` 去重；`_spider.py` 构造搜索 URL；从 `url` 派生 |
| `search` | dict/bool | 搜索路径配置 | `_render_spider.py:48` — `.get('paths', [{}])[0].get('path', '')` **注意：不是 bool，是 dict** |
| `proxy` | bool | 是否使用代理 | `_spider.py:127`, `_torrentleech.py:19` |
| `render` | bool | 是否需要浏览器渲染 | `_spider.py:118` 决定是否用 Selenium/Chrome |
| `cookie` | str | 站点 Cookie | `_spider.py:130`, `_render_spider.py:70` 请求认证 |
| `ua` | str | User-Agent | `_spider.py:124`, `_torrentleech.py:35` |
| `token` | str | API Token | API 站点认证用 |
| `order` | int | 排序权重 | 结果排序 |
| `pri` | bool | 是否为私有站点 | `builtin.py:81,107` |
| `rule` | int | 规则 ID | `builtin.py:153-154` 传递过滤规则 |
| `public` | bool | 是否公开站点 | `_base.py:103` 与 `pri` 互补 |
| `builtin` | bool | 是否内置站点 | 38 个内置站点标记 |
| `tags` | list | 标签列表 | 站点分类标签 |
| `category` | str | 分类 | `_spider.py:115` |

### 5.2 调用方代码参考

`app/indexer/client/builtin.py` 中的调用模式：

```python
# 私有站点（行 75-84）
return self.user.get_indexer(url=url,
                             siteid=site.get("id"),
                             cookie=site.get("cookie"),
                             ua=site.get("ua"),
                             name=site.get("name"),
                             rule=site.get("rule"),
                             pri=site.get('pri'),
                             public=False,
                             proxy=site.get("proxy"),
                             render=render)

# 公开站点（行 121）
indexer = self.user.get_indexer(url=site_url)

# 后续使用：
# indexer.id        — 哈希映射过滤（行 112, 122）
# indexer.domain    — 去重判断（行 114, 124）
# indexer.name      — 赋值覆盖（行 116）
# indexer.rule      — 传递给过滤参数（行 153-154）
# indexer.public    — 种子过滤（_base.py:103）
# indexer.search    — 搜索路径构造（_render_spider.py:48）
# indexer.cookie    — HTTP 请求（_spider.py:130）
# indexer.ua        — HTTP 请求头（_spider.py:124）
# indexer.proxy     — 代理配置（_spider.py:127）
# indexer.render    — 浏览器渲染决策（_spider.py:118）
# indexer.category  — 分类信息（_spider.py:115）
```

### 5.3 domain 属性说明

`domain` 是从 `url` 派生的属性，包含 URL scheme 和 host，用于：
- 去重：同一个站点的多个 URL 只创建一个 indexer
- 构造搜索 URL：`self._indexer.domain + torrentspath`

```python
# 派生逻辑示例
from urllib.parse import urlparse
parsed = urlparse(url)
self.domain = f"{parsed.scheme}://{parsed.netloc}"
```

---

## 六、SiteConfigManager 类规范

原名 `WlI5bfacg2`（.so 中的混淆名称），重命名为 `SiteConfigManager`。

### 6.1 职责

1. 加载并解密 `user.sites.bin` 获取站点配置数据
2. 提供站点配置查询接口（索引器、刷流、公开站点）
3. 管理菜单和权限配置

### 6.2 方法清单

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `__init__` | - | - | 初始化，调用 `init_config` |
| `init_config` | - | - | 加载站点数据 |
| `__decrypt` | ciphertext: str | str | Fernet 解密 |
| `get_topmenus` | - | list[str] | 返回可分配的权限名称列表 |
| `get_menus` | ignore: list | list | 根据权限过滤 MENU_CONF，深拷贝后操作 |
| `get_topmenus_string` | - | str | 返回逗号分隔的权限字符串 |
| `get_indexer_conf` | url, siteid, cookie, ua, name, rule, pri, public, proxy, render | IndexerConf | 根据 URL/ID 查找站点配置并构造 IndexerConf |
| `get_brush_conf` | - | dict | 返回 `{url: xpath_config}` |
| `get_public_sites` | - | list[str] | 返回公开站点 URL 列表 |

> **注意：** 原 .so 中的 `get_authsites`、`check_user`、`get_auth_level`、`get_uuid`、`__register_uuid`、`__requestauth` 等认证相关方法在本次迭代中将全部不实现（见附录 B）。

### 6.3 加密体系

用于解密 `user.sites.bin`：

1. **Fernet**（主加密）：`user.sites.bin` 使用 Fernet 加密（`gAAAAAB` 前缀）
2. **AES key → Fernet key 派生**：硬编码 AES key `0f941adc1ca38b0d`，需逆向确认如何生成 Fernet key

可能的派生方式（按优先级尝试）：
- `base64.urlsafe_b64encode(bytes.fromhex("0f941adc1ca38b0d"))` → 32 bytes Fernet key
- PBKDF2 派生
- 直接 hex → base64 转换

> **注意：** AES 加密和 nexusphp_encrypt 仅用于原认证系统的 payload 构造，认证移除后不需要实现。

### 6.4 内置站点列表（38 个域名）

从 .so 逆向提取的内置站点域名列表：

```
1ptba.com, 52pt.site, audiences.me, avgv.cc, azusa.ru, carpt.net, ccfbits.org,
chdbits.co, cyanbug.net, discfan.net, et8.org, gainbound.net, hdatmos.club,
hdchina.org, hdfans.org, hdhome.org, hdmayi.com, hdsky.me, hdtime.org,
hdzone.me, hhanclub.top, ihdbits.me, jptv.club, kamept.com, leaves.red,
lemonhd.org, nanyangpt.com, ourbits.club, piggo.me, ptchina.org, pterclub.com,
pthome.net, ptsbao.club, sharkpt.net, skyeysnow.com, springsunday.net,
ubits.club, wintersakura.net, zmpt.cc
```

这些站点在 `get_indexer_conf` 中被标记为 `builtin=True`，在 `get_public_sites` 中作为公开站点返回。

---

## 七、已知 Bug（user.py 当前代码）

### Bug 1：`get_usermenus` 修改全局 MENU_CONF

**位置**：`web/backend/user.py:195-206`

**问题**：`MENU_CONF.pop(menu_key)` 直接修改模块级全局变量。每次调用永久删除菜单项，且遍历中 pop 导致不可预测行为。

**修复方案**：在 `SiteConfigManager.get_menus()` 中深拷贝 `MENU_CONF` 后操作。

### Bug 2：`get_user` 返回值与调用者不匹配

**位置**：`web/main.py:297`

**问题**：
- `main.py:189` 对返回值调用 `.verify_password(password)` — 期望 User 对象
- `main.py:297` 对返回值调用 `.get("pris")` — 期望 dict

当前 `get_user` 返回 User 对象，`User.get(user_id)` 签名是 `get(self, user_id)`，所以 `.get("pris")` 查找 id="pris" 的用户，返回 None。

**修复方案**：将 `main.py:297` 改为 `User().get_user(username).pris`。

### Bug 3：`add_user` 未哈希密码

**位置**：`web/backend/user.py:217`

**问题**：`add_user` 直接传原始密码给 `dbhelper.insert_user`，未用 `generate_password_hash`。

**影响**：新增用户密码以明文存储，无法通过 `check_password_hash` 验证。

---

## 八、GitHub Fork 调研结果

搜索了 GitHub 上 nas-tools 的相关 fork，找到了 4 个包含 `user.py` 的仓库：

| Fork | 行数 | get_authsites | check_user | WlI5bfacg2 | get_services | 参考价值 |
|------|-----:|:---:|:---:|:---:|:---:|:---:|
| frostyleave/nas-tools | 138 | `return []` 占位 | `return 1, ''` 占位 | - | 动态（从 Config） | User/UserManager 分离架构 |
| mysll/nts | 297 | `return {}` 占位 | `return True, ""` 占位 | - | **完整动态实现** | get_services 动态实现参考 |
| 0xforee/nas-tools-private | 795 | `return None` 占位 | - | - | **完整动态实现** | 完整菜单列表 + 动态服务 |
| JHBOY-ha/nas-tools-complement | 69 | - | - | - | - | 无参考价值 |

**关键结论：**
1. **.so 源码在 GitHub 上不存在** — `WlI5bfacg2`、`IndexerConf`、`user.sites.bin` 加解密没有任何公开 fork 实现
2. **`get_authsites` 和 `check_user` 在所有 fork 中都是空占位** — 确认只有 .so 有真正实现
3. **`mysll` 和 `0xforee` 的 `get_services` 有动态实现** — 但本轮采用硬编码方案，动态实现可作为后续增强参考
4. **`frostyleave` 采用 User + UserManager 分离架构** — 值得注意但本轮不采用

---

## 九、开发任务分解

### Phase 1：Bug 修复 + 基础设施（P0，可并行）

#### Task 1.1：新增 IndexerConf 数据类
- **文件**：`web/backend/user.py`
- **内容**：定义 `IndexerConf` 类，`__init__` 接收属性并存储
- **属性和默认值**：
  ```python
  def __init__(self, id="", name="", url="", domain="",
               search=False, proxy=False, render=False,
               cookie="", ua="", token="",
               order=0, pri=False, rule=None,
               public=False, builtin=False,
               tags=None, category=None):
  ```
- **注意**：`domain` 从 `url` 自动派生（如果未显式传入）；`search` 类型为 `dict` 或 `False`，不是 `bool`
- **验收**：`IndexerConf(id="1", name="test", url="http://example.com")` 正常实例化，`indexer.domain == "http://example.com"`

#### Task 1.2：修复 get_usermenus bug
- **文件**：`web/backend/user.py`
- **内容**：将 `MENU_CONF` 的操作改为深拷贝后操作（`copy.deepcopy(MENU_CONF)`）
- **验收**：连续多次调用 `get_usermenus` 不丢失菜单项

#### Task 1.3：修复 main.py:297 返回值不匹配
- **文件**：`web/main.py`
- **内容**：`User().get_user(username).get("pris")` → `User().get_user(username).pris`
- **验收**：资源搜索页面正常加载

#### Task 1.4：移除启动时认证调用
- **文件**：`run.py`
- **内容**：移除 `WebAction.auth_user_level()` 调用（行 107）
- **背景**：该调用在启动时向合作站点 API 发送认证请求，认证系统移除后不再需要
- **验收**：启动时不再执行认证流程

### Phase 2：SiteConfigManager 实现（P0，顺序执行）

#### Task 2.1：实现 SiteConfigManager 基础框架 + 配置加载
- **文件**：`web/backend/user.py`
- **新增 import**：`from cryptography.fernet import Fernet`、`import json`、`import os`
- **内容**：
  - 定义 `SiteConfigManager` 类
  - `__init__` / `init_config`：初始化
  - `__decrypt`：Fernet 解密实现
  - 加载 `user.sites.bin`（与 `user.py` 同目录，路径 `os.path.join(os.path.dirname(__file__), 'user.sites.bin')`）
  - 解析解密后的 JSON 站点数据结构
- **不实现的方法**：认证相关方法（`get_auth_level`、`get_uuid`、`__register_uuid`、`__requestauth` 等）均不在本类中实现，详见附录 B
- **依赖**：`cryptography.fernet`（已在 `requirements.txt`）
- **技术风险**：Fernet key 的派生方式需从 AES key `0f941adc1ca38b0d` 确认
- **验收**：能正确解密 `user.sites.bin` 并解析 JSON，打印顶层 key 确认结构

#### Task 2.2：实现菜单和权限方法
- **文件**：`web/backend/user.py`
- **内容**：
  - `get_topmenus()`：返回中文权限名列表（`["我的媒体库", "探索", "资源搜索", ...]`）
  - `get_topmenus_string()`：返回逗号分隔的权限字符串
  - `get_menus(ignore)`：深拷贝 `MENU_CONF` 后按权限过滤，支持 ignore 排除 `page` 匹配的菜单项和子菜单项
- **验收**：返回值格式与 `users.html` 和 `navigation.html` 模板兼容

#### Task 2.3：实现站点查询方法
- **文件**：`web/backend/user.py`
- **内容**：
  - `get_indexer_conf(url, siteid, cookie, ua, name, rule, pri, public, proxy, render)`：从站点数据查找配置，构造并返回 `IndexerConf`
  - `get_brush_conf()`：返回 `{url: xpath_config}` dict
  - `get_public_sites()`：返回公开站点 URL 列表
- **验收**：`app/indexer/client/builtin.py` 和 `app/sites/siteconf.py` 中的调用正常工作

### Phase 3：User 类改造（P0，依赖 Phase 2）

#### Task 3.1：修改 User.__init__
- **文件**：`web/backend/user.py`
- **内容**：
  - 初始化 `SiteConfigManager` 实例
  - 保留 `DbHelper` 和 `admin_users` 初始化
  - 所有用户 `level` 统一设为 2
- **验收**：`User()` 实例化不报错

#### Task 3.2：User 类新增方法 + 修改现有方法（含认证移除）
- **文件**：`web/backend/user.py`
- **新增空壳方法（替代 .so 中的认证逻辑）**：
  - `check_user(site, params)` → 返回 `(True, "")`（原 .so 通过合作站点 API 校验，现跳过校验直接放行）
  - `get_authsites()` → 返回 `{}`（原 .so 返回含加密凭据的认证站点配置，现返回空字典使认证弹窗无内容）
- **新增委托方法**：
  - `as_dict()` → 返回 `{id, name, pris}` 字典
  - `get_indexer(...)` → 委托 `SiteConfigManager.get_indexer_conf(...)`
  - `get_brush_conf()` → 委托 `SiteConfigManager.get_brush_conf()`
  - `get_public_sites()` → 委托 `SiteConfigManager.get_public_sites()`
- **修改现有方法**：
  - `get_topmenus()` → 委托 `SiteConfigManager.get_topmenus()`
  - `get_usermenus(ignore)` → 委托 `SiteConfigManager.get_menus(ignore)`
- **保留不变**：`get_services()` 继续返回硬编码 `SERVICE_CONF`
- **验收**：所有方法可正常调用，返回值与调用者期望一致

### Phase 4：集成与回归（P0，依赖 Phase 1-3）

#### Task 4.1：依赖确认
- 确认 `cryptography` 在 `requirements.txt`（已有）
- 无新增依赖

#### Task 4.2：本地测试
- Python 3.12 venv 测试
- 验证菜单渲染正常（`get_usermenus`、`get_topmenus`）
- 验证索引器配置获取（`get_indexer`、`get_public_sites`）
- 验证刷流配置获取（`get_brush_conf`）
- 验证用户登录流程正常（`get`、`get_user`、`verify_password`）
- 验证认证弹窗不再弹出（`level=2`）
- 验证插件全部可见（`level=2` ≥ 所有 `auth_level`）

#### Task 4.3：Docker 构建测试
- 重建 Docker 镜像
- 容器内启动验证无 import 报错
- 访问 Web UI 验证菜单显示正常

---

## 十、任务依赖关系

```
Phase 1 (Task 1.1, 1.2, 1.3, 1.4)  ← 互不依赖，可并行
    ↓
Phase 2 (Task 2.1 → 2.2 → 2.3)      ← 2.2 依赖 2.1 的配置加载
    ↓                                    2.3 依赖 2.1 的站点数据解析
Phase 3 (Task 3.1 → 3.2)             ← 依赖 Phase 2 的 SiteConfigManager
    ↓
Phase 4 (Task 4.1, 4.2, 4.3)         ← 依赖 Phase 1-3 全部完成
```

---

## 十一、技术风险

| 风险 | 等级 | 说明 | 缓解措施 |
|------|------|------|---------|
| Fernet key 派生逻辑不明 | **高** | AES key 到 Fernet key 的派生方式需逆向确认 | 优先尝试 `base64.urlsafe_b64encode(bytes.fromhex("0f941adc1ca38b0d"))`；失败则尝试 PBKDF2；再失败则直接用 hex key 的 base64 |
| user.sites.bin 数据结构未知 | **中** | 解密后的 JSON 结构需确认 | 解密后打印顶层 key 和嵌套结构，逐步适配 |
| IndexerConf 的 search 属性类型 | **低** | `.so` 中 `search` 是 `dict`（搜索路径配置），不是 `bool` | `get_indexer_conf` 需从站点数据中提取正确的 dict 结构 |

---

## 十二、文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `web/backend/user.py` | **主要修改** | 新增 `IndexerConf`、`SiteConfigManager` 类；User 新增/修改方法；修复 bug；新增 import（`cryptography.fernet`, `json`, `copy`, `urllib.parse`）；预计新增 ~300 行 |
| `web/main.py` | 小修改 | 修复 `search()` 路由中 `.get("pris")` → `.pris`（行 297） |
| `run.py` | 小修改 | 移除 `WebAction.auth_user_level()` 调用（行 107） |
| `requirements.txt` | 不变 | `cryptography` 已存在 |
| `docs/plan/001-align-user-py-to-so.md` | 本文件 | 计划文档 |

---

## 附录 A：当前 user.py 的 imports

```python
from flask_login import UserMixin
from werkzeug.security import check_password_hash
from operator import itemgetter

from app.helper import DbHelper
from config import Config
from app.conf import ModuleConf
```

迭代后需要新增的 imports：
```python
import copy
import json
import os
from urllib.parse import urlparse
from cryptography.fernet import Fernet
```

## 附录 B：不实现的认证相关方法

以下是 .so 中存在但因本次迭代移除认证系统而不需要实现的方法：

| 类 | 方法 | 原功能 |
|---|---|---|
| SiteConfigManager | `get_auth_level` | 从 SystemConfig 读取认证等级 |
| SiteConfigManager | `get_uuid` | 获取设备 UUID |
| SiteConfigManager | `__random_uuid` | 生成随机 UUID（`uuid.uuid1()`） |
| SiteConfigManager | `__register_uuid` | 向 `nastool.org/user/register` 注册 |
| SiteConfigManager | `__encrypt` | Fernet 加密 |
| SiteConfigManager | `__requestauth` | 向合作站点发送认证请求 |
| SiteConfigManager | `__requestauth.__get_playload` | 构造加密请求体 |
| SiteConfigManager | `__requestauth.__check_result` | 校验认证响应 |
| SiteConfigManager | `get_authsites` | 返回认证站点配置（含加密凭据） |
| SiteConfigManager | `check_user` | 校验用户是否有合作站点认证 |
| User | `check_user` | 委托认证（改为返回 `(True, "")` 空壳） |
| User | `get_authsites` | 委托认证站点（改为返回 `{}` 空壳） |

## 附录 C：合作站点 API 端点（仅存档，不实现）

| 站点 | 认证端点 |
|------|---------|
| iyuu | `https://api.iyuu.cn/index.php?s=App.Api.Sites&version=2.0.0` |
| piggo | `https://api.piggo.me/ntapi.php` |
| sharkpt | `https://api.sharkpt.net/v1/user/auth` |
| audiences | `https://audiences.me/api.php?action=WyR5Zd6q` |
| 1ptba | `https://1ptba.com/api/nastools/approve` |
| hdfans | `https://hdfans.org/api/nastools/approve` |
| hhanclub | `https://hhanclub.top/api/nastools/approve` |
| leaves.red | `https://leaves.red/api/nastools/approve` |
| wintersakura | `https://wintersakura.net/api/nastools/approve` |
| pt.0ff.cc | `https://pt.0ff.cc/api/nastools/approve` |
| icc2022 | `https://www.icc2022.com/api/nastools/approve` |
| zmpt | `https://zmpt.cc/api/nastools/approve` |
| hddolby | `https://www.hddolby.com/api.php` |
