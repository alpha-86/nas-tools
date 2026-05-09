# Plan 002: 视频名称映射动态配置

> 目标：将 `video_name_mapping.yaml` 的手动编辑改为 Web UI 弹窗动态配置，在文件整理页面为每个文件新增"名称映射"按钮，支持增删查映射关系。

---

## 一、项目背景

### 1.1 现状

nas-tools 在媒体识别流程中支持"视频名称映射"功能：当文件名/种子名被解析出某个标题名后，可通过 `video_name_mapping.yaml` 将该标题映射为另一个名称。这一机制的典型用途包括：

- 英文名 → 中文名：`coco` → `寻梦环游记`
- 缩写/别名 → 正式名：`cl` → `权欲之巅`
- 系列编号 → 统一名：`1_fantastic_beasts...` → `fantastic beasts...`
- 版本后缀 → 纯标题：`hero_director's_cut` → `英雄`

当前有 116 条映射，全部靠手动编辑 `/config/video_name_mapping.yaml`，然后通过 `Config.check_and_reload_video_name_mapping()` 的热重载机制（基于文件 mtime）生效。这带来了几个问题：

1. **操作门槛高**：用户需要 SSH 到服务器编辑 YAML，对非技术用户不友好
2. **容易出错**：YAML 格式要求严格（空格敏感），手动编辑容易破坏文件
3. **无法直观关联**：不知道当前识别出的标题名具体是哪个，不知道该不该加映射
4. **无法快速验证**：加完映射后需要重新触发识别才能确认是否生效

### 1.2 映射机制的完整链路

映射不是简单的"文件名替换"，而是在**媒体识别阶段**生效，影响最终的 `cn_name`/`en_name`，进而影响 TMDB 搜索和文件重命名：

```
原始文件名 ──→ MetaVideo 解析 ──→ __fix_name() ──→ get_video_name_mapping()
     │                              │                  │
     │                              ▼                  ▼
     │                         识别出标题名        查 YAML 字典
     │                              │                  │
     │                              ▼                  ▼
     │                         匹配到映射? ──是──→ 替换为映射值
     │                              │                  │
     │                              否                 ▼
     │                              │            返回映射后名称
     │                              ▼                  │
     └──────────────────────→ 保持原名 ←───────────────┘
```

关键点：映射作用于**识别出的标题名**，不是作用于文件名本身。比如文件名 `The.Long.Season.2017.mkv` 识别出 `en_name = "The Long Season"`，映射后变为 `en_name = "漫长的季节"`，后续 TMDB 搜索会用"漫长的季节"去匹配中文条目。

### 1.3 目标

在"媒体整理 → 文件整理"页面，每个文件已有 7 个按钮（识别/转移/刮削/下载字幕/硬链接查询/重命名/删除），在"识别"按钮后新增"名称映射"按钮：

1. 点击弹出 Modal，自动填充文件名和识别出的名称
2. 可输入映射目标名，一键保存到 YAML
3. 如果已有映射，自动填充当前映射值，可编辑更新或删除
4. 保存后利用已有的热重载机制立即生效，无需重启

---

## 二、现有逻辑梳理

### 2.1 后端：Config 类 (`config.py`)

| 方法 | 行号 | 功能 |
|------|------|------|
| `init_video_name_mapping()` | 153-166 | 启动时从 YAML 加载到 `_video_name_mapping` 字典 |
| `check_and_reload_video_name_mapping()` | 168-172 | 检查文件 mtime 变化则重新加载（热重载） |
| `get_video_name_mapping(name)` | 175-181 | 将 name 空格替换为`_`并小写后查字典，找不到返回原名 |
| `get_video_name_mapping_file()` | 297-301 | 返回 YAML 文件路径，默认 `/config/video_name_mapping.yaml` |

**关键点**：key 规范化规则为 `name.replace(' ','_').lower()`

**缺失**：无任何写入方法（set/delete/save），需新增。现有代码的 `getatime` 检测不可靠，需统一改为 `getmtime`。

### 2.2 后端：识别流程 (`app/media/meta/metavideo.py`)

调用链：文件名 → `MetaInfo` → `MetaVideo.__init__` → `__fix_name()` (line 159) → `Config().get_video_name_mapping(name)` → 返回映射后名称

`__fix_name` 对 `cn_name` 和 `en_name` 都会调用，映射在识别阶段最后一步生效。

### 2.3 后端：Web Action (`web/action.py`)

- `name_test` action (line 2041)：调用 `Media().get_media_info()`，返回 `mediainfo_dict` 含 `name`、`title`、`org_string` 等字段
- 注册模式：`__init__` 中 `_actions` 字典映射命令名到方法
- `__rename_file` (line 4066)：简单的文件重命名 action，展示静态方法的写法
- 已有的 `__get_sub_path` (line ~3950)：文件树数据的 action

### 2.4 前端：文件整理页面 (`web/templates/rename/mediafile.html`)

