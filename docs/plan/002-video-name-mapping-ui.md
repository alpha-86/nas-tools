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

### 2.1 保存原始识别名 (`metavideo.py`)

**问题**：已有映射时 `name_test` 返回的 `name` 已是映射后值（如"漫长的季节"），而 YAML key 是映射前的清洗后名称（如 "the_long_season"），二者不同导致查/删失败。

**修复**：`__fix_name()` 加 `apply_mapping` 参数，在 `MetaVideo.__init__` 中先清洗不映射获取 raw 值，再按 `get_name()` 优先级选择 `raw_name`，确保与最终展示名一一对应。

**`app/media/meta/_base.py`** — `MetaBase.__init__` line 159 新增：

```python
self.raw_name = None
```

**`app/media/meta/metavideo.py`** — `__fix_name()` 加 `apply_mapping` 参数（默认 `True`，向后兼容）：

```python
def __fix_name(self, name, apply_mapping=True):
    if not name:
        return name
    name = re.sub(r'%s' % self._name_nostring_re, '', name,
                  flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+', ' ', name)
    if name.isdigit() \
            and int(name) < 1800 \
            and not self.year \
            and not self.begin_season \
            and not self.resource_pix \
            and not self.resource_type \
            and not self.audio_encode \
            and not self.video_encode:
        if self.begin_episode is None:
            self.begin_episode = int(name)
            name = None
        elif self.is_in_episode(int(name)) and not self.begin_season:
            name = None
    if apply_mapping:
        name = Config().get_video_name_mapping(name)
    return name
```

**`MetaVideo.__init__` line 129-131** 改为：

```python
# 先清洗不映射，保存原始清洗值
raw_cn = self.__fix_name(self.cn_name, apply_mapping=False)
raw_en = self.__fix_name(self.en_name, apply_mapping=False)
# 再映射（apply_mapping=True 为默认值）
self.cn_name = self.__fix_name(self.cn_name)
self.en_name = StringUtils.str_title(self.__fix_name(self.en_name))
# 按 get_name() 优先级选择 raw_name，确保与最终展示名一致
# get_name() 逻辑：全中文 cn_name → en_name → 非全中文 cn_name
if self.cn_name and StringUtils.is_all_chinese(self.cn_name):
    self.raw_name = raw_cn
elif self.en_name:
    self.raw_name = raw_en
elif self.cn_name:
    self.raw_name = raw_cn
```

**说明**：
- `raw_name` = "清洗后、映射前"的名称 = 实际用于查 YAML 的 source name
- `apply_mapping=False` 时只做清洗（去干扰词、压缩空格、处理纯数字），不查映射
- `get_name()` 优先级：全中文 `cn_name` → `en_name` → 非全中文 `cn_name`，`raw_name` 按同样优先级选择，避免 cn_name/en_name 混淆

**`web/action.py`** — `mediainfo_dict()` 新增返回字段：

```python
"raw_name": media_info.raw_name or media_info.get_name(),
```

前端弹窗用 `raw_name` 做 mapping key，`name` 继续显示映射后的值。

### 2.2 Config CRUD (`config.py`)

**锁策略**：所有访问 `_video_name_mapping` 的路径（包括识别流程的读和 UI 写入）都走同一把 `threading.RLock()`（可重入锁）。`check_and_reload` 在锁内被调用时不会死锁。

**模块顶部**：

```python
import threading
# 替换原有的 lock = Lock()
lock = threading.RLock()
```

**`_save_video_name_mapping()`** — 内部方法，调用方已持锁：

```python
def _save_video_name_mapping(self):
    """内部方法，调用方必须已持有 lock"""
    mapping_config_file = self.get_video_name_mapping_file()
    os.makedirs(os.path.dirname(mapping_config_file), exist_ok=True)
    tmp = mapping_config_file + '.tmp'
    with open(tmp, mode='w', encoding='utf-8') as sf:
        ruamel.yaml.YAML().dump(self._video_name_mapping, sf)
    os.replace(tmp, mapping_config_file)
    self._video_name_mapping_mtime = os.path.getmtime(mapping_config_file)
```

**`get_video_name_mapping(name)`** — 识别流程调用，加锁保护：

```python
def get_video_name_mapping(self, name):
    if not name:
        return name
    with lock:
        self.check_and_reload_video_name_mapping()
        key_name = name.replace(' ', '_').lower()
        return self._video_name_mapping.get(key_name, name)
```

**`set_video_name_mapping(key, value)`** — 完整 read-modify-write 在锁内：

