# Plan 002: 视频名称映射动态配置

> 目标：在文件整理页面新增"名称映射"按钮，通过弹窗动态增删改 `video_name_mapping.yaml`，不改原有识别/刮削/映射链路。

---

## 一、现状与痛点

`video_name_mapping.yaml` 是 key-value YAML 字典，在 `MetaVideo.__fix_name()` 末尾通过 `Config().get_video_name_mapping()` 生效。现有 116 条映射全部手动编辑，使用门槛高。

映射链路（**保持不变**）：

```
文件名 → MetaVideo 解析 → __fix_name() → get_video_name_mapping() → cn_name/en_name
                                                    ↑
                                              查 video_name_mapping.yaml
```

---

## 二、最小后端改动

### 2.1 保存原始识别名 (`metavideo.py` + `_base.py`)

问题：已有映射时 `name_test` 返回的 `name` 已是映射后值（如"漫长的季节"），无法用它作为 YAML key 查/删已有映射。

修复：在 `__fix_name` 覆盖前保存原始名。

**`app/media/meta/_base.py`** — `MetaBase.__init__` 新增一行：
```python
self.raw_name = None
```

**`app/media/meta/metavideo.py`** — `MetaVideo.__init__` line 129-131：
```python
self.raw_name = self.get_name()      # 新增：保存映射前原始名
self.cn_name = self.__fix_name(self.cn_name)
self.en_name = StringUtils.str_title(self.__fix_name(self.en_name))
```

**`web/action.py`** — `mediainfo_dict()` 新增返回字段：
```python
"raw_name": media_info.raw_name or media_info.get_name(),
```

前端用 `raw_name` 做 mapping key，`name` 继续显示映射后的值，互不影响。

### 2.2 Config CRUD (`config.py`)

**`save_video_name_mapping()`** — 写 YAML，加锁，确保父目录存在，原子写入：
```python
def save_video_name_mapping(self):
    mapping_config_file = self.get_video_name_mapping_file()
    os.makedirs(os.path.dirname(mapping_config_file), exist_ok=True)
    with lock:
        tmp = mapping_config_file + '.tmp'
        with open(tmp, mode='w', encoding='utf-8') as sf:
            ruamel.yaml.YAML().dump(self._video_name_mapping, sf)
        os.replace(tmp, mapping_config_file)
    self._video_name_mapping_mtime = os.path.getmtime(mapping_config_file)
```

**`set_video_name_mapping(key, value)`** — upsert：
```python
def set_video_name_mapping(self, key, value):
    if not key or not value:
        return
    key_name = key.replace(' ', '_').lower()
    self._video_name_mapping[key_name] = value
    self.save_video_name_mapping()
```

**`delete_video_name_mapping(key)`** — 删除：
```python
def delete_video_name_mapping(self, key):
    if not key:
        return
    key_name = key.replace(' ', '_').lower()
    self._video_name_mapping.pop(key_name, None)
    self.save_video_name_mapping()
```

**`list_video_name_mapping(name=None)`** — 查单条或全量，文件不存在时返回空：
```python
def list_video_name_mapping(self, name=None):
    self.check_and_reload_video_name_mapping()
    if name:
        key_name = name.replace(' ', '_').lower()
        return {key_name: self._video_name_mapping[key_name]} if key_name in self._video_name_mapping else {}
    return dict(self._video_name_mapping)
```

**`check_and_reload_video_name_mapping()` 修复** — 文件不存在时静默跳过（防 500）：
```python
def check_and_reload_video_name_mapping(self):
    mapping_config_file = self.get_video_name_mapping_file()
    if not os.path.exists(mapping_config_file):
        return
    now_mtime = os.path.getmtime(mapping_config_file)
    if now_mtime > self._video_name_mapping_mtime:
        self.init_video_name_mapping()
```

同步把 `init_video_name_mapping` 中的 `getatime` 改为 `getmtime`。

### 2.3 Action 端点 (`web/action.py`)

注册 3 个 action：

```python
"get_video_name_mappings": self.__get_video_name_mappings,
"set_video_name_mapping": self.__set_video_name_mapping,
"delete_video_name_mapping": self.__delete_video_name_mapping,
```

