# Plan 009: Security Audit Remediation — 移除 nastool.org 遥测、修复 RCE、硬化更新机制

> 目标：消除代码中的数据外传隐患、多处 `eval()` 导致的认证后 RCE、pickle 反序列化 RCE，以及可被劫持的自动更新机制。

---

## 一、现状分析

### 1.1 安全审查结论

基于对代码库的全面安全审查，发现以下高危问题：

| 类别 | 问题 | 风险等级 | 影响 |
|---|---|---|---|
| 数据外传 | `nastool.org` 遥测接口已全部失效并被域名劫持，所有请求 302 重定向到 `survey-smiles.com`（DNS 不可解析） | **高** | 验证码图片、插件列表、版本号被发送至未知第三方；功能超时卡顿 |
| RCE | 多处 `eval()` 执行用户可控输入 | **高** | 认证后可执行任意 Python 代码 |
| RCE | `pickle.load()` 反序列化用户可写文件 | **中** | 篡改缓存文件可导致启动时 RCE |
| 供应链 | `update_system()` 使用 `git reset --hard` + `pip install` 无签名校验 | **高** | Git 仓库被劫持可导致任意代码执行 |
| 加密 | `user.sites.bin` 使用硬编码 Fernet 密钥 | **低** | 密钥已公开，但仅用于站点爬虫规则，不含用户凭证 |

### 1.2 nastool.org 域名状态

**已全部不可用且被劫持：**

| 原接口 | 当前状态 |
|---|---|
| `GET https://nastool.org/plugin/{id}/install` | 302 → survey-smiles.com (NXDOMAIN) |
| `POST https://nastool.org/plugin/update` | 302 → survey-smiles.com (NXDOMAIN) |
| `GET https://nastool.org/plugin/statistic` | 302 → survey-smiles.com (NXDOMAIN) |
| `POST https://nastool.org/captcha/base64` | 302 → survey-smiles.com (NXDOMAIN) |
| `GET https://nastool.org/{version}/update` | 302 → survey-smiles.com (NXDOMAIN) |
| `GET https://wechat.nastool.org` | 302 → survey-smiles.com (NXDOMAIN) |

> `requests` 默认 `allow_redirects=True`，代码中的请求会自动跟随 302 重定向。

### 1.3 eval() 分布

| 文件 | 行号 | 上下文 | 输入来源 |
|---|---|---|---|
| `web/action.py` | 1664, 1677 | `__test_connection()` | 前端 API 请求（需认证） |
| `app/media/tmdbv3api/tmdb.py` | 135, 157 | `eval(proxies)` | config.yaml 代理配置 |
| `app/brushtask.py` | 125-126 | `eval(task.RSS_RULE)`, `eval(task.REMOVE_RULE)` | 数据库刷流任务规则 |
| `app/helper/words_helper.py` | 131 | `eval(offset_caculate)` | 自定义识别词配置 |

### 1.4 pickle 分布

| 文件 | 行号 | 上下文 | 文件是否用户可写 |
|---|---|---|---|
| `app/helper/meta_helper.py` | 144, 176 | `pickle.load/dump` 读写 `tmdb.dat` | **是**（运行时缓存） |
| `web/backend/user.py` | 368 | `pickle.loads` 加载内置 `user.sites.bin` | **否**（内置只读文件） |

---

## 二、方案

### 2.1 总体策略

```
Phase 1: 移除 nastool.org 遥测（最高优先级，可立即执行）
    ├─ 禁用 PluginHelper 的三个远程调用
    ├─ 禁用 OcrHelper 远程 OCR
    ├─ 禁用版本检查远程调用
    ├─ 移除 tmdb.nastool.org / wechat.nastool.org / nastool.org/cookiecloud
    ├─ 移除 initializer.py 启动上报
    └─ 移除 config.py 中 tmdb.nastool.org 域名

Phase 2: 消除 eval() RCE（代码中无 eval()）
    ├─ __test_connection: 完全删除 eval，改为后端白名单执行
    ├─ tmdb proxies: ast.literal_eval 替代
    ├─ brushtask rules: json.loads 替代
    └─ words_helper: ast 安全算术解析替代

Phase 3: 硬化自动更新
    └─ 所有环境（含群晖）改为只提示手动更新，禁止任何 os.system/git/pip 自动执行

Phase 4: 消除 pickle RCE
    └─ tmdb 缓存改为 JSON 序列化，写入新文件 tmdb.json，不再读取旧 tmdb.dat
```

