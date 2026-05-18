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
    ├─ 移除 wechat.nastool.org 默认代理
    └─ 移除 initializer.py 启动上报

Phase 2: 消除 eval() RCE
    ├─ __test_connection: 限制命名空间 + 白名单校验
    ├─ tmdb proxies: ast.literal_eval 替代
    ├─ brushtask rules: json.loads 替代
    └─ words_helper: ast.literal_eval 替代

Phase 3: 硬化自动更新
    └─ 改为只读通知模式，禁止自动 git reset + pip install

Phase 4: 消除 pickle RCE
    └─ tmdb.dat 缓存改为 JSON 序列化
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

#### 3.1.4 企业微信默认代理 (`app/conf/moduleconf.py`)

```diff
-                        "placeholder": "https://wechat.nastool.org"
+                        "placeholder": "https://qyapi.weixin.qq.com"
```

#### 3.1.5 启动上报 (`initializer.py`)

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

### 3.2 消除 eval() RCE

#### 3.2.1 __test_connection (`web/action.py:1652-1687`)

将无限制的 `eval()` 改为限制命名空间的受控执行：

```python
    @staticmethod
    def __test_connection(data):
        """
        测试连通性
        """
        command = data.get("command")
        ret = None
        if command:
            try:
                # 安全的 eval 命名空间：只允许访问预定义模块和类
                safe_globals = {"__builtins__": {}}
                safe_locals = {
                    "Config": Config,
                    "RequestUtils": RequestUtils,
                    "SystemUtils": SystemUtils,
                    "StringUtils": StringUtils,
                    "ExceptionUtils": ExceptionUtils,
                    "json": __import__("json"),
                    "os": __import__("os"),
                }
                module_obj = None
                if isinstance(command, list):
                    for cmd_str in command:
                        ret = eval(cmd_str, safe_globals, safe_locals)
                        if not ret:
                            break
                else:
                    if command.find("|") != -1:
                        module = command.split("|")[0]
                        class_name = command.split("|")[1]
                        module_obj = getattr(
                            importlib.import_module(module), class_name)()
                        if hasattr(module_obj, "init_config"):
                            module_obj.init_config()
                        ret = module_obj.get_status()
                    else:
                        ret = eval(command, safe_globals, safe_locals)
                Config().init_config()
                if module_obj:
                    if hasattr(module_obj, "init_config"):
                        module_obj.init_config()
            except Exception as e:
                ret = None
                ExceptionUtils.exception_traceback(e)
            return {"code": 0 if ret else 1}
        return {"code": 0}
```

> `safe_locals` 白名单按需扩展。核心原则：`__builtins__` 为空字典，禁止 `__import__`、`open`、`subprocess` 等危险函数。

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
  import ast

-               "rss_rule": eval(task.RSS_RULE),
-               "remove_rule": eval(task.REMOVE_RULE),
+               "rss_rule": ast.literal_eval(task.RSS_RULE) if task.RSS_RULE else {},
+               "remove_rule": ast.literal_eval(task.REMOVE_RULE) if task.REMOVE_RULE else {},
```

#### 3.2.4 WordsHelper (`app/helper/words_helper.py:131`)

```diff
  import ast

-               episode_num_offset_int = int(eval(offset_caculate))
+               episode_num_offset_int = int(ast.literal_eval(offset_caculate))
```

### 3.3 硬化自动更新 (`web/action.py:1185-1221`)

非群晖环境下禁止自动执行 git/pip：

```python
    def update_system(self):
        """
        更新（已硬化：不再自动执行 git reset + pip install）
        """
        if SystemUtils.is_synology():
            # 群晖套件保持原行为（由套件自身管理）
            if SystemUtils.execute('/bin/ps -w -x | grep -v grep | grep -w "nastool update" | wc -l') == '0':
                os.system('nastool update')
                self.restart_server()
        else:
            # Docker / 普通环境：仅通知有更新，不自动执行
            # 更新应通过重新拉取镜像或手动 git pull 完成
            log.warn("自动更新已禁用，请手动更新或重新部署容器")
        return {"code": 0}
```

### 3.4 消除 pickle RCE (`app/helper/meta_helper.py`)

将 `tmdb.dat` 缓存从 pickle 改为 JSON：

```diff
  import os
- import pickle
+ import json
  import random
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

---

