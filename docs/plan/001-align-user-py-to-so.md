# Plan 001: user.py 功能对齐至 .so 版本

> 目标：将 `web/backend/user.py`（基础版）功能补全，使其与 `user.cpython-310-x86_64-linux-gnu.so`（迭代版）行为一致，支持 Python 3.10/3.12 双版本运行。

---

## 一、项目背景

### 1.1 nas-tools 是什么

nas-tools 是一个 NAS 媒体管理工具，提供 Web UI 用于管理 PT（Private Tracker）站点、自动订阅、下载、媒体整理等功能。项目基于 Flask + Flask-Login 构建 Web 层。

### 1.2 为什么需要替换 .so 文件

原始项目 alpha-86/nas-tools 将 `web/backend/user.py` 通过 Cython 编译为 `.so`（`user.cpython-310-x86_64-linux-gnu.so`），以保护站点加密密钥和认证逻辑。**问题在于：** Cython 编译的 `.so` 只能在匹配的 Python 主版本上加载（3.10 的 .so 无法在 3.12 上运行）。

当前 Docker 镜像使用 Python 3.12，无法加载该 .so。因此需要将其逆向还原为纯 Python 实现。

### 1.3 两个版本的来源关系

| 版本 | 来源 | 说明 |
|------|------|------|
| `user.py`（基础版） | GitHub fork `linyuan0213/nas-tools` | 原始开源版本，仅含基础用户管理，221 行 |
| `.so`（迭代版） | alpha-86/nas-tools 仓库 | 在基础版上大幅迭代，增加了站点加密、认证系统、索引器配置等，约 2200 行等价 Python |

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

### 1.5 加密数据文件

`web/backend/user.sites.bin`（779KB）是 Fernet 加密的 JSON 文件（`gAAAAAB` 前缀），包含所有 PT 站点的配置数据（URL、Cookie、UA、规则等）。`.so` 在运行时解密此文件获取站点信息。

加密密钥来源：
- **AES key**: `0f941adc1ca38b0d`（硬编码）
- **IV/nonce**: `3pEeF0dx5IT7Seo2`（硬编码）
- **Fernet key**: 从 AES key 派生（`cryptography.fernet`）
- **Hash**: `45b0433d77e880c4547905abc000ec08`

### 1.6 认证系统概述

`.so` 包含一套 PT 站点合作认证系统：
1. 生成设备 UUID 并注册到 `nastool.org/user/register`
2. 用户选择一个合作站点，提交 uid + passkey
3. 向合作站点 API 发送加密认证请求
4. 校验响应，更新认证等级

合作站点 API 端点（13 个）：

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

内置站点列表（38 个域名）：
1ptba.com, 52pt.site, audiences.me, avgv.cc, azusa.ru, carpt.net, ccfbits.org, chdbits.co, cyanbug.net, discfan.net, et8.org, gainbound.net, hdatmos.club, hdchina.org, hdfans.org, hdhome.org, hdmayi.com, hdsky.me, hdtime.org, hdzone.me, hhanclub.top, ihdbits.me, jptv.club, kamept.com, leaves.red, lemonhd.org, nanyangpt.com, ourbits.club, piggo.me, ptchina.org, pterclub.com, pthome.net, ptsbao.club, sharkpt.net, skyeysnow.com, springsunday.net, ubits.club, wintersakura.net, zmpt.cc

---

## 二、方法详细对比

### 2.1 User 类属性对比

| 属性 | user.py | .so | 差异说明 |
|------|:-------:|:---:|---------|
| `dbhelper` | ✅ DbHelper 实例 | ❌ 不存在 | .so 不使用数据库 helper |
| `admin_users` | ✅ 列表，从 Config 读取 | `__admin_user` 私有属性 | .so 用私有属性存储，初始化方式可能不同 |
| `id` | ✅ 来自 user dict | ✅ | 一致 |
| `admin` | ✅ 来自 user dict | ✅ | 一致 |
| `username` | ✅ 来自 user dict | `name`（来自字符串分析） | 属性名可能不同 |
| `password_hash` | ✅ 来自 user dict | ✅ PASSWORD | 一致 |
| `pris` | ✅ 来自 user dict | ✅ PRIS | 一致 |
| `level` | ✅ 来自 user dict | ✅ | 一致 |
| `search` | ✅ 来自 user dict | ✅ | 一致 |
| `__systemconfig` | ❌ | ✅ SystemConfig 实例 | .so 新增，用于读写系统配置 |
| `__user_uuid` | ❌ | ✅ 设备 UUID | .so 新增 |