---

## 三、具体改动

### 3.1 移除 nastool.org 遥测

#### 3.1.1 PluginHelper (`app/helper/plugin_helper.py`)

三个方法全部禁用，返回空值以保持 API 兼容：

```python
class PluginHelper:
    @staticmethod
    def install(plugin_id):
        """
        插件安装统计计数（已禁用：nastool.org 已失效并被劫持）
        """
        # 原逻辑：RequestUtils(timeout=5).get(f"https://nastool.org/plugin/{plugin_id}/install")
        return None

    @staticmethod
    def report(plugins):
        """
        批量上报插件安装统计数据（已禁用）
        """
        # 原逻辑：POST https://nastool.org/plugin/update
        return None

    @staticmethod
    @cached(cache=TTLCache(maxsize=1, ttl=3600))
    def statistic():
        """
        获取插件安装统计数据（已禁用）
        """
        # 原逻辑：GET https://nastool.org/plugin/statistic
        return {}
```

#### 3.1.2 OcrHelper (`app/helper/ocr_helper.py`)

远程 OCR 服务已失效，改为直接返回空字符串：

```python
class OcrHelper:
    # _ocr_b64_url = "https://nastool.org/captcha/base64"  # 已禁用

    def get_captcha_text(self, image_url=None, image_b64=None, cookie=None, ua=None):
        """
        根据图片地址获取验证码内容
        注意：远程 OCR 服务已禁用，返回空字符串
        """
        # 远程 OCR 服务 nastool.org 已失效并被劫持，不再发送图片到第三方
        return ""
```

> 影响：自动签到插件（hdsky、opencd）和站点 Cookie 获取中的验证码识别将失效。这些站点通常需要手动登录一次获取 Cookie，不影响日常使用。

#### 3.1.3 版本检查 (`web/backend/web_utils.py`)

```python
    @staticmethod
    def get_latest_version():
        """
        获取最新版本号（已禁用：nastool.org 已失效并被劫持）
        """
        # 远程版本检查服务已不可用
        return None, None
```

#### 3.1.4 TMDB 域名白名单 (`config.py`)

移除 `tmdb.nastool.org` 和 `t.nastool.workers.dev`：

```diff
- TMDB_API_DOMAINS = ['api.themoviedb.org', 'api.tmdb.org', 'tmdb.nastool.org', 't.nastool.workers.dev']
+ TMDB_API_DOMAINS = ['api.themoviedb.org', 'api.tmdb.org']
```

#### 3.1.5 initializer.py 默认域名迁移

删除 initializer.py 中向配置写入 `tmdb.nastool.org` 的迁移逻辑：

```diff
-    # TMDB代理服务开关迁移
-    try:
-        tmdb_proxy = Config().get_config('laboratory').get("tmdb_proxy")
-        if tmdb_proxy:
-            _config['app']['tmdb_domain'] = 'tmdb.nastool.org'
-            _config['laboratory'].pop("tmdb_proxy")
-            overwrite_cofig = True
-    except Exception as e:
-        ExceptionUtils.exception_traceback(e)
```

#### 3.1.6 企业微信默认代理 (`app/conf/moduleconf.py`)

```diff
-                        "placeholder": "https://wechat.nastool.org"
+                        "placeholder": "https://qyapi.weixin.qq.com"
```

#### 3.1.7 企业微信客户端默认代理 (`app/message/client/wechat.py`)

```diff
-    _default_proxy_url = 'https://wechat.nastool.org'
+    _default_proxy_url = None
```

> `_default_proxy_url` 不再指向任何第三方代理。已配置 `wechat.nastool.org` 的存量用户不受影响（config.yaml 中持久化的值不会被覆盖），仅影响未配置时使用默认值的新安装场景。

#### 3.1.8 CookieCloud 默认服务器 (`app/plugins/modules/cookiecloud.py`)

```diff
-                                    'placeholder': 'https://nastool.org/cookiecloud'
+                                    'placeholder': 'http://localhost:8088'
```

> CookieCloud 是用户自建服务，placeholder 不应指向已失效的第三方地址。改为 `localhost:8088` 作为自建服务的典型端口提示。

#### 3.1.9 启动上报 (`initializer.py`)

删除以下代码块：

