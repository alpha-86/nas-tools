# Plan 009: Security Audit Remediation — 完整安全问题覆盖清单

> 目标：全面消除数据外传隐患、RCE 攻击面、供应链风险、TLS 中间人攻击面、SSRF、弱口令；完成 Session Cookie 加固，并登记 CSRF 残余风险/P1 后续。

---

## 一、安全问题汇总

| # | 类别 | 问题 | 风险等级 | 影响 |
|---|---|---|---|---|
| 1 | 数据外传 | `nastool.org` 遥测接口已失效并被域名劫持，所有请求 302 重定向到 `survey-smiles.com`（DNS 不可解析） | **高** | 验证码图片、插件列表、版本号被发送至未知第三方；功能超时卡顿 |
| 2 | RCE | 4 处 `eval()` 执行用户可控输入 | **高** | 认证后可执行任意 Python 代码 |
| 3 | RCE | `pickle.load()` 反序列化用户可写文件 | **中** | 篡改缓存文件可导致启动时 RCE |
| 4 | 供应链 | `update_system()` 使用 `git reset --hard` + `pip install` 无签名校验 | **高** | Git 仓库被劫持可导致任意代码执行 |
| 5 | TLS MITM | 全局 `verify=False`（10 处）禁用所有出站 HTTPS 证书校验 | **高** | 中间人可拦截/篡改 TMDB、Telegram、PT 站点等所有 HTTPS 流量 |
| 6 | 供应链 | CloudflareSpeedTest 插件 `os.system` 下载并执行二进制，无校验和 | **高** | ghproxy.com/XIU2/CloudflareSpeedTest 被劫持后可执行恶意二进制 |
| 7 | SSRF | `__test_connection` 允许任意 `eval(command)`，可访问内网任意地址 | **高** | 认证后可扫描/攻击内网服务 |
| 8 | 反序列化 | `ruamel.yaml.YAML().load(f)` 使用默认 loader | **中** | YAML 文件中若被注入恶意构造，可能导致对象反序列化 |
| 9 | 信息泄露 | API key / token 大量通过 URL query string 传输 | **中** | 密钥出现在 access logs、浏览器历史、Referer headers、代理日志中 |
| 10 | 弱口令 | 默认 `login_password = "password"` | **高** | 新安装实例可被任何人登录 |
| 11 | Session Cookie | Flask session cookie 无 `HttpOnly`/`Secure`/`SameSite`（CSRF 保护待后续迭代） | **中** | XSS 可窃取 session；跨站可伪造 POST 请求（CSRF 为残余风险） |
| 12 | 加密 | `user.sites.bin` 使用硬编码 Fernet 密钥 | **低** | 密钥已公开，但仅用于站点爬虫规则，不含用户凭证 |

---

## 二、方案

### 2.1 总体策略

```
Phase 1: 移除 nastool.org 遥测（P0，可立即执行）
    ├─ 禁用 PluginHelper 的三个远程调用
    ├─ 禁用 OcrHelper 远程 OCR
    ├─ 禁用版本检查远程调用
    ├─ 移除 tmdb.nastool.org / wechat.nastool.org / nastool.org/cookiecloud
    ├─ 移除 initializer.py 启动上报
    └─ 移除 config.py 中 tmdb.nastool.org 域名

Phase 2: 消除 eval() RCE（代码中无 eval()）
    ├─ __test_connection: 完全删除 eval，后端白名单执行，同时阻断 SSRF
    ├─ tmdb proxies: ast.literal_eval 替代
    ├─ brushtask rules: json.loads 替代
    └─ words_helper: ast 安全算术解析替代（支持 EP+1/EP-2，不破坏表达式）

Phase 3: 硬化自动更新
    └─ 所有环境（含群晖）改为只提示手动更新，禁止任何 os.system/git/pip 自动执行

Phase 4: 消除 pickle RCE
    └─ tmdb 缓存改为 JSON 序列化，写入新文件 tmdb.json，不再读取旧 tmdb.dat

Phase 5: TLS 校验恢复
    └─ RequestUtils 默认 verify=True；仅对用户明确配置的自签名证书服务降级

Phase 6: CloudflareSpeedTest 供应链硬化
    ├─ P0: 禁用自动下载和自动执行外部二进制（手动放置二进制即可满足收口）
    └─ P1: 仅在未来恢复自动下载时触发，必须同时满足 SHA256 校验 + 默认关闭的显式开关 + subprocess 参数列表

Phase 7: YAML 安全加载
    └─ ruamel.yaml 显式使用 safe loader

Phase 8: API key 传输加固
    ├─ Telegram：迁移到原生 secret_token / X-Telegram-Bot-Api-Secret-Token；若选兼容方案则 query apikey 作为已脱敏例外保留
    └─ Slack / 本地转发：apikey 从 query string 改为 X-API-Key header

Phase 9: 弱口令消除
    └─ 默认密码改为强制随机生成，首次登录必须修改

Phase 10: Session Cookie 加固（本轮 P0）；CSRF 保护标记为 P1 残余风险
    ├─ P0（10.1）：启用 HttpOnly + SameSite=Lax，HTTPS 部署可选 Secure
    └─ P1（10.2）：CSRF token 引入为后续迭代（残余风险，不阻塞 P0 发布）
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
        测试连通性（无 eval，白名单执行，阻断 SSRF）
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
                    # 保留原 __net_test 的路径补全和代理选择逻辑
                    target = cmd
                    if target == "image.tmdb.org":
                        target = target + "/t/p/w500/wwemzKWzjKYJFfCeiB57q3r4Bcm.png"
                    if target == "qyapi.weixin.qq.com":
                        target = target + "/cgi-bin/message/send"
                    url = "https://" + target
                    if "themoviedb" in url or "telegram" in url or "fanart" in url or "tmdb" in url:
                        res = RequestUtils(proxies=Config().get_proxies(), timeout=5).get_res(url)
                    else:
                        res = RequestUtils(timeout=5).get_res(url)
                    ret = res is not None and res.ok
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
| `127.0.0.1:22` | `cmd not in NETTEST_WHITELIST` → 拒绝（SSRF 阻断） |
| `localhost:3000` | `cmd not in NETTEST_WHITELIST` → 拒绝（SSRF 阻断） |

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

#### 3.2.3 BrushTask rules (`app/brushtask.py:125-126`, `app/helper/db_helper.py`)

**写入端** (`db_helper.py`): 将 `str(item.get('rss_rule'))` 改为 `json.dumps(..., ensure_ascii=False)`，确保入库的是标准 JSON 字符串：

```diff
  import json

-                RSS_RULE=str(item.get('rss_rule')),
-                REMOVE_RULE=str(item.get('remove_rule')),
+                RSS_RULE=json.dumps(item.get('rss_rule') or {}, ensure_ascii=False),
+                REMOVE_RULE=json.dumps(item.get('remove_rule') or {}, ensure_ascii=False),
```

**读取端** (`brushtask.py`): 优先 `json.loads`，兼容旧数据 `ast.literal_eval`，读取成功后迁移保存为 JSON：

```python
import json
import ast

def _load_rule(rule_str):
    if not rule_str:
        return {}
    try:
        return json.loads(rule_str)
    except (json.JSONDecodeError, ValueError):
        try:
            val = ast.literal_eval(rule_str)
            if isinstance(val, dict):
                # 旧数据读取成功，由保存/编辑流程写回 JSON
                return val
            return {}
        except (ValueError, SyntaxError):
            return {}

# 使用
"rss_rule": _load_rule(task.RSS_RULE),
"remove_rule": _load_rule(task.REMOVE_RULE),
```

> **注意**：`json.loads` **不兼容** Python 字典字面量中的单引号（`'key': 'value'`）和 `True/False/None`。因此读取端必须保留 `ast.literal_eval` fallback。旧数据在首次读取成功后，应在保存时由写入端重写为 JSON，完成迁移。

#### 3.2.4 WordsHelper (`app/helper/words_helper.py:131`) — 安全算术解析

**`ast.literal_eval` 会破坏 `EP+1` / `EP-2` 这类算术表达式，不可直接使用。** 需要自定义安全解析器：

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
| `()"__class__"` | `ValueError: Disallowed AST node: Subscript`（拒绝） |
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

### 3.5 恢复 TLS 证书校验（全局 verify=False）

**文件位置**：
- `app/utils/http_utils.py:65,73,85,92,106,115,132,144` — 8 处
- `app/media/tmdbv3api/tmdb.py:135,157` — 2 处
- 共 **10 处**

**风险等级**：**高**

**问题**：`RequestUtils` 的所有 HTTP 请求方法（`post`, `get`, `get_res`, `post_res`）以及 TMDB API 调用均硬编码 `verify=False`，全局禁用 TLS 证书验证。这意味着攻击者如果在网络路径中（如公共 WiFi、DNS 劫持、ISP 中间盒子）部署 MITM 代理，可以：
1. 拦截 TMDB API 响应，注入恶意媒体元数据
2. 拦截 Telegram/微信/Bark 等消息通知，窃取消息内容
3. 拦截 PT 站点 Cookie 和下载链接
4. 拦截 GitHub API、OpenAI API 等调用

**修复策略**：

1. `RequestUtils` 默认 `verify=True`，通过构造函数参数允许用户显式关闭（针对自签名证书的本地 Jellyfin/Emby/qBittorrent）。
2. 对公共互联网服务（TMDB、Telegram、Fanart、GitHub 等）始终 `verify=True`。
3. TMDB `tmdb.py` 中的 `verify=False` 一并移除。

```diff
# app/utils/http_utils.py

  def __init__(self, ...,
+              verify=True,
               ...):
      ...