### 2.2 User 类方法对比

> **重要说明：** "一致"表示行为基本相同；"需迭代"表示同名方法在 .so 中有逻辑变化；"缺失"表示 user.py 中没有。

| 方法 | user.py | .so | 调用者 | 差异说明 |
|------|:-------:|:---:|--------|---------|
| `__init__` | ✅ | ✅ | 所有实例化 | **需迭代**：.so 额外初始化 `WlI5bfacg2`、加载 SystemConfig、生成/获取 UUID |
| `get_id` | ✅ | ❓ 未检测到 | Flask-Login 内部 | 需保留，Flask-Login 要求 |
| `get` | ✅ | ❓ 未检测到 | `web/main.py:102` (user_loader) | 需保留，Flask-Login 的 `load_user` 调用 |
| `get_user` | ✅ | ❓ 未检测到 | `web/main.py:185,297`；`web/apiv1.py:90,126` | 需保留。**注意：** main.py:297 对返回值调用 `.get("pris")` 期望 dict，但 main.py:189 调用 `.verify_password()` 期望 User 对象，存在不一致 |
| `verify_password` | ✅ | ✅ | `web/main.py:189`；`web/apiv1.py:94` | **基本一致**：都用 `check_password_hash` |
| `get_pris` | ✅ | ❌ 移除 | 内部 `get_usermenus` | .so 移除此方法，改用 `as_dict` 或直接访问属性 |
| `as_dict` | ❌ | ✅ | **当前无外部调用者** | **新增**：返回 `{id, name, pris}` 字典。可能是为将来替代 `get_pris` 准备的 |
| `get_users` | ✅ | ❓ 未检测到 | `web/action.py:3930` | 需保留，返回数据库中的用户列表 |
| `add_user` | ✅ | ❓ 未检测到 | `web/action.py:1698` | 需保留。**注意：** user.py 直接传原始密码，.so 可能做了哈希处理 |
| `delete_user` | ✅ | ❓ 未检测到 | `web/action.py:1700` | 需保留 |
| `get_topmenus` | ✅ | ✅ | `web/action.py:4750` → `users.html` 模板 | **需迭代**：user.py 从 `admin_users[0]["pris"]` 分割；.so 委托 `WlI5bfacg2`，返回值格式可能不同 |
| `get_usermenus` | ✅ | ✅ | `web/action.py:4736` → `navigation.html` 模板 | **需迭代且有 bug**：详见 2.3 节 |
| `get_services` | ✅ | ✅ | `web/main.py:679` | **需迭代**：user.py 返回硬编码 `SERVICE_CONF`；.so 委托 `WlI5bfacg2`，可能返回扩展的服务配置 |
| `get_authsites` | ❌ | ✅ | `web/main.py:218` → `navigation.html` 模板 | **新增**：返回 `{SiteId: SiteAttr}` dict，模板用 `.items()` 遍历，SiteAttr 需有 `.name` 属性 |
| `get_indexer` | ❌ | ✅ | `app/indexer/client/builtin.py:75,101,121` | **新增**：接收 `url, siteid, cookie, ua, name, rule` 参数，返回 `IndexerConf` 对象 |
| `get_brush_conf` | ❌ | ✅ | `app/sites/siteconf.py:93,94` | **新增**：返回 `{url: xpath_config}` dict |
| `get_public_sites` | ❌ | ✅ | `app/indexer/client/builtin.py:120` | **新增**：返回公开站点 URL 列表 |
| `check_user` | ❌ | ✅ | `web/action.py:4763` | **新增**：接收 `(site, params)`，返回 `(state, msg)` 元组 |

### 2.3 同名方法逻辑差异详解

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
        "password": Config().get_config('app').get('login_password')[6:],  # 跳过 "pbkdf2:" 前缀
        "pris": "我的媒体库,资源搜索,探索,站点管理,订阅管理,下载管理,媒体整理,服务,系统设置",
        "level": 2, 'search': 1
    }]