```diff
-    # 存量插件安装情况统计
-    try:
-        plugin_report_state = SystemConfig().get(SystemConfigKey.UserInstalledPluginsReport)
-        installed_plugins = SystemConfig().get(SystemConfigKey.UserInstalledPlugins)
-        if not plugin_report_state and installed_plugins:
-            ret = PluginHelper().report(installed_plugins)
-            if ret:
-                SystemConfig().set(SystemConfigKey.UserInstalledPluginsReport, '1')
-    except Exception as e:
-        ExceptionUtils.exception_traceback(e)
```

---

### 3.2 消除 eval() RCE（代码中无 eval()）

#### 3.2.1 __test_connection (`web/action.py:1652-1687`) — 完全删除 eval

将无限制的 `eval()` 改为后端白名单执行。不再执行任何前端传入的 Python 表达式。

**处理逻辑：**

1. **普通网络连通性测试**：`command` 为字符串（非 list，不含 `|`）。后端根据 `ModuleConf.NETTEST_TARGETS` 白名单，执行实际的 HTTP 请求或 socket 连接测试。
2. **Media Server 状态测试**：`command` 为 `module|Class` 形式。只允许三个固定映射，禁止任意 `importlib.import_module`：
   - `"app.mediaserver.client.emby|Emby"` → 固定实例化 `Emby` 并调用 `get_status()`
   - `"app.mediaserver.client.jellyfin|Jellyfin"` → 固定实例化 `Jellyfin`
   - `"app.mediaserver.client.plex|Plex"` → 固定实例化 `Plex`
   - 其他任何 `module|Class` 一律拒绝
3. **批量测试**：`command` 为 list 时，逐个按上述规则处理。

```python
    @staticmethod
    def __test_connection(data):
        """
        测试连通性（无 eval，白名单执行）
        """
        command = data.get("command")
        ret = None
        if not command:
            return {"code": 0}

        try:
            # Media Server 固定映射白名单
            MEDIA_SERVER_MAP = {
                "app.mediaserver.client.emby|Emby": Emby,
                "app.mediaserver.client.jellyfin|Jellyfin": Jellyfin,
                "app.mediaserver.client.plex|Plex": Plex,
            }
            # 网络测试白名单（来自 ModuleConf.NETTEST_TARGETS）
            NETTEST_WHITELIST = set(ModuleConf.NETTEST_TARGETS)

            commands = command if isinstance(command, list) else [command]
            for cmd in commands:
                if "|" in cmd:
                    # Media Server 状态测试
                    if cmd not in MEDIA_SERVER_MAP:
                        log.warn(f"test_connection: 拒绝未授权的 Media Server 类型: {cmd}")
                        ret = False
                        break
                    cls = MEDIA_SERVER_MAP[cmd]
                    instance = cls()
                    if hasattr(instance, "init_config"):
                        instance.init_config()
                    ret = instance.get_status()
                else:
                    # 网络连通性测试
                    if cmd not in NETTEST_WHITELIST:
                        log.warn(f"test_connection: 拒绝未授权的网络测试目标: {cmd}")
                        ret = False
                        break
                    ret = RequestUtils().get_res(f"https://{cmd}", timeout=5) is not None
                if not ret:
                    break

            Config().init_config()
        except Exception as e:
            ret = None
            ExceptionUtils.exception_traceback(e)
        return {"code": 0 if ret else 1}
```

**攻击回归用例（必须全部失败）：**

| 输入 | 预期行为 |
|---|---|
| `__import__("os").system("id")` | 不含 `\|`，`cmd not in NETTEST_WHITELIST` → 拒绝 |
| `open("/etc/passwd").read()` | `cmd not in NETTEST_WHITELIST` → 拒绝 |
| `().__class__.__bases__[0].__subclasses__()` | `cmd not in NETTEST_WHITELIST` → 拒绝 |
| `"os|system"` | `cmd not in MEDIA_SERVER_MAP` → 拒绝 |
| `"app.utils.system_utils|SystemUtils"` | `cmd not in MEDIA_SERVER_MAP` → 拒绝 |
| `"app.mediaserver.client.emby|Emby"` | `cmd in MEDIA_SERVER_MAP` → 允许（固定白名单） |

#### 3.2.2 TMDB proxies (`app/media/tmdbv3api/tmdb.py:135,157`)

```diff
  import ast

  # line 135
- return requests.request(method, url, data=data, proxies=eval(proxies), verify=False, timeout=10)
+ return requests.request(method, url, data=data, proxies=ast.literal_eval(proxies) if proxies else None, verify=False, timeout=10)

  # line 157
- req = self._session.request(method, url, data=data, proxies=eval(self.proxies), timeout=10, verify=False)
+ req = self._session.request(method, url, data=data, proxies=ast.literal_eval(self.proxies) if self.proxies else None, timeout=10, verify=False)
```