+     self._verify = verify

  def post(self, url, data=None, json=None):
      ...
-                                         verify=False,
+                                         verify=self._verify,

  def get(self, url, params=None):
      ...
-                                      verify=False,
+                                      verify=self._verify,

  def get_res(self, url, params=None, allow_redirects=True, raise_exception=False):
      ...
-                                         verify=False,
+                                         verify=self._verify,

  def post_res(self, url, data=None, params=None, allow_redirects=True, files=None, json=None):
      ...
-                                         verify=False,
+                                         verify=self._verify,
```

```diff
# app/media/tmdbv3api/tmdb.py

- return requests.request(method, url, data=data, proxies=ast.literal_eval(proxies) if proxies else None, verify=False, timeout=10)
+ return requests.request(method, url, data=data, proxies=ast.literal_eval(proxies) if proxies else None, timeout=10)

- req = self._session.request(method, url, data=data, proxies=ast.literal_eval(self.proxies) if self.proxies else None, timeout=10, verify=False)
+ req = self._session.request(method, url, data=data, proxies=ast.literal_eval(self.proxies) if self.proxies else None, timeout=10)
```

> 用户的本地服务（Jellyfin、Emby、qBittorrent、Transmission）如果使用自签名证书，需要在各自的客户端初始化时显式传入 `verify=False` 或配置 `CERT_PATH`。

**验收命令**：

```bash
# 1. RequestUtils 中无硬编码 verify=False
rg -n "verify\s*=\s*False" app/utils/http_utils.py
# 期望：无命中

# 2. tmdb.py 中无 verify=False
rg -n "verify\s*=\s*False" app/media/tmdbv3api/tmdb.py
# 期望：无命中

# 3. 全局统计（仅允许用户可控的本地服务客户端中显式传入）
rg -n "verify\s*=\s*False" app web --glob "*.py"
# 期望：仅命中本地服务客户端（如 mediaserver/client/*, downloader/client/*）中用户显式配置的 verify=False
```

---

### 3.6 CloudflareSpeedTest 插件供应链风险

**文件位置**：`app/plugins/modules/cloudflarespeedtest.py`

**风险等级**：**高**

**问题**：
1. `os.system(cf_command)` 执行用户可控路径下的二进制（`self._cf_path + self._binary_name`），命令字符串拼接无转义。
2. `os.system(f'wget -P {self._cf_path} https://ghproxy.com/{download_url}')` 从 GitHub Release 下载二进制，无 SHA256 校验和验证。
3. `os.system(f'{unzip_command}')` 和 `os.system(f'rm -rf {self._cf_path}/{cf_file_name}')` 使用 `os.system` 而非安全 API。
4. `--no-check-certificate` 在 wget 中被使用。

**威胁模型**：
- `ghproxy.com` 是第三方加速代理，被劫持后可分发恶意二进制。
- `XIU2/CloudflareSpeedTest` GitHub Release 被入侵后，恶意二进制可在宿主机执行任意代码。
- `self._cf_path` 和 `self._additional_args` 来自用户配置，恶意配置可导致命令注入。

**修复策略**：

**P0 — 禁用自动下载和自动执行外部二进制**：

1. **删除 `__os_install` 中的自动下载逻辑**：不再调用 `wget` 下载外部二进制。插件启动时若二进制不存在，直接报错并停止，提示用户手动上传。
2. **删除 `os.system(cf_command)`**：不再通过 `os.system` / `subprocess` 自动执行外部二进制。
3. **移除 `--no-check-certificate`**：任何剩余的 `wget`/`curl` 调用恢复 TLS 校验。

```diff
  def __check_envirment(self):
      ...
-     # 自动下载安装逻辑
-     return self.__os_install(...)
+     # P0：禁用自动下载。若二进制不存在，提示用户手动上传
+     if not Path(f'{self._cf_path}/{self._binary_name}').exists():
+         self.error(f"CloudflareSpeedTest 二进制不存在，请手动下载并放置到 {self._cf_path}")
+         return False, None
+     return True, self._version
```

**P1 — 校验和校验或用户手动上传（增强）**：

- 若维护者决定保留有限的自动下载能力（需用户显式开启），则必须：
  1. 使用 `subprocess.run` 参数列表替代 `os.system`。
  2. 下载后计算 SHA256，与硬编码的已知 good hash 比对，不匹配则拒绝执行。
  3. 或改为用户手动上传二进制并配置路径，完全消除自动下载执行风险。

```python
# P1 增强示例：若保留下载，必须加 checksum
import hashlib

_KNOWN_SHA256 = {
    "v2.2.4": {
        "CloudflareST_linux_amd64.tar.gz": "abc123...",
    }
}

def _verify_checksum(filepath, expected):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest() == expected
```

**验收命令**：

```bash
# P0 验收：无自动下载（无 wget/curl 下载外部二进制）
rg -n "wget|curl|ghproxy\.com|github\.com.*CloudflareST" app/plugins/modules/cloudflarespeedtest.py
# 期望：无命中（或仅命中注释/文档）

# P0 验收：无 os.system / subprocess.run 执行外部二进制
rg -n "os\.system|subprocess" app/plugins/modules/cloudflarespeedtest.py
# 期望：无命中自动执行逻辑

# P1 增强验收：若保留下载，命中 SHA256 校验逻辑
rg -n "sha256|checksum|hashlib" app/plugins/modules/cloudflarespeedtest.py
# 期望：命中校验和验证代码
```

---

### 3.7 YAML 安全加载

**文件位置**：`app/media/category.py:39`

**风险等级**：**中**

**问题**：
```python
yaml = ruamel.yaml.YAML()
self._categorys = yaml.load(f)
```

`ruamel.yaml.YAML()` 默认使用 `RoundTripLoader`，虽然比 PyYAML 的 `unsafe_load` 安全，但仍可能解析 Python 对象标签（`!!python/object` 等），导致反序列化攻击。

**修复策略**：显式使用 safe loader：

```diff
-             yaml = ruamel.yaml.YAML()
-             self._categorys = yaml.load(f)
+             yaml = ruamel.yaml.YAML(typ='safe')
+             self._categorys = yaml.load(f)
```

> `ruamel.yaml.YAML(typ='safe')` 仅解析标准 YAML 标量、序列和映射，拒绝 `!!python/object` 等对象标签。

**验收命令**：

```bash
# 确认 category.py 中使用 safe loader
rg -n "yaml\.load" app/media/category.py
# 期望：命中行包含 SafeLoader 或 typ='safe'