## 四、文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `app/helper/plugin_helper.py` | 禁用三个远程调用 | install、report、statistic 返回空/None |
| `app/helper/ocr_helper.py` | 禁用远程 OCR | get_captcha_text 直接返回空字符串 |
| `web/backend/web_utils.py` | 禁用版本检查 | get_latest_version 返回 None, None |
| `app/conf/moduleconf.py` | 修改占位符 | 企业微信默认代理改回官方地址 |
| `initializer.py` | 移除启动上报 | 删除 PluginHelper().report 调用块 |
| `web/action.py` | 限制 eval + 硬化更新 | __test_connection 加 safe_locals；update_system 禁用自动更新 |
| `app/media/tmdbv3api/tmdb.py` | eval → ast.literal_eval | 两处 proxies 解析 |
| `app/brushtask.py` | eval → ast.literal_eval | RSS_RULE / REMOVE_RULE 解析 |
| `app/helper/words_helper.py` | eval → ast.literal_eval | offset_caculate 解析 |
| `app/helper/meta_helper.py` | pickle → json | tmdb.dat 缓存格式迁移 |
| `docs/plan/009-security-audit-remediation.md` | 新增 | 本计划文档 |

---

## 五、验证方式

### 5.1 nastool.org 遥测移除验证

```bash
# 启动服务后查看日志，确认无 nastool.org 相关请求超时
grep -i "nastool.org" logs/*.log || echo "OK: no nastool.org requests"

# 验证 PluginHelper 方法返回空
python3 -c "from app.helper import PluginHelper; print(PluginHelper.install('test'))"    # None
python3 -c "from app.helper import PluginHelper; print(PluginHelper.report(['test']))"    # None
python3 -c "from app.helper import PluginHelper; print(PluginHelper.statistic())"         # {}

# 验证 OcrHelper 返回空
python3 -c "from app.helper import OcrHelper; print(repr(OcrHelper().get_captcha_text()))"  # ''

# 验证版本检查返回 None
python3 -c "from web.backend.web_utils import WebUtils; print(WebUtils.get_latest_version())"  # (None, None)
```

### 5.2 eval() 消除验证

```bash
# 搜索确认代码中无 eval()（除了 re.compile 等合法用法和已被限制的 __test_connection）
grep -rn "\beval\s*(" app/ web/ --include="*.py" | grep -v "re.compile.*eval"
# 期望输出仅包含 __test_connection 中的受限制 eval
```

### 5.3 自动更新硬化验证

在 Web UI 中点击"检查更新"或调用 API，确认：
1. 不再执行 `git reset --hard`
2. 日志输出 `"自动更新已禁用，请手动更新或重新部署容器"`

### 5.4 pickle → JSON 验证

```bash
# 1. 删除旧 tmdb.dat
rm config/tmdb.dat

# 2. 启动服务，执行一次媒体识别（触发 TMDB 缓存写入）

# 3. 确认新缓存文件为 JSON 格式
python3 -c "import json; data=json.load(open('config/tmdb.dat')); print(type(data))"
# 期望: <class 'dict'>
```

---

## 六、风险与注意事项

1. **tmdb.dat 格式迁移**：旧的 pickle 格式缓存将在首次启动时失效，TMDB 数据会重新从 API 获取。不影响功能，仅增加首次启动时的 API 调用量。

2. **OCR 禁用影响**：hdsky、opencd 等需要验证码的自动签到站点将无法自动识别验证码。用户需要手动在站点管理中获取 Cookie 后填入。这是安全与便利的权衡。

3. **__test_connection 的 safe_locals 可能不完整**：如果某些连通性测试命令依赖了未列入 safe_locals 的类，会报 NameError。需在测试中覆盖所有 `ModuleConf.NETTEST_TARGETS` 中的命令类型。如发现问题，扩展 safe_locals 即可，不影响安全性。

4. **ast.literal_eval 限制**：`literal_eval` 只支持 Python 字面量（字符串、数字、列表、字典等），不支持函数调用。对于 `brushtask.py` 和 `tmdb.py` 中的场景（proxies 和 rules 都是数据结构），完全适用。

5. **企业微信代理配置**：将默认占位符从 `wechat.nastool.org` 改回 `qyapi.weixin.qq.com` 后，已配置 `wechat.nastool.org` 的存量用户不会受影响（config.yaml 中已持久化的值不会被覆盖）。仅影响新安装时的默认值。

6. **自动更新禁用**：在 Docker 环境中这是正确行为。对于非 Docker 的源码部署用户，需手动执行 `git pull`。建议在 README 中注明更新方式。

---

## 七、开发任务分解

### Phase 1: 移除 nastool.org 遥测（P0，可并行）