#### 3.2.3 BrushTask rules (`app/brushtask.py:125-126`)

```diff
  import json

-               "rss_rule": eval(task.RSS_RULE),
-               "remove_rule": eval(task.REMOVE_RULE),
+               "rss_rule": json.loads(task.RSS_RULE) if task.RSS_RULE else {},
+               "remove_rule": json.loads(task.REMOVE_RULE) if task.REMOVE_RULE else {},
```

> 确认 `RSS_RULE` / `REMOVE_RULE` 在数据库中以 JSON 字符串存储（来自前端提交和 `json.dumps`）。如字段值为 Python 字典字面量字符串，也兼容 `json.loads`。

#### 3.2.4 WordsHelper (`app/helper/words_helper.py:131`) — 安全算术解析

`ast.literal_eval` 不支持 `EP+1` / `EP-2` 这类算术表达式，需要自定义安全解析器：

```python
import ast

_ALLOWED_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a // b if b != 0 else 0,
    ast.USub: lambda a: -a,
}

_SAFE_NUM_TYPES = (int, float)


def safe_arith_eval(expr):
    """
    安全算术表达式求值。
    仅允许：常量数字、+ - * //、一元负号。
    拒绝：函数调用、属性访问、下标、名称引用、字符串等。
    """
    if not isinstance(expr, str):
        raise ValueError("expr must be string")
    tree = ast.parse(expr, mode='eval')
    return _eval_node(tree.body)


def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, _SAFE_NUM_TYPES):
            return node.value
        raise ValueError(f"Disallowed constant type: {type(node.value)}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_OPS:
            raise ValueError(f"Disallowed binary operator: {op_type.__name__}")
        return _ALLOWED_OPS[op_type](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_OPS:
            raise ValueError(f"Disallowed unary operator: {op_type.__name__}")
        return _ALLOWED_OPS[op_type](_eval_node(node.operand))
    raise ValueError(f"Disallowed AST node: {type(node).__name__}")
```

替换 words_helper.py 中的 eval：

```diff
  import ast
+
+ _ALLOWED_OPS = {ast.Add: ..., ast.Sub: ..., ast.Mult: ..., ast.Div: ..., ast.USub: ...}
+ _SAFE_NUM_TYPES = (int, float)
+
+ def safe_arith_eval(expr):
+     ...
+
+ def _eval_node(node):
+     ...

                  offset_caculate = offset.replace("EP", str(episode_num_int))
-                 episode_num_offset_int = int(eval(offset_caculate))
+                 episode_num_offset_int = int(safe_arith_eval(offset_caculate))
```

**验收用例：**

| 输入 | 预期结果 |
|---|---|
| `EP+1`（offset="EP+1", EP 替换为 5 后） | `6`（正常） |
| `EP-2`（offset="EP-2", EP 替换为 10 后） | `8`（正常） |
| `EP*3` | `15`（正常，乘法允许） |
| `__import__("os").system("id")` | `ValueError: Disallowed AST node: Call`（拒绝） |
| `()["__class__"]` | `ValueError: Disallowed AST node: Subscript`（拒绝） |
| `"hello" + 1` | `ValueError: Disallowed constant type: <class 'str'>`（拒绝） |
| `(1).__class__` | `ValueError: Disallowed AST node: Attribute`（拒绝） |

---

### 3.3 硬化自动更新 (`web/action.py:1185-1221`)

**威胁模型：**

- `update_system()` 在认证后通过 Web API 触发。
- 非群晖环境：`sudo git reset --hard origin/{branch}` + `sudo pip install` 无 GPG 签名校验，Git 仓库被劫持后可直接在宿主机执行任意代码。
- 群晖环境：`os.system("nastool update")` 执行一个外部命令，其来源、权限、签名/完整性校验均不透明。`nastool update` 可能执行与上述相同的 git/pip 操作，也可能执行其他系统命令。无法证明其安全性。

**最终决策：所有环境均禁止自动执行外部更新命令。**

```python
    def update_system(self):
        """
        更新（已硬化：不再自动执行任何 git/pip/os.system 命令）
        """
        # 不再区分群晖/Docker/普通环境
        # 自动更新完全禁用，用户需手动更新或重新部署
        log.warn("自动更新已禁用。请手动执行 git pull 或重新部署容器/套件。")
        return {"code": 0, "msg": "自动更新已禁用"}
```