# 全局确认无其他不安全的 yaml.load
rg -n "yaml\.(load|unsafe_load)" app web --glob "*.py"
# 期望：仅命中 yaml.safe_load 或 yaml.load 带 SafeLoader
```

---

### 3.8 API key query string 泄露

**文件位置**：
- `app/message/client/telegram.py:54,305` — `apikey=%s` 在 webhook URL
- `app/message/client/slack.py:37` — `apikey=%s` 在 webhook URL
- `app/mediaserver/client/jellyfin.py` 多处 — `api_key=%s` 在请求 URL
- `app/mediaserver/client/emby.py` 多处 — `api_key=%s` 在请求 URL

**风险等级**：**中**

**问题**：API key / token 通过 URL query string 传输，导致：
1. 出现在 HTTP access logs（服务端日志泄露）
2. 出现在浏览器历史记录
3. 通过 `Referer` header 泄露给第三方
4. 出现在代理日志、负载均衡日志、CDN 日志中
5. URL 长度限制可能导致截断

**修复策略**（客户端 + 服务端闭环）：

1. **客户端 URL 生成**（Telegram/Slack）：新生成的 webhook URL 不再包含 `apikey`：

```diff
# app/message/client/telegram.py
-                        self._webhook_url = "%s/telegram?apikey=%s" % (self._domain, self._api_key)
+                        self._webhook_url = "%s/telegram" % self._domain
```

```diff
# app/message/client/slack.py
-        self._ds_url = "http://127.0.0.1:%s/slack?apikey=%s" % (_web_port, _api_key)
+        self._ds_url = "http://127.0.0.1:%s/slack" % _web_port
```

2. **服务端认证兼容**（`web/security.py`）：`require_auth()` 增加 `X-API-Key` header 支持，短期保留 `request.args.get('apikey')` 兼容存量配置：

```diff
# web/security.py 中 require_auth()
        auth = request.headers.get("Authorization")
        if auth:
            auth = str(auth).split()[-1]
            if auth == Config().get_config("security").get("api_key"):
                return func(*args, **kwargs)
+       auth = request.headers.get("X-API-Key")
+       if auth:
+           if auth == Config().get_config("security").get("api_key"):
+               return func(*args, **kwargs)
        # 允许使用在api后面拼接 ?apikey=xxx 的方式进行验证
        # 从query中获取apikey
        auth = request.args.get("apikey")
        if auth:
            if auth == Config().get_config("security").get("api_key"):
                return func(*args, **kwargs)
```

3. **Jellyfin/Emby**：`api_key` 在 URL query string 中是 Jellyfin/Emby 官方 API 的设计（非 NAStool 可控）。此项标记为 **外部依赖，文档提醒**。

**验收命令**：

```bash
# 1. 客户端：Telegram webhook URL 不再包含 apikey
rg -n "apikey=" app/message/client/telegram.py
# 期望：无命中

# 2. 客户端：Slack ds_url 不再包含 apikey
rg -n "apikey=" app/message/client/slack.py
# 期望：无命中

# 3. 服务端：require_auth 支持 X-API-Key header
rg -n "X-API-Key" web/security.py
# 期望：命中 X-API-Key header 读取逻辑

# 4. 服务端：短期兼容旧 query string（允许存在，但不应是唯一认证方式）
rg -n "apikey" web/security.py
# 期望：命中 request.args.get('apikey') 兼容逻辑
```

---

### 3.9 消除默认弱口令

**文件位置**：`initializer.py:82`

**风险等级**：**高**

**问题**：
```python
login_password = _config.get("app", {}).get("login_password") or "password"
```

新安装时如果用户未配置密码，默认密码为 `"password"`。任何人都能猜中并登录系统，进而利用 `__test_connection` 的 RCE 等漏洞。

**修复策略**：

1. 默认密码改为强制随机生成（32 位随机字符串），并写入 config.yaml。
2. 首次登录后强制要求修改密码（或在 Web UI 登录页显示 "默认密码已生成，请查看日志"）。
3. 删除 `"password"` 回退值。

```diff
-    login_password = _config.get("app", {}).get("login_password") or "password"
+    login_password = _config.get("app", {}).get("login_password")
+    if not login_password:
+        login_password = StringUtils.generate_random_str(32)
+        _config['app']['login_password'] = login_password
+        overwrite_config = True
+        log.warn(f"【安全】首次启动已生成随机管理员密码，请查看 config.yaml 或日志获取。强烈建议立即修改。")
```

> 需要在 `initializer.py` 顶部确保 `StringUtils` 已 import。

**验收命令**：

```bash
# 1. 代码中无 "password" 默认回退
rg -n '\"password\"' initializer.py
# 期望：无命中（或仅命中注释/文档）

# 2. 新安装实例的默认密码为随机字符串（验证逻辑）
python3 -c "
import re
with open('initializer.py') as f:
    code = f.read()
assert 'or \"password\"' not in code, '仍存在默认弱口令回退'
print('[OK] 无默认弱口令回退')
"
```

---

### 3.10 Session Cookie / CSRF 加固

**文件位置**：`web/main.py:62-70`

**风险等级**：**中**

**问题**：
1. **无 `SESSION_COOKIE_HTTPONLY`**：JavaScript 可通过 `document.cookie` 读取 session cookie，XSS 攻击可直接窃取。
2. **无 `SESSION_COOKIE_SECURE`**：cookie 在 HTTP 连接下也会传输，中间人可窃取。
3. **无 `SESSION_COOKIE_SAMESITE`**：浏览器默认可能为 `Lax`（现代浏览器）或 `None`（旧浏览器），跨站 POST 请求可能携带 cookie。
4. **无 CSRF 保护**：Flask-WTF / CSRFProtect 未启用，`apiv1.py` 中大量 POST 端点无 CSRF token 验证。

**修复策略**：

1. **Session Cookie Hardening**：

```diff
  App.secret_key = _secret_key
  App.permanent_session_lifetime = datetime.timedelta(days=30)
+ App.config['SESSION_COOKIE_HTTPONLY'] = True
+ App.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
+ # 仅在 HTTPS 环境下启用 Secure（Docker 内网部署可能为 HTTP）
+ # 用户可通过环境变量控制：
+ if os.environ.get('NASTOOL_SESSION_SECURE', 'false').lower() == 'true':
+     App.config['SESSION_COOKIE_SECURE'] = True
```

2. **CSRF 保护（可选，标记为 P1）**：
   引入 Flask-WTF 的 CSRFProtect 需要大量前端改动（所有 POST form 添加 csrf_token）。考虑到本项目主要在内网/容器环境使用，且 API 端点使用 apikey 认证，CSRF 风险相对可控。**建议标记为 P1（后续迭代）**，本次先完成 session cookie hardening。

> **评估**：NAStool 的 Web UI 混合了传统 form POST 和 REST API（`apiv1.py`）。API 端点使用 `api_key` header 认证，不受 CSRF 影响。但传统 form POST（如登录、配置保存）使用 session cookie 认证，存在 CSRF 风险。由于前端改动量大，本次仅加固 cookie，CSRF token 引入作为后续任务。

**验收命令**：

```bash
# 1. Session cookie 配置存在
rg -n "SESSION_COOKIE_HTTPONLY|SESSION_COOKIE_SAMESITE|SESSION_COOKIE_SECURE" web/main.py
# 期望：命中 SESSION_COOKIE_HTTPONLY 和 SESSION_COOKIE_SAMESITE 配置行

# 2. 确认无 XSS 可直接读取 session cookie（通过 HttpOnly）
python3 -c "
with open('web/main.py') as f:
    code = f.read()
assert 'SESSION_COOKIE_HTTPONLY' in code, '缺少 SESSION_COOKIE_HTTPONLY'
assert 'SESSION_COOKIE_SAMESITE' in code, '缺少 SESSION_COOKIE_SAMESITE'
print('[OK] Session cookie 加固配置已存在')
"
```

---

## 四、文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `app/helper/plugin_helper.py` | 禁用三个远程调用 | install、report、statistic 返回空/None |
| `app/helper/ocr_helper.py` | 禁用远程 OCR | get_captcha_text 直接返回空字符串 |
| `web/backend/web_utils.py` | 禁用版本检查 | get_latest_version 返回 None, None |
| `config.py` | 移除 tmdb.nastool.org | TMDB_API_DOMAINS 白名单精简 |
| `initializer.py` | 移除 tmdb_domain 迁移 + 启动上报 + **弱口令消除** | 删除 nastool.org 相关逻辑；默认密码改为随机生成 |
| `app/message/client/wechat.py` | 移除默认代理 | _default_proxy_url 设为 None |
| `app/conf/moduleconf.py` | 修改占位符 | 企业微信默认代理改回官方地址 |
| `app/plugins/modules/cookiecloud.py` | 修改占位符 | CookieCloud 默认地址改为 localhost |
| `web/action.py` | **完全删除 eval + 硬化更新 + SSRF 白名单** | __test_connection 改为白名单执行；update_system 禁用所有自动更新 |
| `app/media/tmdbv3api/tmdb.py` | eval → ast.literal_eval + **移除 verify=False** | 两处 proxies 解析；恢复 TLS 校验 |
| `app/helper/db_helper.py` | str → **json.dumps** | BrushTask RSS_RULE / REMOVE_RULE 写入端改为标准 JSON |
| `app/brushtask.py` | eval → **json.loads + ast.literal_eval fallback** | RSS_RULE / REMOVE_RULE 读取端兼容旧数据；读取 legacy 成功后立即写回 JSON（详见 Task 2.3 迁移语义） |
| `app/helper/words_helper.py` | eval → **safe_arith_eval** | 自定义安全算术解析器，支持 EP+1/EP-2 |
| `app/helper/meta_helper.py` | pickle → json + 新文件名 | tmdb.dat → tmdb.json，不读旧文件 |
| `app/utils/http_utils.py` | **恢复 TLS 校验** | 默认 verify=True；通过参数允许显式关闭 |
| `app/plugins/modules/cloudflarespeedtest.py` | **供应链硬化** | P0: 禁用自动下载/执行外部二进制（手动放置二进制即可）；P1: **仅在未来恢复自动下载时**，必须同时满足 subprocess 参数列表 + SHA256 校验 + 默认关闭的显式开关 |
| `app/media/category.py` | **YAML safe loader** | ruamel.yaml 显式使用 safe loader |
| `app/message/client/telegram.py` | **API key 传输加固（Telegram 限制）** | 推荐迁移到原生 secret_token；若选兼容方案则保留 query apikey 作为已脱敏例外（Telegram 平台不发送 X-API-Key） |
| `app/message/client/slack.py` | **API key 脱离 query string** | ds_url 不再包含 apikey，本地转发改用 X-API-Key header |
| `web/security.py` | **require_auth 支持 X-API-Key** | 服务端增加 header 认证用于 Slack/本地转发；Telegram 走 secret_token 校验分支；短期兼容旧 query apikey |
| `web/main.py` | **Session cookie 加固（P0 本轮）** | 添加 SESSION_COOKIE_HTTPONLY / SESSION_COOKIE_SAMESITE |
| `docs/plan/009-tls-exceptions.md` | **新增产物（Task 5.3）** | 本地自签名 HTTPS 客户端审计清单（固定表格字段） |

---

## 五、可执行安全回归清单

以下命令在整改完成后必须全部通过。

### 5.1 eval() 零容忍验证

```bash
# 代码中不允许任何 eval()
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