- 文件列表模板 `mediafile_item_template` (line 422-464)：每个文件卡片的按钮区，7 个按钮横向排列
- 识别按钮调用 `mediafile_name_test()` → `media_name_test()` (functions.js:1454) → `ajax_post("name_test", ...)` → 结果显示在 `<custom-chips>` 组件
- Modal 模式：参照 `modal-mediafile-modify` (line 62-85) 的弹窗结构（header/body/footer）
- `ajax_post` 调用模式：`ajax_post("command_name", {param1: value1}, function(ret) { ... })`

### 2.5 实际目录案例

NAS 目录 `/mnt/nas23_video5/` 的实际结构：

- **movie/**：电影文件，如 `The.Godfather.1972.BluRay...`、`Coco.2017.UHD...`
- **tv/**：剧集目录，如 `Masters.of.the.Air.S01...`、`Squid.Game.S02...`
- 中文混合命名：`[三命].What.If.2025.S01...`、`[爱情怎么翻译？].Can.This.Love...`

这些实际文件是映射功能的主要应用场景 —— 英文名文件需要映射为中文名以便中文媒体库识别。

---

## 三、技术设计

### 3.1 Config 层：新增 CRUD 方法 (`config.py`)

#### 3.1.1 `save_video_name_mapping(self)`

将内存中 `_video_name_mapping` 写回 YAML 文件，加锁防并发，并更新 mtime 防止热重载重复加载。

```python
def save_video_name_mapping(self):
    mapping_config_file = self.get_video_name_mapping_file()
    with lock:
        with open(mapping_config_file, mode='w', encoding='utf-8') as sf:
            yaml = ruamel.yaml.YAML()
            yaml.dump(self._video_name_mapping, sf)
    self._video_name_mapping_mtime = os.path.getmtime(mapping_config_file)
```

> **注意**：
> - 使用模块顶部已有的 `lock = Lock()` (line 83) 保护写入，防止并发请求导致数据丢失
> - 现有代码用 `os.path.getatime()` 做 mtime 检测，这里写完后用 `os.path.getmtime()` 更新时间戳，确保下次 `check_and_reload` 不会重复加载。同时应将 `init_video_name_mapping` 和 `check_and_reload_video_name_mapping` 中的 `getatime` 统一改为 `getmtime`，因为 `atime` 在很多系统上不可靠

#### 3.1.2 `set_video_name_mapping(self, key, value)`

Upsert 语义：key 不存在则新增，已存在则更新覆盖。新增和更新复用同一方法，不需要单独的 `update` 方法。

```python
def set_video_name_mapping(self, key, value):
    if not key or not value:
        return
    key_name = key.replace(' ', '_').lower()
    self._video_name_mapping[key_name] = value
    self.save_video_name_mapping()
```

#### 3.1.3 `delete_video_name_mapping(self, key)`

```python
def delete_video_name_mapping(self, key):
    if not key:
        return
    key_name = key.replace(' ', '_').lower()
    self._video_name_mapping.pop(key_name, None)
    self.save_video_name_mapping()
```

#### 3.1.4 `list_video_name_mapping(self, name=None)`

```python
def list_video_name_mapping(self, name=None):
    self.check_and_reload_video_name_mapping()
    if name:
        key_name = name.replace(' ', '_').lower()
        value = self._video_name_mapping.get(key_name)
        if value:
            return {key_name: value}
        return {}
    return dict(self._video_name_mapping)
```

### 3.2 Action 层：新增 3 个端点 (`web/action.py`)

在 `_actions` 字典注册：

```python
"get_video_name_mappings": self.__get_video_name_mappings,
"set_video_name_mapping": self.__set_video_name_mapping,
"delete_video_name_mapping": self.__delete_video_name_mapping,
```

#### `__get_video_name_mappings(data)`

```python
@staticmethod
def __get_video_name_mappings(data):
    name = data.get("name")
    result = Config().list_video_name_mapping(name)
    return {"code": 0, "data": result}
```

#### `__set_video_name_mapping(data)`

新增和更新复用同一端点（upsert）。

```python
@staticmethod
def __set_video_name_mapping(data):
    key = data.get("key")
    value = data.get("value")
    if not key or not value:
        return {"code": 1, "msg": "原始名称和映射名称不能为空"}
    try:
        Config().set_video_name_mapping(key, value)
        return {"code": 0, "msg": "保存成功"}
    except Exception as e:
        return {"code": 1, "msg": str(e)}
```

#### `__delete_video_name_mapping(data)`

```python
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

### 3.3 前端：按钮与弹窗 (`mediafile.html`)

#### 3.3.1 新增按钮

在 `mediafile_item_template` (line 450) 的"识别"按钮后插入：

```html
<button onclick='show_name_mapping_modal("{FILENAME}", "{FILEPOS}")' class="btn btn-sm btn-pill">名称映射</button>
```

按钮顺序变为：识别 → **名称映射** → 转移 → 刮削 → 下载字幕 → 硬链接查询 → 重命名 → 删除

#### 3.3.2 弹窗 Modal 设计

```
┌──────────────────────────────────────────────┐
│  名称映射配置                            [×]  │
├──────────────────────────────────────────────┤
│  文件名称:  The.Long.Season.2017...    (只读) │
│  识别名称:  The Long Season             (只读) │
│  映射名称:  [ 漫长的季节           ]  (可编辑) │
│                                              │
│  (已有映射时: 输入框自动填充当前值,            │
│   修改后点保存即更新; 点删除可移除映射)         │
│                                              │
├──────────────────────────────────────────────┤
│  [取消]         [删除映射]      [保存映射]     │
└──────────────────────────────────────────────┘
```

- **新建映射**：识别名称无映射时，输入框为空，填写后点"保存映射"
- **已有映射**：输入框自动填充当前映射值，可修改后点"保存映射"更新，也可点"删除映射"移除
- "删除映射"按钮仅在已有映射时显示（通过 `d-none` class 控制）

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
          <label class="form-label">识别名称</label>
          <input type="text" id="name_mapping_source" class="form-control" readonly>
        </div>
        <div class="mb-3">
          <label class="form-label required">映射名称</label>
          <input type="text" id="name_mapping_target" class="form-control" placeholder="输入映射后的名称">
        </div>
        <input type="hidden" id="name_mapping_key">
        <input type="hidden" id="name_mapping_has_existing" value="0">
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-link me-auto" data-bs-dismiss="modal">取消</button>
        <a id="name_mapping_delete_btn" href="javascript:delete_name_mapping()" class="btn btn-danger d-none">删除映射</a>
        <a href="javascript:save_name_mapping()" class="btn btn-primary">保存映射</a>
      </div>
    </div>
  </div>
</div>
```

#### 3.3.3 JavaScript 函数

**`show_name_mapping_modal(name, id)`**

1. 设置文件名（只读，`#name_mapping_filename`）
2. 尝试从 `#testresults_{id}` 的 chips 组件提取识别名称（`name` 字段）
3. 如果没有识别结果，先自动触发 `mediafile_name_test`
4. 设置识别名称（只读，`#name_mapping_source`）
5. 设置隐藏字段 `#name_mapping_key` = `source.replace(/\s+/g, '_').toLowerCase()`
6. `ajax_post("get_video_name_mappings", {name: source})` 查询已有映射
7. **如果返回有映射**：填充 `#name_mapping_target` 为当前映射值 + 显示 `#name_mapping_delete_btn`（移除 `d-none`）
8. **如果无映射**：清空 `#name_mapping_target` + 隐藏 `#name_mapping_delete_btn`（添加 `d-none`）
9. 显示 modal

**`save_name_mapping()`**

1. 获取 source（`#name_mapping_source`）和 target（`#name_mapping_target`）
2. 校验 target 非空（为空则 `addClass("is-invalid")`，return）
3. `ajax_post("set_video_name_mapping", {key: source, value: target})` — 新增和更新复用同一端点
4. 成功：隐藏 modal，`show_success_modal`（可选：自动重新触发识别让用户立即看到效果）

**`delete_name_mapping()`**

1. 从 `#name_mapping_source` 获取 source name
2. `show_confirm_modal("确定要删除该名称映射吗？", function() { ... })`
3. 确认后 `ajax_post("delete_video_name_mapping", {key: source})`
4. 成功：清空 `#name_mapping_target`，隐藏删除按钮，`show_success_modal`

---

## 四、交互流程

1. 用户浏览文件列表，点击"识别" → chips 显示识别结果（如 `name: The Long Season`）
2. 识别名称不正确或需要映射 → 点击"名称映射"
3. 弹窗自动填充：文件名 + 识别名称 + 映射目标（如果已有则自动填充）
4. 用户输入/修改映射目标（如"漫长的季节"），点击保存
5. 后端 `set_video_name_mapping` 写入 YAML，热重载机制立即生效
6. 用户再次点击"识别"，chips 中名称变为映射后的名称

---

## 五、文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `config.py` | 修改 | 新增 4 个方法；`getatime` → `getmtime`；加锁保护写入 |
| `web/action.py` | 修改 | 注册 3 个新 action + 对应方法 |
| `web/templates/rename/mediafile.html` | 修改 | 新增按钮 + Modal + JS 函数 |
| `docs/plan/002-video-name-mapping-ui.md` | 新增 | 本文档 |

---

## 六、验证方式

1. 启动服务 → 媒体整理 → 文件整理
2. 对一个文件点击"识别"，确认识别结果正常
3. 点击"名称映射"，弹窗显示文件名和识别名称，映射输入框为空，删除按钮隐藏
4. 输入映射目标，保存 → 检查 `video_name_mapping.yaml` 新增条目
5. 再次点击"识别"，确认名称已变为映射后的值
6. 再次点击"名称映射"，输入框自动填充当前映射值，删除按钮显示，可修改后保存更新
7. 点击"删除映射"确认删除 → 再次识别，确认恢复为原始名称