> 删除整个 `update_system` 方法中的 `os.system(...)`、`git clean/reset/fetch/submodule`、`pip install`、`nastool update` 等外部命令调用。

---

### 3.4 消除 pickle RCE (`app/helper/meta_helper.py`)

**威胁模型：** `tmdb.dat` 是运行时缓存文件，位于用户可写的配置目录。如果攻击者能写入恶意 pickle payload，服务启动或缓存加载时将触发任意代码执行。

**方案：** 缓存文件改为 JSON，使用新文件名 `tmdb.json`，**不再读取旧 `tmdb.dat`**。

```diff
  import os
- import pickle
+ import json
  import random
```

```diff
      def __init__(self):
          self.init_config()

      def init_config(self):
          ...
-         self._meta_path = os.path.join(Config().get_config_path(), 'tmdb.dat')
+         self._meta_path = os.path.join(Config().get_config_path(), 'tmdb.json')
          self._meta_data = self.__load_meta_data(self._meta_path)
```

```diff
      @staticmethod
      def __load_meta_data(path):
          try:
              if os.path.exists(path):
-                 with open(path, 'rb') as f:
-                     data = pickle.load(f)
+                 with open(path, 'r', encoding='utf-8') as f:
+                     data = json.load(f)
                  return data
              return {}
          except Exception as e:
              ExceptionUtils.exception_traceback(e)
              return {}
```

```diff
      def save_meta_data(self, force=False):
          ...
-         with open(self._meta_path, 'wb') as f:
-             pickle.dump(new_meta_data, f, pickle.HIGHEST_PROTOCOL)
+         with open(self._meta_path, 'w', encoding='utf-8') as f:
+             json.dump(new_meta_data, f, ensure_ascii=False)
```

> **不实现旧 pickle 迁移。** 旧 `tmdb.dat` 被忽略，首次启动时缓存为空，TMDB 数据会从 API 重新获取。不影响功能，仅增加首次启动时的 API 调用量。

---

## 四、文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `app/helper/plugin_helper.py` | 禁用三个远程调用 | install、report、statistic 返回空/None |
| `app/helper/ocr_helper.py` | 禁用远程 OCR | get_captcha_text 直接返回空字符串 |
| `web/backend/web_utils.py` | 禁用版本检查 | get_latest_version 返回 None, None |
| `config.py` | 移除 tmdb.nastool.org | TMDB_API_DOMAINS 白名单精简 |
| `initializer.py` | 移除 tmdb_domain 迁移 + 启动上报 | 删除 nastool.org 相关配置写入和上报 |
| `app/message/client/wechat.py` | 移除默认代理 | _default_proxy_url 设为 None |
| `app/conf/moduleconf.py` | 修改占位符 | 企业微信默认代理改回官方地址 |
| `app/plugins/modules/cookiecloud.py` | 修改占位符 | CookieCloud 默认地址改为 localhost |
| `web/action.py` | **完全删除 eval + 硬化更新** | __test_connection 改为白名单执行；update_system 禁用所有自动更新 |
| `app/media/tmdbv3api/tmdb.py` | eval → ast.literal_eval | 两处 proxies 解析 |
| `app/brushtask.py` | eval → json.loads | RSS_RULE / REMOVE_RULE 解析 |
| `app/helper/words_helper.py` | eval → safe_arith_eval | 自定义安全算术解析器 |
| `app/helper/meta_helper.py` | pickle → json + 新文件名 | tmdb.dat → tmdb.json，不读旧文件 |
| `docs/plan/009-security-audit-remediation.md` | 新增 | 本计划文档 |

---

## 五、可执行安全回归清单

以下命令在整改完成后必须全部通过。

### 5.1 eval() 零容忍验证

```bash
# 代码中不允许任何 eval()（含 re.compile 中的 eval 也不允许）
rg -n "\beval\s*\(" app web --glob "*.py"
# 期望：无任何输出
```

### 5.2 pickle 残留验证

```bash
# pickle.load / pickle.loads 只允许在 web/backend/user.py（加载内置只读 user.sites.bin）
rg -n "pickle\.(load|loads)" app web config.py initializer.py --glob "*.py"
# 期望：仅命中 web/backend/user.py:368（内置只读文件，信任边界可控）
# 不允许命中 app/helper/meta_helper.py
```

### 5.3 nastool.org 零容忍验证