### 5.4 verify=False 零容忍验证（公共互联网服务）

```bash
# http_utils.py 和 tmdb.py 中不允许硬编码 verify=False
rg -n "verify\s*=\s*False" app/utils/http_utils.py app/media/tmdbv3api/tmdb.py
# 期望：无命中

# 全局统计：仅允许用户可控的本地服务客户端中显式传入
rg -n "verify\s*=\s*False" app web --glob "*.py"
# 期望：仅命中 mediaserver/client/* 和 downloader/client/* 中显式配置的场景
```

### 5.5 __test_connection SSRF / 攻击回归验证

```bash
python3 <<'PY'
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

attacks = [
    '__import__("os").system("id")',
    'open("/etc/passwd").read()',
    '().__class__.__bases__[0].__subclasses__()',
    '"os|system"',
    'app.utils.system_utils|SystemUtils',
    'app.mediaserver.client.emby|System',
    '127.0.0.1:22',
    'localhost:3000',
    '169.254.169.254',
]
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

### 5.6 WordsHelper 攻击回归验证

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

### 5.7 pickle 文件隔离验证

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

### 5.8 自动更新硬化验证

```bash
# 确认 update_system 中不再有任何 os.system / git / pip 调用
rg -n "os\.system|git\s|pip\s|subprocess" web/action.py
# 期望：无命中（或仅命中其他无关方法，update_system 方法体内无命中）
```

### 5.9 弱口令消除验证

```bash
# 确认 initializer.py 中无默认 "password" 回退
rg -n 'or "password"' initializer.py
# 期望：无命中
```

### 5.10 Session Cookie 加固验证

```bash
# 确认 SESSION_COOKIE_HTTPONLY 和 SESSION_COOKIE_SAMESITE 已配置
rg -n "SESSION_COOKIE_HTTPONLY|SESSION_COOKIE_SAMESITE" web/main.py
# 期望：命中两行配置
```

---

## 六、风险与注意事项

1. **tmdb.json 格式迁移**：旧 `tmdb.dat` 被忽略，首次启动时缓存为空，TMDB 数据会从 API 重新获取。不影响功能，仅增加首次启动时的 API 调用量。旧 `tmdb.dat` 可由用户手动删除，也可保留（不再被读取，无安全风险）。

2. **OCR 禁用影响**：hdsky、opencd 等需要验证码的自动签到站点将无法自动识别验证码。用户需要手动在站点管理中获取 Cookie 后填入。这是安全与便利的权衡。

3. **TLS 校验恢复影响**：部分用户可能使用自签名证书的本地 Jellyfin/Emby/qBittorrent。这些用户需要：
   - 在配置中指定 `CERT_PATH`；或
   - 在各自客户端初始化时显式传入 `verify=False`。
   公共互联网服务（TMDB、Telegram、Fanart 等）不受影响，验证始终通过。

4. **__test_connection 白名单变更**：Media Server 测试不再支持任意 `module|Class`，仅限 Emby/Jellyfin/Plex。如需测试其他 Media Server，需扩展 `MEDIA_SERVER_MAP`。普通网络测试仅限 `NETTEST_TARGETS` 中的域名。

5. **企业微信代理配置**：`_default_proxy_url` 设为 `None` 后，未配置代理的群晖用户将直连微信官方 API。已配置 `wechat.nastool.org` 的存量用户不受影响（config.yaml 中已持久化的值不会被覆盖）。

6. **自动更新禁用**：在 Docker 环境中这是正确行为。对于非 Docker 的源码部署用户，需手动执行 `git pull`。建议在 README 中注明更新方式。

7. **CloudflareSpeedTest 插件**：由于上游 Release 不提供独立 SHA256 校验文件，短期方案是维护者手动计算每个版本的 SHA256 并硬编码。长期建议改为用户手动上传二进制并配置路径，完全消除自动下载执行的风险。

8. **API key 传输加固的向后兼容**：Telegram/Slack webhook handler 需要同时支持 Header 读取和 query string 读取（`request.args.get('apikey')`），以保证存量用户的 webhook URL 配置在短期内仍可工作。可在下一个大版本中完全移除 query string 支持。

9. **默认弱口令消除**：首次启动时生成的随机密码会被写入 config.yaml。用户需要查看日志获取。建议同步在 Web UI 登录失败页面提示 "默认密码已生成，请查看日志"。

10. **CSRF 保护**：本次未引入 Flask-WTF CSRFProtect（前端改动量过大），标记为后续迭代。Session cookie 的 `HttpOnly` + `SameSite=Lax` 已能显著降低风险。

---

## 七、开发任务分解

> **同文件串行约束**：以下任务对同一文件，必须由同一 owner 串行处理或合并提交，不得并行执行：
> - `web/action.py`：Task 2.1（`__test_connection`）与 Task 3.1（`update_system`）
> - `app/media/tmdbv3api/tmdb.py`：Task 2.2（`eval` → `ast.literal_eval`）与 Task 5.2（移除 `verify=False`）
> - `initializer.py`：Task 1.5（移除 nastool.org 配置写入）与 Task 9.1（弱口令消除）
> - `app/plugins/modules/cloudflarespeedtest.py`：Task 6.1（P0 禁用自动下载）与 Task 6.2（P1 未来恢复）
>
> 其余跨文件任务方可并行。

### Phase 1: 移除 nastool.org 遥测（P0，1.5 与 9.1 同文件串行，其余可并行）

#### Task 1.1: 禁用 PluginHelper 远程调用
- **文件**: `app/helper/plugin_helper.py`
- **内容**: 将 `install`, `report`, `statistic` 改为返回 `None`/`{}`
- **验收**: `rg -n "nastool\.org" app/helper/plugin_helper.py` 无命中

#### Task 1.2: 禁用 OcrHelper 远程 OCR
- **文件**: `app/helper/ocr_helper.py`
- **内容**: `get_captcha_text` 直接返回空字符串
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
- **内容**: 删除 TMDB 代理迁移逻辑和插件启动上报
- **同文件依赖**: 与 Task 9.1（弱口令消除）共享 `initializer.py`，必须串行或合并由同一 owner 提交
- **验收**: `rg -n "nastool\.org" initializer.py` 无命中

#### Task 1.6: 移除企业微信默认代理
- **文件**: `app/message/client/wechat.py`
- **内容**: `_default_proxy_url` 设为 `None`
- **验收**: `rg -n "wechat\.nastool\.org" app/message/client/wechat.py` 无命中

#### Task 1.7: 修改企业微信占位符
- **文件**: `app/conf/moduleconf.py`
- **内容**: placeholder 改为 `https://qyapi.weixin.qq.com`
- **验收**: `rg -n "wechat\.nastool\.org" app/conf/moduleconf.py` 无命中