```python
def set_video_name_mapping(self, key, value):
    if not key or not value:
        return
    with lock:
        self.check_and_reload_video_name_mapping()
        key_name = key.replace(' ', '_').lower()
        self._video_name_mapping[key_name] = value
        self._save_video_name_mapping()
```

**`delete_video_name_mapping(key)`** — 同上：

```python
def delete_video_name_mapping(self, key):
    if not key:
        return
    with lock:
        self.check_and_reload_video_name_mapping()
        key_name = key.replace(' ', '_').lower()
        self._video_name_mapping.pop(key_name, None)
        self._save_video_name_mapping()
```

**`list_video_name_mapping(name=None)`** — 读操作也加锁（防读到半写状态）：

```python
def list_video_name_mapping(self, name=None):
    with lock:
        self.check_and_reload_video_name_mapping()
        if name:
            key_name = name.replace(' ', '_').lower()
            if key_name in self._video_name_mapping:
                return {key_name: self._video_name_mapping[key_name]}
            return {}
        return dict(self._video_name_mapping)
```

**`check_and_reload_video_name_mapping()` 修复** — 文件不存在时清空内存映射：

```python
def check_and_reload_video_name_mapping(self):
    mapping_config_file = self.get_video_name_mapping_file()
    if not os.path.exists(mapping_config_file):
        self._video_name_mapping = {}
        self._video_name_mapping_mtime = 0
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

### 3.2 Modal 弹窗

```
┌──────────────────────────────────────────────┐
│  名称映射配置                            [×]  │
├──────────────────────────────────────────────┤
│  文件名称:  The.Long.Season.2017...    (只读) │
│  原始名称:  The Long Season             (只读) │ ← raw_name（清洗后、映射前）
│  映射名称:  [ 漫长的季节           ]  (可编辑) │
│                                              │
├──────────────────────────────────────────────┤
│  [取消]      [删除映射]      [保存映射]       │
└──────────────────────────────────────────────┘
```

- **识别失败**（`name: "无法识别"`）：弹窗禁用保存按钮，提示"请先确认识别结果"
- **新建**：输入框为空，删除按钮隐藏（`d-none`）
- **已有**：自动填充映射值，删除按钮显示，保存即更新

Modal HTML 结构：

```html
<div class="modal modal-blur fade" id="modal-name-mapping" tabindex="-1" ...>
  <div class="modal-dialog modal-lg modal-dialog-centered" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">名称映射配置</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">文件名称</label>
          <input type="text" id="name_mapping_filename" class="form-control" readonly>
        </div>
        <div class="mb-3">
          <label class="form-label">原始名称</label>
          <input type="text" id="name_mapping_source" class="form-control" readonly>
        </div>
        <div class="mb-3">
          <label class="form-label required">映射名称</label>
          <input type="text" id="name_mapping_target" class="form-control" placeholder="输入映射后的名称">
        </div>
        <!-- 保存 filename 和 filepos，用于保存后自动重新识别 -->
        <input type="hidden" id="name_mapping_filename_hidden">
        <input type="hidden" id="name_mapping_filepos_hidden">
        <input type="hidden" id="name_mapping_has_existing" value="0">
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-link me-auto" data-bs-dismiss="modal">取消</button>
        <a id="name_mapping_delete_btn" href="javascript:delete_name_mapping()" class="btn btn-danger d-none">删除映射</a>
        <a id="name_mapping_save_btn" href="javascript:save_name_mapping()" class="btn btn-primary">保存映射</a>
      </div>
    </div>
  </div>