```bash
# 运行时代码中不允许任何 nastool.org 相关字符串
rg -n "nastool\.org|wechat\.nastool\.org|tmdb\.nastool\.org" \
    app web config.py initializer.py --glob "*.py"
# 期望：无任何命中
# 注释/文档中的提及可保留，但不得出现在可执行代码路径中
```

### 5.4 __test_connection 攻击回归验证

```bash
cd /home/work/code/nas-tools
python3 <<'PY'
# 模拟 __test_connection 的白名单逻辑
NETTEST_WHITELIST = {
    "www.themoviedb.org", "image.tmdb.org", "webservice.fanart.tv",
    "api.telegram.org", "qyapi.weixin.qq.com", "www.opensubtitles.org"
}
MEDIA_SERVER_MAP = {
    "app.mediaserver.client.emby|Emby",
    "app.mediaserver.client.jellyfin|Jellyfin",
    "app.mediaserver.client.plex|Plex",
}

def is_allowed(cmd):
    if "|" in cmd:
        return cmd in MEDIA_SERVER_MAP
    return cmd in NETTEST_WHITELIST

# 攻击用例（必须全部拒绝）
attacks = [
    '__import__("os").system("id")',
    'open("/etc/passwd").read()',
    '().__class__.__bases__[0].__subclasses__()',
    '"os|system"',
    'app.utils.system_utils|SystemUtils',
    'app.mediaserver.client.emby|System',
]
# 合法用例（必须全部允许）
legit = [
    'www.themoviedb.org',
    'api.telegram.org',
    'app.mediaserver.client.emby|Emby',
    'app.mediaserver.client.plex|Plex',
]

for a in attacks:
    assert not is_allowed(a), f"攻击应被拒绝: {a}"
print("[OK] 所有攻击用例均被正确拒绝")

for l in legit:
    assert is_allowed(l), f"合法用例应被允许: {l}"
print("[OK] 所有合法用例均被正确允许")
PY
```

### 5.5 WordsHelper 攻击回归验证

```bash
python3 <<'PY'
import ast

_ALLOWED_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a // b if b != 0 else 0,
    ast.USub: lambda a: -a,
}
_SAFE_NUM_TYPES = (int, float)

def safe_arith_eval(expr):
    tree = ast.parse(expr, mode='eval')
    return _eval_node(tree.body)

def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, _SAFE_NUM_TYPES):
            return node.value
        raise ValueError(f"Disallowed constant type: {type(node.value)}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_OPS:
            raise ValueError(f"Disallowed binary operator: {op_type.__name__}")
        return _ALLOWED_OPS[op_type](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_OPS:
            raise ValueError(f"Disallowed unary operator: {op_type.__name__}")
        return _ALLOWED_OPS[op_type](_eval_node(node.operand))
    raise ValueError(f"Disallowed AST node: {type(node).__name__}")

# 合法用例
assert safe_arith_eval("5+1") == 6
assert safe_arith_eval("10-2") == 8
assert safe_arith_eval("3*4") == 12
assert safe_arith_eval("-5") == -5
assert safe_arith_eval("10//3") == 3
print("[OK] 合法算术表达式正常求值")

# 攻击用例（必须全部抛出 ValueError）
attacks = [
    '__import__("os").system("id")',
    'open("/etc/passwd")',
    '(1).__class__',
    '"hello"',
    '[]',
    '{}',
    '().__class__.__bases__[0]',
]
for a in attacks:
    try:
        safe_arith_eval(a)
        raise AssertionError(f"攻击应被拒绝: {a}")
    except ValueError:
        pass
print("[OK] 所有攻击用例均被正确拒绝")
PY
```

### 5.6 pickle 文件隔离验证

```bash
# 1. 确认旧 tmdb.dat 不会被加载
python3 -c "
import os
old = 'config/tmdb.dat'
if os.path.exists(old):
    print(f'[WARN] 旧 {old} 仍存在，需手动删除')
else:
    print('[OK] 旧 tmdb.dat 不存在')
"

# 2. 确认新缓存写入 JSON
python3 -c "
import json, os
new = 'config/tmdb.json'
if os.path.exists(new):
    with open(new) as f:
        d = json.load(f)
    print(f'[OK] 新缓存为 JSON，顶层类型: {type(d).__name__}')
else:
    print('[INFO] 新 tmdb.json 尚未生成（需运行一次媒体识别）')
"
```

### 5.7 自动更新硬化验证

```bash
# 确认 update_system 中不再有任何 os.system / git / pip 调用
rg -n "os\.system|git\s|pip\s|subprocess" web/action.py
# 期望：无命中（或仅命中其他无关方法，update_system 方法体内无命中）
```