#### Task 1.8: 修改 CookieCloud 占位符
- **文件**: `app/plugins/modules/cookiecloud.py`
- **内容**: placeholder 改为 `http://localhost:8088`
- **验收**: `rg -n "nastool\.org" app/plugins/modules/cookiecloud.py` 无命中

### Phase 2: 消除 eval() RCE（P0，2.1 与 3.1 同文件串行；2.2 与 5.2 同文件串行；其余可并行）

#### Task 2.1: 完全重写 __test_connection（无 eval，阻断 SSRF）
- **文件**: `web/action.py`
- **内容**: 删除 eval；普通网络测试用 NETTEST_TARGETS 白名单；Media Server 仅限 Emby/Jellyfin/Plex 固定映射
- **同文件依赖**: 与 Task 3.1（`update_system`）共享 `web/action.py`，必须串行或合并由同一 owner 提交
- **验收**: `rg -n "\beval\s*\(" web/action.py` 无命中；攻击用例全部失败（详见 Task 12.3 单测）

#### Task 2.2: TMDB proxies eval → ast.literal_eval
- **文件**: `app/media/tmdbv3api/tmdb.py`
- **内容**: 两处 `eval(proxies)` 改为 `ast.literal_eval`
- **同文件依赖**: 与 Task 5.2（移除 `verify=False`）共享 `tmdb.py`，必须串行或合并由同一 owner 提交
- **验收**: `rg -n "\beval\s*\(" app/media/tmdbv3api/tmdb.py` 无命中

#### Task 2.3: BrushTask rules eval → json.loads + ast.literal_eval fallback
- **文件**: `app/brushtask.py`（读取端）、`app/helper/db_helper.py`（写入端）
- **内容**:
  1. **写入端**：`str()` 改为 `json.dumps(..., ensure_ascii=False)`，所有新写入都是标准 JSON。
  2. **读取端**：优先 `json.loads`；失败回退到 `ast.literal_eval`（且必须确认返回值为 `dict`，否则返回空 `{}`，绝不抛 RCE 风险类异常）。
  3. **迁移语义（必须二选一并落地）**：
     - **方案 A（推荐，立即写回迁移 / eager migration）**：读取 legacy 数据并 `ast.literal_eval` 成功后，**立即**调用 `db_helper` 写回标准 JSON，并以 INFO 级日志记录迁移事件（task_id + 字段名）。
       - 优点：数据快速完成迁移，运行一次主流程后 legacy 数据基本清零，下次启动只走 JSON 快速路径。
       - 取舍：读取路径会产生一次数据库写入；需要确认调用上下文不在只读事务中。
     - **方案 B（懒迁移 / lazy migration，仅在用户编辑保存时写回）**：legacy 数据正常读取，但**不在读取路径主动写回**；只在用户通过 UI/接口编辑保存时由现有写入端覆盖为 JSON。
       - 优点：读取路径无副作用。
       - 取舍：从不编辑的 legacy 任务永远不会被迁移；需保留 `ast.literal_eval` fallback 直到下个大版本。
  4. **本次默认选择**：**方案 A（eager migration）**。理由：legacy 字符串虽然 `ast.literal_eval` 比 `eval` 安全，但仍属于历史污染数据，越早写回 JSON 越快收敛清理边界。
  5. **若维护者改选方案 B**：必须在 PR 中显式标注，并补充：在下个大版本前不删除 `ast.literal_eval` fallback；Task 12.2 单测同步调整为只验证读取路径，不验证写回。
- **配套测试**: Task 12.2（BrushTask legacy fallback 单测，含选定方案下的写回/不写回断言）
- **验收**: `rg -n "\beval\s*\(" app/brushtask.py` 无命中；`rg -n "json\.dumps" app/helper/db_helper.py` 命中写入逻辑；选定方案的迁移行为有日志/代码体现；Task 12.2 单测通过

#### Task 2.4: WordsHelper eval → safe_arith_eval
- **文件**: `app/helper/words_helper.py`
- **内容**: 实现 `safe_arith_eval()`，支持 EP+1/EP-2，拒绝所有非算术 AST 节点
- **配套测试**: Task 12.1（safe_arith_eval 单测）
- **验收**: `rg -n "\beval\s*\(" app/helper/words_helper.py` 无命中；Task 12.1 单测通过

### Phase 3: 硬化自动更新（P0，与 Task 2.1 同文件 `web/action.py`，必须串行）

#### Task 3.1: 禁用所有环境的自动更新
- **文件**: `web/action.py`
- **内容**: `update_system` 删除所有 `os.system`、`git`、`pip` 调用
- **同文件依赖**: Task 2.1 完成后再合入，或与 2.1 合并由同一 owner 一次提交
- **验收**: `rg -n "os\.system|git\s|pip\s" web/action.py` 在 update_system 方法体内无命中

### Phase 4: 消除 pickle RCE（P0）

#### Task 4.1: tmdb 缓存改为 JSON + 新文件名
- **文件**: `app/helper/meta_helper.py`
- **内容**: `pickle` → `json`；路径 `tmdb.dat` → `tmdb.json`
- **验收**: `rg -n "pickle\.(load|loads)" app/helper/meta_helper.py` 无命中

### Phase 5: 恢复 TLS 校验（P0，5.2 与 Task 2.2 同文件 `tmdb.py` 必须串行）

#### Task 5.1: RequestUtils 默认 verify=True
- **文件**: `app/utils/http_utils.py`
- **内容**: 构造函数新增 `verify=True` 参数；所有请求方法使用 `self._verify`
- **验收**: `rg -n "verify\s*=\s*False" app/utils/http_utils.py` 无命中

#### Task 5.2: TMDB API 恢复 TLS 校验
- **文件**: `app/media/tmdbv3api/tmdb.py`
- **内容**: 移除两处 `verify=False`
- **同文件依赖**: Task 2.2（`eval` → `ast.literal_eval`）必须先合入或同一 owner 合并提交
- **验收**: `rg -n "verify\s*=\s*False" app/media/tmdbv3api/tmdb.py` 无命中

#### Task 5.3: 梳理本地自签名 HTTPS 客户端兼容（P0 配套）
- **目标**: TLS 默认开启校验后，必须保证用户原本使用自签名证书的本地服务（Jellyfin、Emby、Plex、qBittorrent、Transmission 等）不被打断。
- **范围**: 审计以下目录中所有出站 HTTPS 调用：
  - `app/mediaserver/client/`
  - `app/downloader/client/`
  - `app/indexer/client/`（若存在）
  - 其他直接构造 `RequestUtils` 或 `requests.*` 的本地客户端
- **产物**（必须落地，不得分散在评论或多个文件）：
  - **文件路径**: `docs/plan/009-tls-exceptions.md`（新增）
  - **结构**: 单一表格，**字段固定**为以下 7 列：

    | 文件 | 调用点（行号） | 服务类型 | 配置来源 | 默认 verify | 例外理由 | 回归方式 |
    |---|---|---|---|---|---|---|

  - **字段约束**:
    - `文件`：相对仓库根的路径（如 `app/mediaserver/client/jellyfin.py`）
    - `调用点（行号）`：函数/方法名 + 行号（如 `__get_url:42`）
    - `服务类型`：`Jellyfin` / `Emby` / `Plex` / `qBittorrent` / `Transmission` / `本地 Indexer` 等枚举
    - `配置来源`：明确字段名（如 `mediaserver.cert_verify`、环境变量 `NASTOOL_VERIFY_TLS`、`CERT_PATH`）
    - `默认 verify`：`True` / `False`（统一建议 `True`）
    - `例外理由`：**仅允许"本地自签名证书"或"用户显式关闭"两类**，其它一律视为待修复
    - `回归方式`：具体回归步骤（如"本地 Jellyfin 自签名 + verify=False 配置；HTTPS GET /System/Info 返回 200"）
- **内容**:
  1. 按上述表格逐行登记每个本地客户端的当前 TLS 行为；
  2. 明确 `verify=False`/`CERT_PATH` 的配置来源（用户配置字段、环境变量、默认值）；
  3. 对所有显式传入 `verify=False` 的位置补充注释，引用本表格行号，说明"本地自签名证书允许此例外"；
  4. 编写迁移文档：对已在生产环境使用自签名证书的用户，给出明确的配置切换步骤（追加到同一 `009-tls-exceptions.md` 文末或单独 `## 迁移指南` 小节）。
