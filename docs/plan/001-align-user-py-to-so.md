# Plan 001: user.py 功能对齐至 .so 版本

> 目标：将 `web/backend/user.py`（基础版）功能补全，使其与 `user.cpython-310-x86_64-linux-gnu.so`（迭代版）行为一致，支持 Python 3.10/3.12 双版本运行。

---

## 一、现状对比

### 1.1 文件概况

| 项目 | user.py（基础版） | user.so（迭代版） |
|------|------------------|-------------------|
| 来源 | linyuan0213/nas-tools fork | alpha-86/nas-tools 仓库 |
| 行数 | 221 行 | ~2200 行等价 Python |
| 类数量 | 1（User） | 3（User + WlI5bfacg2 + IndexerConf） |
| 依赖 | flask_login, werkzeug, DbHelper, Config | + cryptography.fernet, json, requests, SystemConfig, ModuleConf, RequestUtils |

### 1.2 方法对比

#### User 类

| 方法 | user.py | user.so | 差异说明 |
|------|:-------:|:-------:|---------|
| `__init__` | ✅ | ✅ | .so 额外初始化 `WlI5bfacg2` 辅助对象 |
| `get_id` | ✅ | ✅ | 一致 |
| `get` | ✅ | ✅ | 一致 |
| `get_user` | ✅ | ✅ | 一致 |
| `verify_password` | ✅ | ✅ | 一致 |
| `get_pris` | ✅ | ❌ | .so 中移除此方法，改用 `as_dict` |
| `as_dict` | ❌ | ✅ | **新增**：返回 `{id, name, pris}` 字典 |
| `get_users` | ✅ | ✅ | user.py 返回 ORM 对象，.so 可能返回字典列表 |
| `add_user` | ✅ | ✅ | 一致 |
| `delete_user` | ✅ | ✅ | 一致 |
| `get_usermenus` | ✅ | ✅ | .so 增加 `ignore` 参数过滤 |
| `get_authsites` | ❌ | ✅ | **新增**：委托 WlI5bfacg2 |
| `get_services` | ✅ | ✅ | .so 委托 WlI5bfacg2 返回 `SERVICE_CONF` |
| `get_topmenus` | ✅ | ✅ | .so 委托 WlI5bfacg2 |
| `check_user` | ❌ | ✅ | **新增**：用户认证校验 |
| `get_indexer` | ❌ | ✅ | **新增**：获取索引器配置 |
| `get_brush_conf` | ❌ | ✅ | **新增**：获取刷流配置 |
| `get_public_sites` | ❌ | ✅ | **新增**：获取公开站点列表 |

#### WlI5bfacg2 类（混淆辅助类，user.py 完全缺失）

| 方法 | 功能描述 |
|------|---------|
| `__init__` / `init_config` | 初始化：加载 SystemConfig、站点数据、UUID |
| `get_auth_level` | 获取用户认证等级 |
| `get_authsites` | 返回认证站点配置（带加密凭据） |
| `get_menus` | 返回菜单配置（供 User.get_usermenus 调用） |
| `get_topmenus` | 返回可分配权限列表（中文菜单名数组） |
| `get_topmenus_string` | 返回权限列表的字符串表示 |
| `get_services` | 返回服务配置（`SERVICE_CONF`） |
| `get_indexer_conf` | 返回 `IndexerConf` 对象 |
| `get_brush_conf` | 返回各站点的刷流 XPath 配置 |
| `get_public_sites` | 返回公开站点 URL 列表 |
| `check_user` | 校验用户是否有合作站点认证 |
| `__encrypt` / `__decrypt` | AES/Fernet 加解密（用于 `user.sites.bin`） |
| `__random_uuid` / `get_uuid` / `__register_uuid` | UUID 生成、获取、注册（注册到 nastool.org） |
| `__requestauth` | 向合作站点发送认证请求 |
| `__requestauth.__get_playload` | 构造认证请求 payload |
| `__requestauth.__check_result` | 校验认证请求结果 |

#### IndexerConf 类（user.py 完全缺失）

| 属性 | 类型 | 说明 |
|------|------|------|
| `id` | str | 索引器 ID |
| `name` | str | 索引器名称 |
| `url` | str | 索引器 URL |
| `search` | bool | 是否支持搜索 |
| `proxy` | bool | 是否使用代理 |
| `render` | bool | 是否需要浏览器渲染 |
| `cookie` | str | 站点 Cookie |
| `ua` | str | User-Agent |
| `token` | str | API Token |
| `order` | int | 排序权重 |
| `pri` | bool | 是否为私有站点 |
| `rule` | int | 规则 ID |
| `public` | bool | 是否公开站点 |
| `builtin` | bool | 是否内置 |
| `tags` | list | 标签列表 |
| `category` | str | 分类 |