---

## 六、风险与注意事项

1. **tmdb.json 格式迁移**：旧 `tmdb.dat` 被忽略，首次启动时缓存为空，TMDB 数据会从 API 重新获取。不影响功能，仅增加首次启动时的 API 调用量。旧 `tmdb.dat` 可由用户手动删除，也可保留（不再被读取，无安全风险）。

2. **OCR 禁用影响**：hdsky、opencd 等需要验证码的自动签到站点将无法自动识别验证码。用户需要手动在站点管理中获取 Cookie 后填入。这是安全与便利的权衡。

3. **ast.literal_eval 限制**：`literal_eval` 只支持 Python 字面量（字符串、数字、列表、字典等），不支持函数调用。对于 `brushtask.py` 和 `tmdb.py` 中的场景（proxies 和 rules 都是数据结构），完全适用。

4. **__test_connection 白名单变更**：Media Server 测试不再支持任意 `module|Class`，仅限 Emby/Jellyfin/Plex。如需测试其他 Media Server，需扩展 `MEDIA_SERVER_MAP`。普通网络测试仅限 `NETTEST_TARGETS` 中的域名。如需测试其他域名，需扩展白名单。

5. **企业微信代理配置**：`_default_proxy_url` 设为 `None` 后，未配置代理的群晖用户将直连微信官方 API。已配置 `wechat.nastool.org` 的存量用户不受影响（config.yaml 中已持久化的值不会被覆盖）。

6. **自动更新禁用**：在 Docker 环境中这是正确行为。对于非 Docker 的源码部署用户，需手动执行 `git pull`。建议在 README 中注明更新方式。

7. **config.py 中的 `t.nastool.workers.dev`**：这是 Cloudflare Workers 代理，与 `tmdb.nastool.org` 同属第三方域名，一并移除。仅保留官方 `api.themoviedb.org` 和 `api.tmdb.org`。

---

## 七、开发任务分解

### Phase 1: 移除 nastool.org 遥测（P0，可并行）

#### Task 1.1: 禁用 PluginHelper 远程调用
- **文件**: `app/helper/plugin_helper.py`
- **内容**: 将 `install`, `report`, `statistic` 改为返回 `None`/`{}`，注释原请求逻辑
- **验收**: `rg -n "nastool\.org" app/helper/plugin_helper.py` 无命中

#### Task 1.2: 禁用 OcrHelper 远程 OCR
- **文件**: `app/helper/ocr_helper.py`
- **内容**: `get_captcha_text` 直接返回空字符串，注释 `_ocr_b64_url`
- **验收**: `rg -n "nastool\.org" app/helper/ocr_helper.py` 无命中

#### Task 1.3: 禁用版本检查
- **文件**: `web/backend/web_utils.py`
- **内容**: `get_latest_version` 返回 `(None, None)`
- **验收**: `rg -n "nastool\.org" web/backend/web_utils.py` 无命中

#### Task 1.4: 移除 TMDB 域名白名单中的 nastool.org
- **文件**: `config.py`
- **内容**: `TMDB_API_DOMAINS` 移除 `tmdb.nastool.org` 和 `t.nastool.workers.dev`
- **验收**: `rg -n "tmdb\.nastool\.org|t\.nastool\.workers\.dev" config.py` 无命中

#### Task 1.5: 移除 initializer.py 中的 nastool.org 配置写入
- **文件**: `initializer.py`
- **内容**: 删除 TMDB 代理迁移逻辑（写入 `tmdb.nastool.org`）和插件启动上报
- **验收**: `rg -n "nastool\.org" initializer.py` 无命中

#### Task 1.6: 移除企业微信默认代理
- **文件**: `app/message/client/wechat.py`
- **内容**: `_default_proxy_url` 设为 `None`
- **验收**: `rg -n "wechat\.nastool\.org" app/message/client/wechat.py` 无命中

#### Task 1.7: 修改企业微信占位符
- **文件**: `app/conf/moduleconf.py`
- **内容**: 企业微信 placeholder 改为 `https://qyapi.weixin.qq.com`
- **验收**: `rg -n "wechat\.nastool\.org" app/conf/moduleconf.py` 无命中

#### Task 1.8: 修改 CookieCloud 占位符
- **文件**: `app/plugins/modules/cookiecloud.py`
- **内容**: placeholder 改为 `http://localhost:8088`
- **验收**: `rg -n "nastool\.org" app/plugins/modules/cookiecloud.py` 无命中