- **保留命中允许范围**: `rg -n "verify\s*=\s*False" app web --glob "*.py"` 的剩余命中**只允许**出现在 `009-tls-exceptions.md` 表格列出的行上；其余任何命中视为漏审。
- **验收**:
  - `docs/plan/009-tls-exceptions.md` 存在，表格字段、枚举、行号均完整且与代码一致；
  - 剩余 `verify=False` 全部能在表格中找到对应行；
  - 至少手动回归一组自签名场景（建议使用本地 Jellyfin/qBittorrent 自签名证书），验证客户端通过显式配置后仍能连通；
  - 至少手动回归一组公共服务（TMDB / Telegram），确认 TLS 校验恢复后无证书错误。

### Phase 6: CloudflareSpeedTest 供应链硬化（6.1 P0；6.2 P1，与 6.1 同文件，必须串行）

#### Task 6.1: 禁用自动下载和自动执行外部二进制（P0）
- **文件**: `app/plugins/modules/cloudflarespeedtest.py`
- **内容**: 删除 `__os_install` 自动下载逻辑；删除 `os.system(cf_command)` 自动执行；二进制缺失时仅记录错误并要求用户自行放置（手动放置已在 P0 内完成，**不再单列为 P1**）
- **验收**: `rg -n "wget|curl|ghproxy\.com|github\.com.*CloudflareST" app/plugins/modules/cloudflarespeedtest.py` 无命中；`rg -n "os\.system|subprocess" app/plugins/modules/cloudflarespeedtest.py` 无命中自动执行逻辑

#### Task 6.2: 未来恢复自动下载时的安全基线（P1，仅在维护者决定重新启用自动下载时执行）
- **触发条件**: 仅当未来需要重新支持"自动下载二进制"时才需启动此任务；P0 已禁用自动下载，无此任务也满足收口。
- **文件**: `app/plugins/modules/cloudflarespeedtest.py`
- **必备要素**（三项同时满足，缺一不可）：
  1. **SHA256 校验和**：硬编码每个支持版本的二进制 SHA256，下载后立即比对，不匹配则删除并拒绝执行；
  2. **显式开启开关**：默认关闭，需用户在配置或环境变量中显式开启（如 `cloudflarespeedtest.allow_auto_download = true`），并在 UI/日志中告知供应链风险；
  3. **subprocess.run 参数列表**：所有外部命令调用必须使用 `subprocess.run([...], shell=False)` 的参数列表形式，禁止 `os.system` / `shell=True` / 字符串拼接命令。
- **同文件依赖**: Task 6.1 完成并合入后才能开始本任务
- **配套测试**: Task 12.6（CloudflareSpeedTest 自动下载基线测试，触发时启用）
- **验收**:
  - `rg -n "os\.system|shell\s*=\s*True" app/plugins/modules/cloudflarespeedtest.py` 无命中；
  - `rg -n "subprocess\.run\s*\(\s*\[" app/plugins/modules/cloudflarespeedtest.py` 命中参数列表形式；
  - `rg -n "sha256|hashlib" app/plugins/modules/cloudflarespeedtest.py` 命中校验逻辑；
  - 默认配置下自动下载关闭，单测覆盖开关与校验和分支

### Phase 7: YAML 安全加载（P1）

#### Task 7.1: ruamel.yaml safe loader
- **文件**: `app/media/category.py`
- **内容**: `ruamel.yaml.YAML(typ='safe')` 替代默认 loader
- **验收**: `rg -n "yaml\.load" app/media/category.py` 命中行包含 safe

### Phase 8: API key 传输加固（P1，Telegram 与 Slack 认证机制不同，分别处理）

> **关键约束**：Telegram Bot Platform 调用 NAStool 的 webhook 时**不会**发送任何自定义请求头（包括 `X-API-Key`）。Telegram 仅支持其原生的 `secret_token` 机制——通过 `setWebhook` 时传入 `secret_token` 参数，Telegram 在后续 webhook 请求中会附带 `X-Telegram-Bot-Api-Secret-Token` 请求头。因此 Telegram webhook 不能依赖通用 `X-API-Key` header，Slack/本地转发场景可以使用 `X-API-Key`。

#### Task 8.1: Telegram webhook 认证机制（不可用 X-API-Key）
- **文件**: `app/message/client/telegram.py`，`web/security.py`（或 Telegram webhook handler 所在文件）
- **内容**（二选一）：
  - **方案 A（推荐）**：迁移到 Telegram 原生 `secret_token`/`X-Telegram-Bot-Api-Secret-Token`：
    - `setWebhook` 时传入 `secret_token`（建议复用 `api_key` 或单独生成）；
    - webhook handler 校验 `request.headers.get("X-Telegram-Bot-Api-Secret-Token")`，匹配则放行；
    - 仍可短期保留 `request.args.get('apikey')` 作为存量兼容路径；
    - 新生成的 webhook URL 不再附带 `apikey` query。
  - **方案 B（兼容兜底）**：维持 `apikey` 通过 query string 传输，但明确文档化此例外原因（Telegram 平台限制），并将其纳入访问日志脱敏。
- **明确禁止**: 让 webhook handler 强制要求 `X-API-Key` header——Telegram 永远不会发送该 header，强制要求会破坏 webhook。
- **配套测试**: Task 12.4（Telegram secret_token / query apikey 兼容认证测试）
- **验收**:
  - 方案 A：`rg -n "X-Telegram-Bot-Api-Secret-Token" app web --glob "*.py"` 命中校验逻辑；新生成的 `_webhook_url` 不含 `apikey`；`rg -n "apikey=" app/message/client/telegram.py` 无命中。
  - 方案 B：`apikey` 通过 query 传输的注释/文档已落地；访问日志已脱敏 `apikey` 参数。
  - Task 12.4 单测通过。

#### Task 8.2: Slack webhook 脱离 query string（本地转发，可用 X-API-Key）
- **文件**: `app/message/client/slack.py`
- **背景**: `ds_url = "http://127.0.0.1:%s/slack?apikey=%s"` 是 NAStool 进程内的本地转发地址，请求方与处理方都受我方控制，可改用 `X-API-Key` header。
- **内容**: `ds_url` 不再包含 `apikey`；改由请求方（NAStool 内部）在调用时设置 `X-API-Key` header。
- **验收**: `rg -n "apikey=" app/message/client/slack.py` 无命中

#### Task 8.3: require_auth() 支持 X-API-Key header（仅 Slack/本地转发使用）
- **文件**: `web/security.py`
- **内容**: `require_auth()` 增加 `request.headers.get("X-API-Key")` 读取分支，短期保留 `request.args.get('apikey')` 兼容存量配置（Telegram 走 Task 8.1 自有路径）
- **明确范围**: 本任务的 `X-API-Key` header 仅服务于 Slack/本地转发及主动调用方，**不替代** Telegram webhook 的认证；Telegram 走 Task 8.1。
- **配套测试**: Task 12.5（X-API-Key header 认证测试）
- **验收**: `rg -n "X-API-Key" web/security.py` 命中认证逻辑；Task 12.5 单测通过

### Phase 9: 弱口令消除（P0，与 Task 1.5 同文件 `initializer.py` 必须串行）

#### Task 9.1: 默认密码改为随机生成
- **文件**: `initializer.py`
- **内容**: 删除 `"password"` 回退；未配置时生成 32 位随机字符串
- **同文件依赖**: Task 1.5 完成后再合入，或与 1.5 合并由同一 owner 一次提交
- **验收**: `rg -n 'or "password"' initializer.py` 无命中

### Phase 10: Session Cookie 加固（Task 10.1 为 P0 本轮）；CSRF 保护（Task 10.2）登记为 P1 残余风险

#### Task 10.1: 启用 HttpOnly + SameSite + Secure（P0，纳入本轮发布闸门）
- **文件**: `web/main.py`
- **内容**: 添加 `SESSION_COOKIE_HTTPONLY = True`、`SESSION_COOKIE_SAMESITE = 'Lax'`，支持 `NASTOOL_SESSION_SECURE` 环境变量开启 `SESSION_COOKIE_SECURE`
- **验收**: `rg -n "SESSION_COOKIE_HTTPONLY|SESSION_COOKIE_SAMESITE" web/main.py` 命中配置行

#### Task 10.2: CSRF 保护（P1 后续迭代，残余风险，**不阻塞 P0 发布**）
- **说明**: 引入 Flask-WTF CSRFProtect 需大量前端改动（所有 POST form 添加 csrf_token）。本次不实施，标记为后续任务。

### Phase 11A: P0 安全回归（依赖 Phase 1-5、6.1、9、10.1 全部完成；**不依赖 P1 / 残余 CSRF**）