</div>
```

### 3.3 JS 函数（唯一实现路径：弹窗内自行 name_test）

**`show_name_mapping_modal(name, id)`**

不依赖 chips 缓存，弹窗打开时自行请求识别结果：

```javascript
function show_name_mapping_modal(name, id) {
    // 保存 filename 和 filepos，供 save/delete 后自动重新识别
    $("#name_mapping_filename_hidden").val(name);
    $("#name_mapping_filepos_hidden").val(id);
    $("#name_mapping_filename").val(name);
    $("#name_mapping_target").removeClass("is-invalid");

    // 自行请求识别结果（含 raw_name）
    ajax_post("name_test", {"name": name}, function(ret) {
        if (ret.code !== 0 || !ret.data || ret.data.name === "无法识别") {
            $("#name_mapping_source").val("无法识别");
            $("#name_mapping_target").val("").prop("disabled", true);
            $("#name_mapping_save_btn").addClass("disabled");
            $("#name_mapping_delete_btn").addClass("d-none");
            $("#modal-name-mapping").modal('show');
            return;
        }

        let raw_name = ret.data.raw_name || ret.data.name;
        $("#name_mapping_source").val(raw_name);
        $("#name_mapping_target").prop("disabled", false);
        $("#name_mapping_save_btn").removeClass("disabled");

        // 查询已有映射
        ajax_post("get_video_name_mappings", {name: raw_name}, function(ret2) {
            if (ret2.code === 0 && ret2.data && Object.keys(ret2.data).length > 0) {
                let mapped_value = Object.values(ret2.data)[0];
                $("#name_mapping_target").val(mapped_value);
                $("#name_mapping_delete_btn").removeClass("d-none");
                $("#name_mapping_has_existing").val("1");
            } else {
                $("#name_mapping_target").val("");
                $("#name_mapping_delete_btn").addClass("d-none");
                $("#name_mapping_has_existing").val("0");
            }
            $("#modal-name-mapping").modal('show');
        });
    });
}
```

**`save_name_mapping()`**

```javascript
function save_name_mapping() {
    let raw_name = $("#name_mapping_source").val();
    let target = $("#name_mapping_target").val();
    let filename = $("#name_mapping_filename_hidden").val();
    let filepos = $("#name_mapping_filepos_hidden").val();

    if (!target) {
        $("#name_mapping_target").addClass("is-invalid");
        return;
    }
    $("#name_mapping_target").removeClass("is-invalid");

    ajax_post("set_video_name_mapping", {key: raw_name, value: target}, function(ret) {
        if (ret.code === 0) {
            $("#modal-name-mapping").modal('hide');
            show_success_modal(ret.msg, function() {
                // 自动重新识别当前文件
                mediafile_name_test(filename, "testresults_" + filepos);
            });
        } else {
            show_fail_modal(ret.msg);
        }
    });
}
```

**`delete_name_mapping()`**

```javascript
function delete_name_mapping() {
    let raw_name = $("#name_mapping_source").val();
    let filename = $("#name_mapping_filename_hidden").val();
    let filepos = $("#name_mapping_filepos_hidden").val();

    show_confirm_modal("确定要删除该名称映射吗？", function() {
        ajax_post("delete_video_name_mapping", {key: raw_name}, function(ret) {
            if (ret.code === 0) {
                $("#modal-name-mapping").modal('hide');
                show_success_modal(ret.msg, function() {
                    mediafile_name_test(filename, "testresults_" + filepos);
                });
            } else {
                show_fail_modal(ret.msg);
            }
        });
    });
}
```

---

## 四、文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `app/media/meta/_base.py` | +1 行 | `self.raw_name = None` |
| `app/media/meta/metavideo.py` | 修 `__fix_name` + `__init__` | `apply_mapping` 参数 + 按 `get_name()` 优先级选 `raw_name` |
| `config.py` | +4 方法，修 2 方法 | CRUD（锁内 RMW）+ 原子写入 + 文件不存在清空 + getmtime |
| `web/action.py` | +3 action + 1 字段 | 新端点 + `mediainfo_dict` 返回 `raw_name` |
| `web/templates/rename/mediafile.html` | +1 按钮 + 1 Modal + JS | 弹窗内自行 name_test，不依赖 chips |

---

## 五、验证方式

1. **基本功能**：点击"识别" → chips 显示映射后的 `name`；点击"名称映射" → 弹窗显示 `raw_name`（清洗后、映射前）+ 空映射输入框 → 保存新建 → `video_name_mapping.yaml` 新增条目 → 再次"识别" → `name` 已变
2. **编辑已有映射**：再次弹窗 → `raw_name` 正确 + 自动填充当前映射值 + 删除按钮显示 → 修改后保存 → YAML 更新
3. **删除映射**：点击删除 → 确认 → YAML 条目移除 → 再次"识别" → 恢复原始名称
4. **raw_name 准确性**：名称包含干扰词（如 `XXX 字幕组`）时，`raw_name` 必须等于清洗后、映射前的名称，与 YAML key 一致
5. **并发安全**：同时保存两个不同映射，两个条目都不丢失，YAML 结构完整
6. **文件删除场景**：运行中删除 `video_name_mapping.yaml` → 再次识别 → 不使用旧映射（内存已清空）；首次保存自动创建文件
7. **识别刷新**：保存/删除后自动重新识别的是正确文件行（通过 hidden 字段 `filename_hidden` + `filepos_hidden`）
8. **无法识别分支**：识别失败时弹窗禁用保存，提示"请先确认识别结果"