```python
@staticmethod
def __get_video_name_mappings(data):
    result = Config().list_video_name_mapping(data.get("name"))
    return {"code": 0, "data": result}

@staticmethod
def __set_video_name_mapping(data):
    key, value = data.get("key"), data.get("value")
    if not key or not value:
        return {"code": 1, "msg": "原始名称和映射名称不能为空"}
    try:
        Config().set_video_name_mapping(key, value)
        return {"code": 0, "msg": "保存成功"}
    except Exception as e:
        return {"code": 1, "msg": str(e)}

@staticmethod
def __delete_video_name_mapping(data):
    key = data.get("key")
    if not key:
        return {"code": 1, "msg": "原始名称不能为空"}
    try:
        Config().delete_video_name_mapping(key)
        return {"code": 0, "msg": "删除成功"}
    except Exception as e:
        return {"code": 1, "msg": str(e)}
```

---

## 三、前端改动 (`mediafile.html`)

### 3.1 按钮

`mediafile_item_template` 的"识别"按钮后插入：

```html
<button onclick='show_name_mapping_modal("{FILENAME}", "{FILEPOS}")' class="btn btn-sm btn-pill">名称映射</button>
```

### 3.2 识别结果缓存

`mediafile_name_test` 中把识别结果缓存到隐藏字段，供弹窗读取 `raw_name`：

```javascript
function mediafile_name_test(name, result_div, filepos) {
    media_name_test(name, result_div, function() {}, null);
    // 回调里把 raw_name 缓存到隐藏字段，供弹窗使用
}
```

更直接的做法：弹窗打开时自行 `ajax_post("name_test")` 获取完整结果（含 `raw_name`），不依赖 chips 解析。

### 3.3 Modal 弹窗

```
┌──────────────────────────────────────────────┐
│  名称映射配置                            [×]  │
├──────────────────────────────────────────────┤
│  文件名称:  The.Long.Season.2017...    (只读) │
│  原始名称:  The Long Season             (只读) │ ← raw_name
│  映射名称:  [ 漫长的季节           ]  (可编辑) │
│                                              │
├──────────────────────────────────────────────┤
│  [取消]      [删除映射]      [保存映射]       │
└──────────────────────────────────────────────┘
```

- **识别失败**（`name: "无法识别"`）：弹窗禁用保存按钮，提示"请先确认识别结果"
- **新建**：输入框为空，删除按钮隐藏
- **已有**：自动填充映射值，删除按钮显示，保存即更新

### 3.4 JS 函数（按正确时序）

**`show_name_mapping_modal(name, id)`**

同步流程，无竞态：

1. 填充文件名（只读）
2. `ajax_post("name_test", {name: filename})` 获取识别结果（含 `raw_name`）
3. 回调中处理：
   - `raw_name == null` 或 `name == "无法识别"` → 填充"无法识别"，禁用保存按钮，显示 modal
   - 否则填充原始名称，检查已有映射
4. `ajax_post("get_video_name_mappings", {name: raw_name})` 查已有映射
5. 回调中：有映射则填充目标值 + 显示删除按钮；无映射则清空 + 隐藏删除按钮
6. 显示 modal

**`save_name_mapping()`**

1. 取 `raw_name` 和 `target`
2. 校验 target 非空
3. `ajax_post("set_video_name_mapping", {key: raw_name, value: target})`
4. 成功后隐藏 modal，`show_success_modal`，自动重新触发识别

**`delete_name_mapping()`**

1. `show_confirm_modal` 确认
2. `ajax_post("delete_video_name_mapping", {key: raw_name})`
3. 成功后清空目标值，隐藏删除按钮

---

## 四、文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `app/media/meta/_base.py` | +1 行 | `self.raw_name = None` |
| `app/media/meta/metavideo.py` | +1 行 | 映射前保存 `self.raw_name` |
| `config.py` | +4 方法，修 2 方法 | CRUD + 锁 + 原子写入 + 文件不存在保护 + getmtime |
| `web/action.py` | +3 action + 1 字段 | 新端点 + `mediainfo_dict` 返回 `raw_name` |
| `web/templates/rename/mediafile.html` | +1 按钮 + 1 Modal + JS | 弹窗 + 异步时序 + 无法识别分支 |

---

## 五、验证方式

1. 点击"识别" → chips 显示映射后的 `name`，检查 DOM 确认 `raw_name` 正确
2. 点击"名称映射" → 弹窗显示原始名称 + 空映射输入框 → 保存新建
3. 再次"识别" → `name` 已变 → 再次弹窗 → 自动填充当前映射值，可修改更新
4. 点击"删除映射" → 确认 → 再次"识别" → 恢复原始名称
5. 删除 `video_name_mapping.yaml` → 重启 → 首次保存自动创建文件