> **收口原则**：本阶段是 P0 安全问题的最终验收。P0 整改的发布闸门**只看 Phase 11A 的通过情况**，不等待 Phase 6.2、Phase 7、Phase 8、Phase 11B 等 P1 任务。

#### Task 11A.1: eval 零容忍（P0）
- **命令**: `rg -n "\beval\s*\(" app web --glob "*.py"`
- **期望**: 无输出

#### Task 11A.2: pickle 残留（P0）
- **命令**: `rg -n "pickle\.(load|loads)" app web config.py initializer.py --glob "*.py"`
- **期望**: 仅命中 `web/backend/user.py:368`

#### Task 11A.3: nastool.org 零容忍（P0）
- **命令**: `rg -n "nastool\.org|wechat\.nastool\.org|tmdb\.nastool\.org" app web config.py initializer.py --glob "*.py"`
- **期望**: 无输出

#### Task 11A.4: verify=False 零容忍（P0，公共 HTTP 工具）
- **命令**: `rg -n "verify\s*=\s*False" app/utils/http_utils.py app/media/tmdbv3api/tmdb.py`
- **期望**: 无输出
- **配套**: Task 5.3 审计清单中列出的本地自签名客户端例外项需逐一核验注释与回归记录

#### Task 11A.5: 弱口令零容忍（P0）
- **命令**: `rg -n 'or "password"' initializer.py`
- **期望**: 无输出

#### Task 11A.6: 自动更新硬化（P0）
- **命令**: `rg -n "os\.system|git\s|pip\s|subprocess" web/action.py`
- **期望**: `update_system` 方法体内无命中

#### Task 11A.7: CloudflareSpeedTest P0 验收
- **命令**:
  - `rg -n "wget|curl|ghproxy\.com|github\.com.*CloudflareST" app/plugins/modules/cloudflarespeedtest.py`
  - `rg -n "os\.system|subprocess" app/plugins/modules/cloudflarespeedtest.py`
- **期望**: 均无命中自动下载/自动执行逻辑

#### Task 11A.8: Session Cookie 加固验收（P0/本轮）
- **命令**: `rg -n "SESSION_COOKIE_HTTPONLY|SESSION_COOKIE_SAMESITE" web/main.py`
- **期望**: 命中两行配置

#### Task 11A.9: P0 单测全部通过
- **依赖**: Phase 12 中 P0 相关单测（Task 12.1、12.2、12.3）
- **期望**: 全部通过

#### Task 11A.10: P0 功能回归
- Web UI 登录、菜单渲染正常
- TMDB 媒体识别正常
- 刷流任务创建/编辑/运行正常
- 自定义识别词（含集偏移 EP+1/EP-2）正常
- 插件安装/卸载正常
- 网络连通性测试（设置页）正常
- Media Server 状态测试（Emby/Jellyfin/Plex）正常
- TLS 校验恢复后，各公共 API 调用无证书错误
- 本地自签名客户端（Task 5.3 审计列表）按新配置仍能连通

### Phase 11B: P1 安全回归（依赖 Phase 6.2、7、8、10.2 等 P1 任务完成；不阻塞 P0 发布）

> **说明**：Phase 11B 单独成阶段，可在 P0 发布后按节奏滚动验收。**CSRF（10.2）作为残余风险**，其后续引入与本阶段同步进行，但不阻塞 P0 收口。

#### Task 11B.1: YAML safe loader（P1）
- **命令**: `rg -n "yaml\.load" app/media/category.py`
- **期望**: 命中行包含 `typ='safe'`

#### Task 11B.2: API key 传输加固（P1）
- **命令**:
  - `rg -n "apikey=" app/message/client/slack.py` → 无命中
  - Telegram 按 Task 8.1 选定方案验收（方案 A：`X-Telegram-Bot-Api-Secret-Token` 校验命中；方案 B：query 兼容已文档化并脱敏）
  - `rg -n "X-API-Key" web/security.py` → 命中

#### Task 11B.3: CloudflareSpeedTest P1（仅当 Task 6.2 启动时验收）
- **命令**:
  - `rg -n "os\.system|shell\s*=\s*True" app/plugins/modules/cloudflarespeedtest.py` → 无命中
  - `rg -n "subprocess\.run\s*\(\s*\[" app/plugins/modules/cloudflarespeedtest.py` → 命中参数列表形式
  - `rg -n "sha256|hashlib" app/plugins/modules/cloudflarespeedtest.py` → 命中校验和逻辑

#### Task 11B.4: P1 单测全部通过
- **依赖**: Phase 12 中 P1 相关单测（Task 12.4、12.5、12.6 若已启动）
- **期望**: 全部通过

#### Task 11B.5: CSRF 残余风险跟踪（P1 后续迭代）
- **状态**: 不在本计划内闭环；登记到长期安全任务列表，明确为残余风险，但 **不作为 P0 发布的阻塞项**
- **触发条件**: 后续单独立项引入 Flask-WTF CSRFProtect 时执行

### Phase 12: 显式单元/集成测试（不只用 rg，必须落地真实可运行的测试用例）

> **原则**：`rg` 只能证明源码字面层面的安全模式不存在，**无法证明运行时行为正确**。本阶段为关键安全修复落地真实测试代码，作为 Phase 11A/11B 验收的强制配套。

#### Task 12.1: safe_arith_eval 单元测试（P0，配套 Task 2.4）
- **文件**: `tests/test_safe_arith_eval.py`（新增）
- **测试用例**:
  - **合法**：`5+1=6`、`10-2=8`、`3*4=12`、`-5=-5`、`10//3=3`、含 EP 替换后的 `EP+1`/`EP-2`/`EP*3` 完整路径
  - **拒绝**：`__import__("os").system("id")`、`open("/etc/passwd")`、`(1).__class__`、字符串/列表/字典字面量、属性/下标访问、函数调用，**全部应抛 `ValueError`**
- **执行**: 使用项目自带 `nastools/` venv 执行 `pytest tests/test_safe_arith_eval.py`
- **验收**: 所有用例通过；CI（若有）将其纳入回归

#### Task 12.2: BrushTask legacy fallback 测试（P0，配套 Task 2.3）
- **文件**: `tests/test_brushtask_rule_loader.py`（新增）
- **前提**: 以 Task 2.3 选定的迁移方案为准（默认方案 A eager 写回；若选方案 B lazy 则移除/关闭对应断言）
- **测试用例**:
  - **新数据**（JSON 字符串）：`json.loads` 解析成功，返回 dict；
  - **旧数据 1**（Python 字典字面量，单引号）：`json.loads` 失败 → `ast.literal_eval` 成功 → 按迁移方案执行写回或不写回；
  - **旧数据 2**（含 `True`/`False`/`None`）：同上路径；
  - **恶意 payload**（如 `__import__("os").system("id")`）：`json.loads` 失败，`ast.literal_eval` 抛出/返回非 dict，最终返回 `{}`，不应有副作用；
  - **方案 A（eager migration）断言**：旧数据经读取后立即触发写入（mock 写入端），断言 `db_helper.save_brushtask`（或等效写入方法）被调用一次，且入参为标准 JSON 字符串；日志中出现 "migrated legacy rule" 等迁移关键字。
  - **方案 B（lazy migration）断言**（仅在选 B 时启用）：旧数据正常返回 dict，但读取路径不调用任何写入方法；写入断言仅在模拟 UI 保存时触发。
- **执行**: `pytest tests/test_brushtask_rule_loader.py`
- **验收**: 所有用例通过

#### Task 12.3: __test_connection 白名单测试（P0，配套 Task 2.1）
- **文件**: `tests/test_test_connection_whitelist.py`（新增）
- **测试用例**:
  - **Media Server 合法**：`app.mediaserver.client.emby|Emby`、`...jellyfin|Jellyfin`、`...plex|Plex`（mock 三个客户端的 `get_status`，断言被调用）
  - **Media Server 拒绝**：`app.utils.system_utils|SystemUtils`、`os|system`、`app.mediaserver.client.emby|System`（断言未实例化任何类，未发起任何调用，`ret=False`）
  - **网络合法**：`www.themoviedb.org`、`api.telegram.org` 等 NETTEST_TARGETS 中的项（mock `RequestUtils.get_res`）
  - **SSRF 拒绝**：`127.0.0.1:22`、`localhost:3000`、`169.254.169.254`、`__import__("os").system("id")`、`open("/etc/passwd").read()`（断言未发起任何请求，`ret=False`）
- **执行**: `pytest tests/test_test_connection_whitelist.py`
- **验收**: 所有用例通过；无任何攻击 payload 进入实际执行路径