# .so 的变化
# - 初始化 __systemconfig (SystemConfig 实例)
# - 初始化 WlI5bfacg2 辅助对象
# - 初始化 __user_uuid
# - 不再使用 DbHelper（或仅在部分方法中使用）
```

#### `get_topmenus`

```python
# user.py 当前实现
def get_topmenus(self):
    return self.admin_users[0]["pris"].split(",")
    # 返回固定列表：["我的媒体库","资源搜索","探索","站点管理","订阅管理","下载管理","媒体整理","服务","系统设置"]

# .so 的变化
# - 委托 WlI5bfacg2.get_topmenus()
# - 可能从 SystemConfig 或 user.sites.bin 中动态获取权限列表
# - 返回格式应该一致（list of str），因为模板 users.html 直接遍历
```

#### `get_usermenus`（**有 bug，需修复**）

```python
# user.py 当前实现
def get_usermenus(self, ignore=None):
    user_pris_list = self.get_pris().split(",")
    for menu_key, menu_value in MENU_CONF.items():
        if menu_value.get('page', 'null') in ignore:
            MENU_CONF.pop(menu_key)  # BUG: 修改正在遍历的 dict
        for index, page in enumerate(menu_value.get('list', [])):
            if page['page'] in ignore:
                MENU_CONF[menu_key]['list'].pop(index)  # BUG: 修改正在遍历的 list
    menu_list = list(itemgetter(*user_pris_list)(MENU_CONF))
    return menu_list

# BUG 说明：
# 1. MENU_CONF 是模块级全局变量，pop() 会永久删除菜单项
# 2. 遍历中修改 dict 会导致 RuntimeError 或跳过元素
# 3. 遍历中修改 list 的 pop(index) 会导致索引错位
# 4. 如果只有一个菜单匹配 user_pris_list，itemgetter 返回单个 dict 而非 list

# .so 的变化
# - 委托 WlI5bfacg2.get_menus(ignore)
# - 返回与模板兼容的菜单列表
# - 不应有上述 bug
```

#### `get_services`

```python
# user.py 当前实现
def get_services(self):
    return SERVICE_CONF
    # 返回硬编码的服务配置 dict

# .so 的变化
# - 委托 WlI5bfacg2.get_services()
# - 可能从 SystemConfig 或 user.sites.bin 中获取扩展的服务配置
# - 返回格式应兼容模板中的 key 检查（"rssdownload" in Services 等）
```

---

## 三、IndexerConf 类规范

`.so` 中的 `IndexerConf` 类仅包含 `__init__` 方法，是一个纯数据类。

### 3.1 属性列表

| 属性 | 类型 | 说明 | 调用者如何使用 |
|------|------|------|--------------|
| `id` | str | 索引器 ID | `builtin.py` 中用于哈希映射 |
| `name` | str | 索引器名称 | 显示用 |
| `url` | str | 索引器 URL | 核心标识 |
| `search` | bool | 是否支持搜索 | `builtin.py` 过滤条件 |
| `proxy` | bool | 是否使用代理 | `builtin.py` 传递给下载器 |
| `render` | bool | 是否需要浏览器渲染 | `builtin.py` 决定是否用 Selenium |
| `cookie` | str | 站点 Cookie | 请求认证用 |
| `ua` | str | User-Agent | 请求头 |
| `token` | str | API Token | API 站点认证用 |
| `order` | int | 排序权重 | 结果排序 |
| `pri` | bool | 是否为私有站点 | 区分公开/私有站点 |
| `rule` | int | 规则 ID | 过滤规则 |
| `public` | bool | 是否公开站点 | 与 `pri` 互补 |
| `builtin` | bool | 是否内置站点 | 38 个内置站点标记 |
| `tags` | list | 标签列表 | 站点分类标签 |
| `category` | str | 分类 | 站点类别 |

### 3.2 调用方代码参考

`app/indexer/client/builtin.py` 中的调用模式：

```python
# 私有站点（75-80 行）
return self.user.get_indexer(url=url,
                             siteid=site.get("id"),
                             cookie=site.get("cookie"),
                             ua=site.get("ua"),
                             name=site.get("name"),
                             rule=site.get("rule"),
                             pri=True,
                             public=False)

# 公开站点（121 行）
indexer = self.user.get_indexer(url=site_url)