### Phase 2: 消除 eval() RCE（P0，可并行）

#### Task 2.1: 完全重写 __test_connection（无 eval）
- **文件**: `web/action.py`
- **内容**:
  - 删除所有 `eval()` 调用
  - 普通网络测试：后端根据 `NETTEST_TARGETS` 白名单执行请求
  - Media Server 测试：只允许 Emby/Jellyfin/Plex 三个固定映射
  - 增加攻击回归用例到测试套件
- **验收**:
  - `rg -n "\beval\s*\(" web/action.py` 无命中
  - 攻击用例全部失败（见 5.4）
  - 合法用例全部通过

#### Task 2.2: TMDB proxies eval → ast.literal_eval
- **文件**: `app/media/tmdbv3api/tmdb.py`
- **内容**: 两处 `eval(proxies)` 改为 `ast.literal_eval(proxies) if proxies else None`
- **验收**: `rg -n "\beval\s*\(" app/media/tmdbv3api/tmdb.py` 无命中

#### Task 2.3: BrushTask rules eval → json.loads
- **文件**: `app/brushtask.py`
- **内容**: 两处 `eval(task.RSS_RULE)` / `eval(task.REMOVE_RULE)` 改为 `json.loads`
- **验收**: `rg -n "\beval\s*\(" app/brushtask.py` 无命中

#### Task 2.4: WordsHelper eval → safe_arith_eval
- **文件**: `app/helper/words_helper.py`
- **内容**: 实现 `safe_arith_eval()` 安全算术解析器，替换 `eval(offset_caculate)`
- **验收**:
  - `rg -n "\beval\s*\(" app/helper/words_helper.py` 无命中
  - 攻击用例全部失败（见 5.5）
  - 合法用例全部通过

### Phase 3: 硬化自动更新（P0）

#### Task 3.1: 禁用所有环境的自动更新
- **文件**: `web/action.py`
- **内容**: `update_system` 删除所有 `os.system`、`git`、`pip` 调用，所有环境统一返回提示信息
- **验收**:
  - `rg -n "os\.system|git\s|pip\s" web/action.py` 在 update_system 方法体内无命中
  - Web UI 点击更新后日志输出禁用提示

### Phase 4: 消除 pickle RCE（P0）

#### Task 4.1: tmdb 缓存改为 JSON + 新文件名
- **文件**: `app/helper/meta_helper.py`
- **内容**:
  - `pickle` → `json`
  - 缓存路径 `tmdb.dat` → `tmdb.json`
  - `rb`/`wb` → `r`/`w`
- **验收**:
  - `rg -n "pickle\.(load|loads)" app/helper/meta_helper.py` 无命中
  - 旧 `tmdb.dat` 不再被读取
  - 新 `tmdb.json` 为 JSON 格式

### Phase 5: 全局安全回归（P0，依赖 Phase 1-4）

#### Task 5.1: 全局 eval 零容忍
- **命令**: `rg -n "\beval\s*\(" app web --glob "*.py"`
- **期望**: 无输出

#### Task 5.2: 全局 pickle 残留检查
- **命令**: `rg -n "pickle\.(load|loads)" app web config.py initializer.py --glob "*.py"`
- **期望**: 仅命中 `web/backend/user.py:368`（内置只读文件）

#### Task 5.3: 全局 nastool.org 零容忍
- **命令**: `rg -n "nastool\.org|wechat\.nastool\.org|tmdb\.nastool\.org" app web config.py initializer.py --glob "*.py"`
- **期望**: 无输出

#### Task 5.4: 功能回归
- Web UI 登录、菜单渲染正常
- TMDB 媒体识别正常（确认 tmdb.nastool.org 移除后仍能直连官方 API）
- 刷流任务创建/编辑/运行正常
- 自定义识别词（含集偏移 EP+1/EP-2）正常
- 插件安装/卸载正常
- 网络连通性测试（设置页）正常
- Media Server 状态测试（Emby/Jellyfin/Plex）正常

---

## 八、任务依赖关系

```
Phase 1 (Task 1.1-1.8)  ← 互不依赖，可并行
Phase 2 (Task 2.1-2.4)  ← 互不依赖，可并行
Phase 3 (Task 3.1)       ← 独立
Phase 4 (Task 4.1)       ← 独立
Phase 5 (Task 5.1-5.4)   ← 依赖 Phase 1-4 全部完成
```