#### Task 12.4: Telegram secret_token / query apikey 兼容认证测试（P1，配套 Task 8.1）
- **文件**: `tests/test_telegram_webhook_auth.py`（新增）
- **测试用例**（按 Task 8.1 选定方案落地）：
  - **方案 A（secret_token）**：
    - 携带正确 `X-Telegram-Bot-Api-Secret-Token` header 的请求被放行；
    - 携带错误 secret_token 的请求被拒绝；
    - 不携带 secret_token 的请求被拒绝（除非启用方案 B 兼容路径）；
    - **关键**：携带 `X-API-Key` header（不带 secret_token）的请求**不应通过**——验证 Telegram 路径不依赖通用 `X-API-Key`。
  - **方案 B（query apikey 兼容）**：
    - 携带正确 `?apikey=` 的请求被放行；
    - 错误 `apikey` 被拒绝；
    - 日志中 `apikey` 已被脱敏。
- **执行**: `pytest tests/test_telegram_webhook_auth.py`
- **验收**: 所有用例通过；不存在"误用 X-API-Key 替代 Telegram secret_token"的代码路径

#### Task 12.5: X-API-Key header 认证测试（P1，配套 Task 8.2/8.3）
- **文件**: `tests/test_require_auth_xapikey.py`（新增）
- **测试用例**:
  - 正确 `X-API-Key` header → 放行；
  - 错误 `X-API-Key` header → 拒绝；
  - `Authorization: Bearer <key>` → 放行（保留路径）；
  - `?apikey=<key>` query → 放行（短期兼容，含弃用警告 log）；
  - 错误 `?apikey=` → 拒绝；
  - **Slack 本地转发**：模拟 `ds_url` 调用，验证使用 `X-API-Key` header 通过认证
- **执行**: `pytest tests/test_require_auth_xapikey.py`
- **验收**: 所有用例通过

#### Task 12.6: CloudflareSpeedTest 自动下载安全基线测试（P1，仅当 Task 6.2 启动时执行）
- **文件**: `tests/test_cloudflarespeedtest_autodownload.py`（新增）
- **测试用例**:
  - **默认关闭**：未显式开启自动下载时，调用安装入口直接拒绝，不发起任何下载；
  - **开关开启 + 校验和正确**：mock 下载内容 SHA256 匹配硬编码值，安装成功；
  - **开关开启 + 校验和错误**：mock 下载内容 SHA256 不匹配，安装拒绝并删除临时文件；
  - **subprocess 调用形式**：断言所有 subprocess 调用使用参数列表 (`[...]`) 形式，禁止 `shell=True`
- **执行**: `pytest tests/test_cloudflarespeedtest_autodownload.py`（仅在 Task 6.2 启动时纳入回归）
- **验收**: 所有用例通过

> **运行说明**：使用项目已有 `nastools/` venv 进行验证（与 `MEMORY.md` 中记录的约定一致），不创建新虚拟环境。

#### Phase 12 总运行入口（避免只写散落测试）

**P0 测试（Phase 11A 前置条件）**：
```bash
# 使用 nastools/ venv
pytest tests/test_safe_arith_eval.py \
       tests/test_brushtask_rule_loader.py \
       tests/test_test_connection_whitelist.py
```

**P1 测试（Phase 11B 前置条件，按配套任务按需执行）**：
```bash
# Telegram webhook 认证
pytest tests/test_telegram_webhook_auth.py

# X-API-Key header 认证
pytest tests/test_require_auth_xapikey.py

# CloudflareSpeedTest 自动下载基线（仅在 Task 6.2 触发时执行）
pytest tests/test_cloudflarespeedtest_autodownload.py
```

**CI / 回归要求**：
- P0 全部单测必须通过方可合入 P0 最终 PR；
- P1 单测在 P0 发布后不阻塞发布，但 P1 任务合入前必须对应单测通过。

---

## 八、任务依赖关系

```
图例：→ 表示依赖；‖ 表示同文件必须串行；// 表示可并行；[P0]/[P1] 表示优先级

Phase 1  [P0]
  ├─ Task 1.1 plugin_helper.py        //
  ├─ Task 1.2 ocr_helper.py           //
  ├─ Task 1.3 web_utils.py            //
  ├─ Task 1.4 config.py               //
  ├─ Task 1.5 initializer.py          ‖ Task 9.1（同文件，串行）
  ├─ Task 1.6 wechat.py               //
  ├─ Task 1.7 moduleconf.py           //
  └─ Task 1.8 cookiecloud.py          //

Phase 2  [P0]
  ├─ Task 2.1 web/action.py           ‖ Task 3.1（同文件，串行）
  ├─ Task 2.2 tmdbv3api/tmdb.py       ‖ Task 5.2（同文件，串行）
  ├─ Task 2.3 brushtask.py + db_helper.py     → Task 12.2（测试）
  └─ Task 2.4 words_helper.py         → Task 12.1（测试）

Phase 3  [P0]
  └─ Task 3.1 web/action.py           ‖ Task 2.1（同文件，串行）

Phase 4  [P0]
  └─ Task 4.1 meta_helper.py          //（独立）

Phase 5  [P0]
  ├─ Task 5.1 http_utils.py           //
  ├─ Task 5.2 tmdbv3api/tmdb.py       ‖ Task 2.2（同文件，串行）
  └─ Task 5.3 本地自签名 HTTPS 客户端审计   依赖 5.1/5.2 完成后启动

Phase 6  [6.1 P0 / 6.2 P1]
  ├─ Task 6.1 cloudflarespeedtest.py  //（P0）
  └─ Task 6.2 cloudflarespeedtest.py  ‖ Task 6.1（同文件，串行；P1 触发时执行） → Task 12.6（测试）

Phase 7  [P1]
  └─ Task 7.1 category.py             //（独立）

Phase 8  [P1]
  ├─ Task 8.1 telegram.py + webhook handler  独立路径（Telegram 不可用 X-API-Key） → Task 12.4（测试）
  ├─ Task 8.2 slack.py                       //
  └─ Task 8.3 security.py (X-API-Key)        → 8.2 完成后合入（共用同一 X-API-Key 路径） → Task 12.5（测试）

Phase 9  [P0]
  └─ Task 9.1 initializer.py          ‖ Task 1.5（同文件，串行）

Phase 10 [10.1 P0 本轮 / 10.2 P1 后续]
  ├─ Task 10.1 web/main.py            //（独立）
  └─ Task 10.2 CSRF                   后续迭代，残余风险，不阻塞 P0

Phase 11A [P0 安全回归]  ← 依赖 Phase 1-5、6.1、9、10.1、Phase 12 中 12.1/12.2/12.3
                          ← **不依赖** Phase 6.2、7、8、10.2、11B
Phase 11B [P1 安全回归]  ← 依赖 Phase 6.2（若触发）、7、8、Phase 12 中 12.4/12.5/12.6

Phase 12 [测试]
  ├─ Task 12.1 safe_arith_eval           配套 2.4，P0
  ├─ Task 12.2 BrushTask legacy fallback 配套 2.3，P0
  ├─ Task 12.3 __test_connection 白名单  配套 2.1，P0
  ├─ Task 12.4 Telegram webhook auth     配套 8.1，P1
  ├─ Task 12.5 X-API-Key header          配套 8.2/8.3，P1
  └─ Task 12.6 CloudflareSpeedTest auto-download 配套 6.2，P1（触发时）
```

### 同文件串行依赖一览（必读）

| 文件 | 涉及任务 | 处理方式 |
|---|---|---|
| `web/action.py` | Task 2.1（`__test_connection`）+ Task 3.1（`update_system`） | 由同一 owner 串行处理或合并提交 |
| `app/media/tmdbv3api/tmdb.py` | Task 2.2（eval 替换）+ Task 5.2（移除 `verify=False`） | 由同一 owner 串行处理或合并提交 |
| `initializer.py` | Task 1.5（nastool.org 清理）+ Task 9.1（弱口令消除） | 由同一 owner 串行处理或合并提交 |
| `app/plugins/modules/cloudflarespeedtest.py` | Task 6.1（P0 禁用自动下载）+ Task 6.2（P1 未来恢复） | 6.1 必须先完成；6.2 仅触发条件满足时启动 |

### 发布闸门

- **P0 发布闸门**：仅以 **Phase 11A** 通过为准；不等待 Phase 11B / CSRF / Phase 6.2 / Phase 7 / Phase 8。
- **P1 滚动验收**：Phase 11B 在 P0 发布后按节奏验收，CSRF（10.2）登记为残余风险，单独立项跟踪。