# 后续使用 indexer 的属性：
# indexer.search, indexer.proxy, indexer.render, indexer.cookie,
# indexer.ua, indexer.token, indexer.url, indexer.name, indexer.id,
# indexer.order, indexer.pri, indexer.rule, indexer.public
```

---

## 四、WlI5bfacg2 辅助类规范

### 4.1 类概述

`WlI5bfacg2` 是 `.so` 的核心实现类，名称经过混淆。`User` 类的所有新增方法都委托给它。该类负责：

1. 加载和解密 `user.sites.bin` 获取站点配置
2. 管理设备 UUID（生成、获取、注册）
3. 提供站点配置查询（索引器、刷流、公开站点）
4. 处理用户认证（向合作站点 API 发送请求）
5. 管理菜单和权限配置

### 4.2 方法清单

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `__init__` | - | - | 初始化，调用 `init_config` |
| `init_config` | - | - | 加载 SystemConfig、站点数据、UUID |
| `get_auth_level` | - | int | 从 SystemConfig 获取当前认证等级 |
| `get_authsites` | - | dict | 返回认证站点配置（`{SiteId: SiteAttr}`） |
| `get_menus` | ignore: list | list | 根据权限过滤 MENU_CONF，支持 ignore 排除 |
| `get_topmenus` | - | list[str] | 返回可分配的权限名称列表 |
| `get_topmenus_string` | - | str | 返回逗号分隔的权限字符串 |
| `get_services` | - | dict | 返回服务配置 |
| `get_indexer_conf` | url, siteid, ... | IndexerConf | 根据 URL/ID 查找站点配置并构造 IndexerConf |
| `get_brush_conf` | - | dict | 返回 `{url: xpath_config}` |
| `get_public_sites` | - | list[str] | 返回公开站点 URL 列表 |
| `check_user` | site, params | tuple(bool, str) | 认证校验，返回 (成功/失败, 消息) |
| `get_uuid` | - | str | 获取当前设备 UUID |
| `__random_uuid` | - | str | 使用 `uuid.uuid1()` 生成 UUID |
| `__register_uuid` | uuid: str | - | 向 `nastool.org/user/register` 注册 |
| `__encrypt` | plaintext: str | str | Fernet 加密 |
| `__decrypt` | ciphertext: str | str | Fernet 解密 |
| `__requestauth` | site, payload | dict | 向合作站点发送认证请求 |
| `__requestauth.__get_playload` | site, params | dict | 构造加密请求体（注意保留 playload 拼写） |
| `__requestauth.__check_result` | response | (bool, str) | 校验认证响应 |

### 4.3 加密体系

`.so` 使用三种加密方式：

1. **Fernet**（主加密）：用于 `user.sites.bin` 的加解密
2. **AES**：用于构造认证请求 payload（`aes_encrypt`/`aes_decrypt`）
3. **nexusphp_encrypt**：部分 PT 站点使用的特殊加密（NexusPHP 系统特有的密码加密）

密钥硬编码在 .so 中：
- AES key: `0f941adc1ca38b0d`
- AES IV/nonce: `3pEeF0dx5IT7Seo2`

---

## 五、已知 Bug（user.py 当前代码）

### Bug 1：`get_usermenus` 修改全局 MENU_CONF

**位置**：`web/backend/user.py:195-206`

**问题**：使用 `pop()` 直接修改模块级 `MENU_CONF` 字典。每次调用都会永久删除菜单项，且在遍历中修改 dict/list 会导致不可预测的行为。

**影响**：Web UI 菜单在多次请求后可能不完整。

**修复方案**：在方法内部复制 `MENU_CONF`，对副本进行过滤操作。

### Bug 2：`get_user` 返回值与调用者不匹配

**位置**：`web/main.py:297` vs `web/main.py:185,189`

**问题**：
- `main.py:189` 对 `get_user` 返回值调用 `.verify_password(password)` — 期望 User 对象
- `main.py:297` 对 `get_user` 返回值调用 `.get("pris")` — 期望 dict

在当前 user.py 中，`get_user` 返回 `User` 对象，`User.get()` 方法签名是 `get(self, user_id)`，所以 `.get("pris")` 实际上会查找 id 为 "pris" 的用户，返回 None。

**修复方案**：将 `main.py:297` 改为 `User().get_user(username).pris` 或使用 `as_dict()["pris"]`。或者在 .so 实现中 `get_user` 返回 dict。

### Bug 3：`add_user` 未哈希密码

**位置**：`web/backend/user.py:217`

**问题**：`add_user` 直接将原始密码传给 `dbhelper.insert_user`，未使用 `generate_password_hash`。

**影响**：新增用户的密码以明文存储在数据库中，无法通过 `check_password_hash` 验证。

---

## 六、开发任务分解

### Phase 1：基础设施（P0，无外部依赖）

#### Task 1.1：新增 IndexerConf 数据类
- **文件**：`web/backend/user.py`
- **内容**：定义 `IndexerConf` 类，`__init__` 接收并存储 16 个属性，带合理默认值
- **验收**：`IndexerConf(id="1", name="test", url="http://example.com")` 正常实例化，所有属性可访问

#### Task 1.2：修复 get_usermenus bug
- **文件**：`web/backend/user.py`
- **内容**：将 `MENU_CONF` 的操作改为深拷贝后操作，修复遍历中修改 dict/list 的 bug
- **验收**：连续多次调用 `get_usermenus` 不丢失菜单项

#### Task 1.3：修复 main.py:297 的 get_user 返回值不匹配
- **文件**：`web/main.py`
- **内容**：将 `User().get_user(username).get("pris")` 改为 `User().get_user(username).pris`
- **验收**：资源搜索页面正常加载，权限检查生效

### Phase 2：WlI5bfacg2 辅助类基础框架（P0）

#### Task 2.1：实现 WlI5bfacg2 类框架和配置加载
- **文件**：`web/backend/user.py`
- **内容**：
  - 定义 `WlI5bfacg2` 类
  - `__init__` / `init_config`：加载 SystemConfig、初始化 `_sites_data`
  - `__decrypt` / `__encrypt`：Fernet 加解密实现
  - 加载并解密 `user.sites.bin`
- **依赖**：`cryptography.fernet`, `app.conf.SystemConfig`
- **验收**：能正确解密 `user.sites.bin` 并解析 JSON 结构

#### Task 2.2：实现菜单和权限方法
- **文件**：`web/backend/user.py`
- **内容**：
  - `get_topmenus`：返回中文权限名列表
  - `get_topmenus_string`：返回逗号分隔的权限字符串
  - `get_menus(ignore)`：根据权限过滤 MENU_CONF，返回菜单列表
  - `get_services`：返回服务配置 dict
- **验收**：`User().get_topmenus()` 和 `User().get_usermenus()` 返回正确数据

#### Task 2.3：实现站点查询方法
- **文件**：`web/backend/user.py`
- **内容**：
  - `get_indexer_conf(url, siteid, cookie, ua, name, rule, pri, public)`：构造 `IndexerConf`
  - `get_brush_conf`：返回 `{url: xpath_config}` dict
  - `get_public_sites`：返回公开站点 URL 列表
  - `get_authsites`：返回 `{SiteId: SiteAttr}` dict（含 name 属性）
- **验收**：`app/indexer/client/builtin.py` 和 `app/sites/siteconf.py` 中的调用正常工作

### Phase 3：User 类改造（P0）

#### Task 3.1：修改 User.__init__ 初始化辅助类
- **文件**：`web/backend/user.py`
- **内容**：
  - 在 `__init__` 中初始化 `WlI5bfacg2` 实例
  - 保留 `admin_users` 初始化（向后兼容）
  - 保留 `DbHelper` 初始化（`get_users`、`add_user`、`delete_user` 仍需要）
- **验收**：`User()` 实例化不报错

#### Task 3.2：User 类新增缺失方法
- **文件**：`web/backend/user.py`
- **新增方法**：
  - `as_dict()` → 返回 `{id, name, pris}` 字典
  - `get_authsites()` → 委托 `WlI5bfacg2.get_authsites()`
  - `get_indexer(...)` → 委托 `WlI5bfacg2.get_indexer_conf(...)`
  - `get_brush_conf()` → 委托 `WlI5bfacg2.get_brush_conf()`
  - `get_public_sites()` → 委托 `WlI5bfacg2.get_public_sites()`
  - `check_user(site, params)` → 委托 `WlI5bfacg2.check_user(site, params)`
- **修改方法**：
  - `get_topmenus()` → 改为委托 `WlI5bfacg2.get_topmenus()`
  - `get_services()` → 改为委托 `WlI5bfacg2.get_services()`
  - `get_usermenus(ignore)` → 改为委托 `WlI5bfacg2.get_menus(ignore)`
- **验收**：所有新增/修改方法可正常调用，返回值与调用者期望一致

### Phase 4：认证系统（P1，可选实现）

> **说明：** 认证系统涉及向外部 PT 站点发送请求，属于辅助功能。即使不实现，主功能（菜单、索引器、刷流）也能正常工作。`check_user` 可先返回 `(False, "认证功能未实现")` 占位。

#### Task 4.1：实现 UUID 管理
- **文件**：`web/backend/user.py`
- **内容**：
  - `__random_uuid()`：使用 `uuid.uuid1()` 生成
  - `get_uuid()`：从 SystemConfig 读取或自动生成
  - `__register_uuid(uuid)`：POST 到 `nastool.org/user/register`
  - 使用 AES 加密 UUID 传输
- **验收**：UUID 注册流程可执行

#### Task 4.2：实现 check_user 认证流程
- **文件**：`web/backend/user.py`
- **内容**：
  - `get_auth_level()`：从 SystemConfig 读取认证等级
  - `check_user(site, params)`：
    1. 获取认证站点列表
    2. 构造加密 payload（`__get_playload`，使用 AES + nexusphp_encrypt）
    3. 向合作站点 API 发送请求（`__requestauth`）
    4. 校验响应（`__check_result`）
    5. 更新认证等级
- **验收**：`User().check_user(None, None)` 可执行认证流程

### Phase 5：集成与回归（P0）

#### Task 5.1：依赖确认
- 确认 `cryptography` 已在 `requirements.txt`（已有）
- 确认 `requests` 可用（已有）
- 无新增依赖

#### Task 5.2：本地测试
- 使用 Python 3.12 venv 测试
- 验证所有菜单渲染正常
- 验证索引器配置获取正常
- 验证刷流配置获取正常
- 验证用户登录/注册流程正常

#### Task 5.3：Docker 构建测试
- 重建 Docker 镜像（确认 .so 被 .py 替代）
- 容器内启动验证无 import 报错
- 访问 Web UI 验证菜单显示正常

---

## 七、任务依赖关系

```
Phase 1 (Task 1.1, 1.2, 1.3)  ← 互不依赖，可并行
    ↓