---

## 二、.so 中的关键业务逻辑

### 2.1 认证系统架构

```
User.check_user(site, params)
  └─ WlI5bfacg2.check_user(site, params)
       ├─ get_auth_level()  → 获取当前认证等级
       ├─ __requestauth()   → 遍历合作站点发送认证请求
       │    ├─ __get_playload()  → 构造加密 payload
       │    └─ __check_result()  → 校验响应
       └─ 更新 SystemConfig 中的认证状态
```

### 2.2 加密体系

- **`user.sites.bin`**：Fernet 加密的 JSON 文件（`gAAAAAB` 前缀），包含所有站点配置
- **密钥来源**：`0f941adc1ca38b0d`（AES key）+ `3pEeF0dx5IT7Seo2`（IV/nonce）
- **UUID 注册**：`__register_uuid()` 向 `nastool.org/user/register` 注册设备 UUID
- **站点凭据格式**：
  - `{uid}:{passkey}`
  - `{uid}{passkey}`
  - `{username}@@@{passkey}`

### 2.3 合作站点认证 API

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

### 2.4 内置站点列表（38 个）

1ptba.com, 52pt.site, audiences.me, avgv.cc, azusa.ru, carpt.net, ccfbits.org,
chdbits.co, cyanbug.net, discfan.net, et8.org, gainbound.net, hdatmos.club,
hdchina.org, hdfans.org, hdhome.org, hdmayi.com, hdsky.me, hdtime.org,
hdzone.me, hhanclub.top, ihdbits.me, jptv.club, kamept.com, leaves.red,
lemonhd.org, nanyangpt.com, ourbits.club, piggo.me, ptchina.org, pterclub.com,
pthome.net, ptsbao.club, sharkpt.net, skyeysnow.com, springsunday.net,
ubits.club, wintersakura.net, zmpt.cc

---

## 三、开发任务分解

### Phase 1：基础类补全（P0）

#### Task 1.1：新增 IndexerConf 类
- **文件**：`web/backend/user.py`
- **内容**：定义 `IndexerConf` 类，包含 16 个属性（id, name, url, search, proxy, render, cookie, ua, token, order, pri, rule, public, builtin, tags, category）
- **验收**：`IndexerConf(id="1", name="test", url="http://example.com")` 可正常实例化

#### Task 1.2：User 类新增缺失方法（简单委托）
- **文件**：`web/backend/user.py`
- **新增方法**：
  - `as_dict()` → 返回 `{id, name, pris}` 字典
  - `get_authsites()` → 委托辅助类
  - `get_services()` → 委托辅助类，返回 `SERVICE_CONF`
  - `get_indexer(...)` → 委托辅助类，返回 `IndexerConf`
  - `get_brush_conf()` → 委托辅助类
  - `get_public_sites()` → 委托辅助类
  - `check_user(site, params)` → 委托辅助类
- **修改方法**：
  - `__init__` → 初始化辅助类实例
  - `get_usermenus` → 增加 `ignore` 参数
- **验收**：所有新增方法可正常调用不报错

### Phase 2：辅助类实现（P0）

#### Task 2.1：实现 WlI5bfacg2 基础框架
- **文件**：`web/backend/user.py`
- **内容**：
  - `__init__` / `init_config`：加载 `SystemConfig`、初始化 `_sites_data`
  - `get_topmenus`：返回中文权限名列表（`["我的媒体库", "探索", "资源搜索", "站点管理", ...]`）
  - `get_menus`：返回 `MENU_CONF` 子集（根据权限过滤）
  - `get_topmenus_string`：返回逗号分隔的权限字符串
- **依赖**：`app.conf.SystemConfig`, `SystemConfigKey`
- **验收**：`User().get_topmenus()` 返回正确列表

#### Task 2.2：实现站点数据加载与解密
- **文件**：`web/backend/user.py`
- **内容**：
  - `__encrypt(plaintext)` / `__decrypt(ciphertext)`：使用 `cryptography.fernet` 加解密
  - 加载 `user.sites.bin`（Fernet 加密的 JSON）
  - 解析站点配置数据结构（`data.sites`, `data.enabled` 等）