#### Task 1.1: 禁用 PluginHelper 远程调用
- **文件**: `app/helper/plugin_helper.py`
- **内容**: 将 `install`, `report`, `statistic` 改为返回 `None`/`{}`，注释原请求逻辑
- **验收**: 三个方法均不再发起 HTTP 请求

#### Task 1.2: 禁用 OcrHelper 远程 OCR
- **文件**: `app/helper/ocr_helper.py`
- **内容**: `get_captcha_text` 直接返回空字符串，注释 `_ocr_b64_url`
- **验收**: 调用 OCR 不发起网络请求，返回 `""`

#### Task 1.3: 禁用版本检查
- **文件**: `web/backend/web_utils.py`
- **内容**: `get_latest_version` 返回 `(None, None)`
- **验收**: 版本检查不发起网络请求

#### Task 1.4: 修改企业微信默认代理
- **文件**: `app/conf/moduleconf.py`
- **内容**: 占位符从 `https://wechat.nastool.org` 改为 `https://qyapi.weixin.qq.com`
- **验收**: 新安装默认显示官方 API 地址

#### Task 1.5: 移除启动上报
- **文件**: `initializer.py`
- **内容**: 删除 `PluginHelper().report` 调用块
- **验收**: 启动日志无插件上报相关输出

### Phase 2: 消除 eval() RCE（P0，可并行）

#### Task 2.1: 限制 __test_connection eval
- **文件**: `web/action.py`
- **内容**: 为 eval 添加 `safe_globals` 和 `safe_locals`，禁止访问 `__builtins__`
- **safe_locals 白名单**: `Config`, `RequestUtils`, `SystemUtils`, `StringUtils`, `ExceptionUtils`, `json`, `os`
- **验收**: 所有 NETTEST_TARGETS 连通性测试正常通过；注入攻击被阻断

#### Task 2.2: TMDB proxies eval → ast.literal_eval
- **文件**: `app/media/tmdbv3api/tmdb.py`
- **内容**: 两处 `eval(proxies)` 改为 `ast.literal_eval(proxies) if proxies else None`
- **验收**: TMDB 代理配置正常生效

#### Task 2.3: BrushTask rules eval → ast.literal_eval
- **文件**: `app/brushtask.py`
- **内容**: 两处 `eval(task.RSS_RULE)` / `eval(task.REMOVE_RULE)` 改为 `ast.literal_eval`
- **验收**: 刷流任务正常加载，规则解析正确

#### Task 2.4: WordsHelper eval → ast.literal_eval
- **文件**: `app/helper/words_helper.py`
- **内容**: `eval(offset_caculate)` 改为 `ast.literal_eval(offset_caculate)`
- **验收**: 自定义识别词偏移计算正常

### Phase 3: 硬化自动更新（P0）

#### Task 3.1: 禁用自动 git/pip 更新
- **文件**: `web/action.py`
- **内容**: 非群晖环境下 `update_system` 只记录日志，不执行 `git reset --hard` / `pip install`
- **验收**: 调用更新 API 后，不执行 git 操作，日志输出禁用提示

### Phase 4: 消除 pickle RCE（P0）

#### Task 4.1: tmdb.dat 改为 JSON
- **文件**: `app/helper/meta_helper.py`
- **内容**: `pickle.load/dump` → `json.load/dump`；文件打开模式 `rb`/`wb` → `r`/`w`
- **验收**: 删除旧 tmdb.dat 后，服务正常启动，新缓存为 JSON 格式

### Phase 5: 回归测试（P0，依赖 Phase 1-4）

#### Task 5.1: 功能回归
- Web UI 登录、菜单渲染正常
- TMDB 媒体识别正常
- 刷流任务创建/编辑/运行正常
- 自定义识别词正常
- 插件安装/卸载正常
- 网络连通性测试（设置页）正常

#### Task 5.2: 安全回归
- 全局搜索 `eval(` 确认仅保留受限制的 `__test_connection` 中的调用
- 全局搜索 `pickle` 确认仅 `user.py` 中用于加载内置 `user.sites.bin`（只读内置资源，风险可控）
- 确认无 nastool.org 硬编码 URL（除注释和文档外）

---

## 八、任务依赖关系

```
Phase 1 (Task 1.1-1.5)  ← 互不依赖，可并行
Phase 2 (Task 2.1-2.4)  ← 互不依赖，可并行
Phase 3 (Task 3.1)       ← 独立
Phase 4 (Task 4.1)       ← 独立
Phase 5 (Task 5.1-5.2)   ← 依赖 Phase 1-4 全部完成
```