Phase 2 (Task 2.1 → 2.2 → 2.3)  ← 依赖 Phase 1 的 IndexerConf 类
    ↓                                2.2 依赖 2.1 的配置加载
    ↓                                2.3 依赖 2.1 的站点数据解析
Phase 3 (Task 3.1 → 3.2)         ← 依赖 Phase 2 的 WlI5bfacg2 实现
    ↓
Phase 4 (Task 4.1 → 4.2)         ← 依赖 Phase 2 的加密体系
    ↓
Phase 5 (Task 5.1, 5.2, 5.3)     ← 依赖 Phase 1-3 全部完成
                                     Phase 4 可选
```

---

## 八、技术风险

| 风险 | 等级 | 说明 | 缓解措施 |
|------|------|------|---------|
| Fernet 密钥派生逻辑不明 | 高 | AES key 到 Fernet key 的派生方式需从 .so 逆向确认 | 优先尝试标准 Fernet key 生成（base64 url-safe encode of AES key），失败则尝试 PBKDF2 派生 |
| user.sites.bin 数据结构未知 | 中 | 解密后的 JSON 结构需要确认 | 解密后打印顶层 key，逐步适配 |
| 认证 API 已下线 | 中 | 合作站点 API 端点可能已失效 | 添加请求超时(5s)和异常捕获，认证失败不阻塞主功能 |
| nexusphp_encrypt 实现复杂 | 中 | 不同 NexusPHP 站点版本加密方式可能不同 | 先实现通用流程，特殊站点单独处理 |
| get_user 返回值不匹配 | 低 | 当前 main.py 中既有期望 User 对象又有期望 dict 的调用 | 已在 Task 1.3 中规划修复 |

---

## 九、文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `web/backend/user.py` | **主要修改** | 新增 IndexerConf 类、WlI5bfacg2 类、User 新方法，修复 bug，预计新增 ~400 行 |
| `web/main.py` | 小修改 | 修复 `search()` 路由中 `get_user` 返回值调用方式 |
| `requirements.txt` | 可能修改 | 确认 cryptography 版本 |
| `docker/Dockerfile` | 不变 | 已在前序任务中修复 |
| `docs/plan/001-align-user-py-to-so.md` | 本文件 | 计划文档 |