- **密钥**：需从 `.so` 逆向确认 Fernet key 来源（硬编码或派生）
- **验收**：能正确解密 `user.sites.bin` 并获得站点列表

#### Task 2.3：实现 get_indexer_conf
- **文件**：`web/backend/user.py`
- **内容**：
  - 根据 `url`/`siteid` 从站点数据中查找配置
  - 组合 `cookie`, `ua`, `rule`, `pri` 等参数
  - 构造并返回 `IndexerConf` 对象
  - 区分公开站点和私有站点
- **验收**：`User().get_indexer(url="https://xxx")` 返回有效 `IndexerConf`

#### Task 2.4：实现 get_brush_conf / get_public_sites / get_authsites
- **文件**：`web/backend/user.py`
- **内容**：
  - `get_brush_conf`：从站点数据中提取各站点的刷流 XPath 配置
  - `get_public_sites`：返回公开站点 URL 列表
  - `get_authsites`：返回认证站点配置（包含加密凭据）
- **验收**：方法返回正确的数据结构

### Phase 3：认证系统实现（P1）

#### Task 3.1：实现 UUID 管理
- **文件**：`web/backend/user.py`
- **内容**：
  - `__random_uuid()`：生成随机 UUID
  - `get_uuid()`：获取当前设备 UUID（从 SystemConfig 读取或自动生成）
  - `__register_uuid(uuid)`：向 `nastool.org/user/register` 注册
  - UUID 存储在 `SystemConfig` 中持久化
- **验收**：UUID 注册流程可正常执行

#### Task 3.2：实现 check_user 认证流程
- **文件**：`web/backend/user.py`
- **内容**：
  - `get_auth_level()`：从 SystemConfig 读取当前认证等级
  - `check_user(site, params)`：
    1. 获取认证站点列表
    2. 构造认证 payload（加密 uid + passkey）
    3. 向合作站点 API 发送认证请求
    4. 校验响应结果
    5. 更新认证等级到 SystemConfig
  - `__requestauth(site, payload)`：发送 HTTP 请求到合作站点
  - `__get_playload(site, params)`：构造加密请求体
  - `__check_result(response)`：校验响应
- **验收**：`User().check_user(None, None)` 可正常执行认证流程

### Phase 4：集成与回归（P0）

#### Task 4.1：更新 requirements.txt
- 确认 `cryptography` 已在依赖中（已有）
- 确认 `requests` 可用（已有）
- 确认无新增依赖

#### Task 4.2：本地测试
- 使用 Python 3.12 venv 测试所有新增方法
- 验证 `get_usermenus` 返回正确的菜单结构
- 验证 `get_topmenus` 返回权限列表
- 验证 `get_indexer` 返回 `IndexerConf`

#### Task 4.3：Docker 构建测试
- 重建 Docker 镜像
- 容器内启动验证无报错
- 访问 Web UI 验证菜单显示正常

---

## 四、技术风险

| 风险 | 等级 | 说明 | 缓解措施 |
|------|------|------|---------|
| Fernet 密钥无法还原 | 高 | `user.sites.bin` 的解密密钥可能依赖运行时环境 | 优先从 SystemConfig 获取密钥，硬编码作为 fallback |
| 认证 API 变更 | 中 | 合作站点 API 可能已下线或变更 | 添加请求超时和异常捕获，认证失败不影响主功能 |
| `nexusphp_encrypt` 站点加密 | 中 | 部分站点使用特殊加密方式 | 先实现通用流程，特殊站点单独处理 |
| 站点数据结构未知 | 中 | `user.sites.bin` 解密后的 JSON 结构需要确认 | 解密后打印结构，逐步适配 |

---

## 五、依赖关系

```
Phase 1 (Task 1.1, 1.2)  ← 无依赖，可立即开始
    ↓
Phase 2 (Task 2.1-2.4)   ← 依赖 Phase 1 的类定义
    ↓
Phase 3 (Task 3.1-3.2)   ← 依赖 Phase 2 的数据加载
    ↓
Phase 4 (Task 4.1-4.3)   ← 依赖 Phase 1-3 全部完成
```

---

## 六、文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `web/backend/user.py` | 修改 | 主要开发文件，新增 ~300 行代码 |
| `requirements.txt` | 可能修改 | 确认 cryptography 依赖版本 |
| `docker/Dockerfile` | 不变 | 已在前序任务中修复 |
| `docs/plan/001-align-user-py-to-so.md` | 本文件 | 计划文档 |
