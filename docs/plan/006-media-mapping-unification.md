# Plan 006: 统一媒体映射配置

> 目标：用 `media_mapping.yaml` 统一替代 `video_name_mapping.yaml` 和 `tmdb_id_mapping.conf`，让文件管理页可以用同一个配置完成名称映射和 TMDB ID 指定。

---

## 一、背景与问题

当前代码里存在两套映射逻辑，但实际只有一套被持续使用：

| 配置 | 当前状态 | 计划处理 |
|---|---|---|
| `video_name_mapping.yaml` | 持续使用，已有不少历史数据 | 用脚本迁移到 `media_mapping.yaml` |
| `tmdb_id_mapping.conf` | 未使用能力，无历史数据 | 完全废弃，不迁移，不兼容 |

文件管理页目前只提供“名称映射”按钮，维护的是 `video_name_mapping.yaml`。当用户遇到类似：

```text
Climax.S01E01.1080p.friDay.WEB-DL.AAC2.0.H.264-MWeb.mkv
Climax.S01E02.1080p.friDay.WEB-DL.AAC2.0.H.264-MWeb.mkv
Climax.S01E03.1080p.friDay.WEB-DL.AAC2.0.H.264-MWeb.mkv
Climax.S01E10.1080p.friDay.WEB-DL.AAC2.0.H.264-MWeb.mkv
```

`tmdb_id_mapping.conf` 虽然代码中已有读取能力，但它不是正在使用的历史能力，而且设计上以原始文件名或正则为 key，不适合作为本需求的基础。它应从运行时链路中移除。

本计划改为引入唯一运行时配置源 `media_mapping.yaml`：

- `video_name_mapping.yaml` 只作为历史数据迁移来源，通过显式脚本迁移。
- `tmdb_id_mapping.conf` 相关能力彻底废弃，不做迁移，不做兼容读取。
- 运行时识别、刮削、字幕下载等路径只读取 `media_mapping.yaml`。

## 二、现有链路梳理

### 2.1 文件管理页

入口：

- `web/main.py` 的 `/mediafile`
- 模板：`web/templates/rename/mediafile.html`

文件卡片现有按钮：

- `识别`：调用 `mediafile_name_test()`，再调用通用 `media_name_test()`，后端 action 为 `name_test`
- `名称映射`：打开名称映射弹窗，后端 action 为 `get_video_name_mappings`、`set_video_name_mapping`、`delete_video_name_mapping`
- `转移`：打开手工转移弹窗，支持手工填写 TMDB ID
- `刮削`：调用 `media_path_scrap`
- `下载字幕`：调用 `download_subtitle`

### 2.2 名称识别与名称映射

`name_test` 调用：

```python
Media().get_media_info(title=name, subtitle=subtitle)
```

`Media().get_media_info()` 内部先创建：

```python
meta_info = MetaInfo(title, subtitle=subtitle)
```

`MetaInfo` 的视频名称清洗逻辑在 `app/media/meta/metavideo.py`：

```python
name = Config().get_video_name_mapping(name)
```

因此当前名称映射发生在“解析文件名得到作品名”之后，“搜索 TMDB”之前。

### 2.3 未使用的 TMDB ID 映射

当前 `tmdb_id_mapping.conf` 代码中存在读取逻辑：

```text
name:type:tmdbid
r:regex:type:tmdbid
```

但它的 key 是原始 `title` 或文件 basename：

- `Media().get_media_info()` 中使用 `Config().get_tmdb_id_mapping(title)`
- `Media().get_media_info_on_files()` 中使用 `Config().get_tmdb_id_mapping(file_name)`

这套能力没有历史数据，也不是当前文件管理页持续使用的配置能力。本计划不基于它扩展，不提供迁移，不保留兼容读取。

### 2.4 刮削链路

文件管理页刮削 action：

```python
ThreadHelper().start_thread(Scraper().folder_scraper, (path, None, 'force_all'))
```

`Scraper().folder_scraper()` 对每个媒体文件调用：

```python
self.media.get_media_info_on_files(file_list=[file], append_to_response="all")
```

所以新 `media_mapping.yaml` 必须同时覆盖：

- `Media().get_media_info()`
- `Media().get_media_info_on_files()`

否则文件管理页“识别”和“刮削”会出现不一致。

## 三、目标设计

### 3.1 唯一配置源

新增配置文件：

```text
/config/media_mapping.yaml
```

可通过 `config.yaml` 的 `app.media_mapping_file` 覆盖。

废弃：

```text
/config/video_name_mapping.yaml
/config/tmdb_id_mapping.conf
```

运行时不再读取 `video_name_mapping.yaml` 和 `tmdb_id_mapping.conf`。

### 3.2 配置 schema

第一版 `media_mapping.yaml` 采用 key-value YAML 字典：

```yaml
climax:
  title: Climax
  type: tv
  tmdbid: 241860

the_long_season:
  title: 漫长的季节

test_movie:
  title: 测试电影
  type: movie
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `title` | string | 条件必填 | 映射后的搜索名称；当没有 `tmdbid` 时必填 |
| `type` | string | 条件必填 | `movie` 或 `tv`；当存在 `tmdbid` 时必填 |
| `tmdbid` | int/string | 否 | TMDB 媒体 ID；存在时直接查询 TMDB 详情 |

### 3.3 校验规则

核心规则：

```text
有 tmdbid -> type 必须填写
无 tmdbid -> title 必须填写
只有 title -> type 可选
type 存在时只能是 movie 或 tv
```

原因：

- TMDB 电影详情接口是 `/3/movie/{movie_id}`。
- TMDB 剧集详情接口是 `/3/tv/{series_id}`。
- TMDB 没有可靠的通用 `/media/{id}` 详情接口。

因此只靠 `tmdbid` 无法可靠判断应该调用 movie 还是 tv。配置中一旦指定 `tmdbid`，必须同时保存 `type`。

### 3.4 key 规则

`media_mapping.yaml` 的 key 沿用当前 `video_name_mapping.yaml` 的规范：

```text
清洗后名称 -> 空格转下划线 -> 小写
```

例如：

| raw name | key |
|---|---|
| `Climax` | `climax` |
| `The Long Season` | `the_long_season` |
| `漫长的季节` | `漫长的季节` |

识别时不再用完整文件名匹配作品级映射，而是使用 `MetaInfo` 解析得到的 raw name。

对于：

```text
Climax.S01E01.1080p.friDay.WEB-DL.AAC2.0.H.264-MWeb.mkv
```

解析得到：

```text
raw_name = Climax
key = climax
```

命中：

```yaml
climax:
  title: Climax
  type: tv
  tmdbid: 241860
```

同一季的 `S01E01` 到 `S01E10` 都自然生效，不需要正则。

### 3.5 运行时优先级

统一后的运行时优先级：

```text
1. 手工输入 tmdbid
2. media_mapping.yaml 按 raw_name key 命中，且存在 tmdbid
3. media_mapping.yaml 按 raw_name key 命中，仅存在 title/type
4. 普通 MetaInfo 解析和 TMDB 搜索
```

详细行为：

| 命中内容 | 行为 |
|---|---|
| `tmdbid + type` | 直接调用 `Media().get_tmdb_info(mtype=type, tmdbid=tmdbid)` |
| `title + type` | 使用 `title` 替换识别名称，并按指定 `type` 搜索 |
| `title` | 使用 `title` 替换识别名称，类型沿用 `MetaInfo` 解析结果 |
| 未命中 | 沿用现有普通识别 |

如果同时存在 `title`、`type`、`tmdbid`：

- `tmdbid + type` 用于运行时识别。
- `title` 只用于 UI 展示、人工辨识和未来回退场景。

### 3.6 与旧配置的关系

`video_name_mapping.yaml`：

- 有历史数据。
- 需要通过脚本迁移到 `media_mapping.yaml`。
- 迁移后运行时不再读取。

迁移规则：

```yaml
# video_name_mapping.yaml
the_long_season: 漫长的季节
```

迁移为：

```yaml
# media_mapping.yaml
the_long_season:
  title: 漫长的季节
```

`tmdb_id_mapping.conf`：

- 无历史数据。
- 不迁移。
- 不提供兼容读取。
- 相关运行时能力、配置项、内存字段和调用点彻底删除。

## 四、文件管理页 UI 设计

### 4.1 按钮命名

将文件卡片中的“名称映射”改为：

```text
映射
```

或更明确：

```text
媒体映射
```

推荐使用“媒体映射”，因为弹窗不再只配置名称。

### 4.2 弹窗结构

弹窗标题：

```text
媒体映射配置
```

字段：

| 字段 | 控件 | 说明 |
|---|---|---|
| 文件名称 | readonly input | 当前文件名 |
| 原始名称 | readonly input | `name_test` 返回的 `raw_name` |
| 映射名称 | text input | 保存为 `title`；当 TMDB ID 为空时必填 |
| 媒体类型 | select | 空 / 电影 / 电视剧；当 TMDB ID 不为空时必填 |
| TMDB ID | text input | 可为空；填写时必须是数字，且媒体类型必填 |

建议布局：

```text
┌──────────────────────────────────────────────┐
│  媒体映射配置                            [×]  │
├──────────────────────────────────────────────┤
│  文件名称   Climax.S01E01.1080p.mkv    只读   │
│  原始名称   Climax                    只读   │
│                                              │
│  映射名称   [ Climax                  ]       │
│  媒体类型   [ 自动/请选择 v ]                 │
│  TMDB ID    [ 241860                  ]       │
│                                              │
├──────────────────────────────────────────────┤
│  [取消]      [删除映射]      [保存映射]       │
└──────────────────────────────────────────────┘
```

### 4.3 UI 校验规则

保存前前端校验：

```javascript
const title = $("#media_mapping_title").val().trim();
const type = $("#media_mapping_type").val();
const tmdbid = $("#media_mapping_tmdbid").val().trim();

if (tmdbid && !/^\d+$/.test(tmdbid)) {
  // TMDB ID 必须是数字
}

if (tmdbid && !type) {
  // 填写 TMDB ID 时必须选择媒体类型
}

if (!tmdbid && !title) {
  // 不填写 TMDB ID 时必须填写映射名称
}
```

后端必须重复同样校验，不能只依赖前端。

### 4.4 类型默认值

弹窗打开时：

1. 调用 `name_test` 获取识别结果。
2. 如果识别结果有 `type`，默认选中该类型。
3. 如果已有 mapping，以 mapping 中的 `type` 覆盖识别结果。
4. 如果没有识别结果且用户填写 TMDB ID，必须手动选择类型。

类型选项：

```text
空：自动
movie：电影
tv：电视剧
```

保存规则：

- `type` 为空且 `tmdbid` 为空：允许保存，只保存 `title`。
- `type` 为空且 `tmdbid` 非空：禁止保存。
- `type` 非空且 `tmdbid` 为空：允许保存，后续搜索固定媒体类型。

### 4.5 删除逻辑

删除映射时使用原始名称 `raw_name` 作为 key 删除。

删除成功后：

- 自动重新识别当前文件。
- chips 展示恢复为普通识别结果。

## 五、后端设计

### 5.1 Config 新接口

新增内部字段：

```python
_media_mapping = {}
_media_mapping_mtime = 0
```

新增方法：

| 方法 | 职责 |
|---|---|
| `init_media_mapping(self)` | 从 `media_mapping.yaml` 加载 `_media_mapping` 并记录 mtime |
| `check_and_reload_media_mapping(self)` | 文件不存在时清空内存映射，mtime 变化时重新加载 |
| `get_media_mapping_file(self)` | 返回 `app.media_mapping_file` 或默认 `/config/media_mapping.yaml` |
| `get_media_mapping(self, name)` | 按规范化 key 返回单条 mapping |
| `list_media_mapping(self, name=None)` | 返回全部 mapping 或指定 name 的 mapping |
| `set_media_mapping(self, key, value)` | 校验并保存单条 mapping |
| `delete_media_mapping(self, key)` | 删除单条 mapping |

key 规范化应提取为共享方法：

```python
def normalize_media_mapping_key(self, name):
    if not name:
        return name
    return name.replace(' ', '_').lower()
```

### 5.2 映射对象规范化

`Config().get_media_mapping(name)` 返回规范化后的 dict 或 `None`：

```python
{
    "title": "Climax",
    "type": "tv",
    "tmdbid": "241860"
}
```

迁移后的最小结构：

```python
{
    "title": "漫长的季节"
}
```

保存前必须清理空值，避免落盘冗余：

```yaml
the_long_season:
  title: 漫长的季节
```

而不是：

```yaml
the_long_season:
  title: 漫长的季节
  type:
  tmdbid:
```

### 5.3 迁移脚本

新增显式迁移脚本：

```text
scripts/migrate_video_name_mapping.py
```

脚本职责：

1. 读取 `video_name_mapping.yaml`。
2. 将每个 `key: value` 转成 `key: {title: value}`。
3. 写入 `media_mapping.yaml`。
4. 默认不删除 `video_name_mapping.yaml`。
5. 如果目标 `media_mapping.yaml` 已存在，默认失败并提示用户使用覆盖参数。

脚本参数：

```text
--source /config/video_name_mapping.yaml
--target /config/media_mapping.yaml
--overwrite
--dry-run
```

默认行为：

- `--source` 默认读取 `Config().get_video_name_mapping_file()`。
- `--target` 默认读取 `Config().get_media_mapping_file()`。
- 不传 `--overwrite` 时，目标文件存在则退出，避免覆盖新配置。
- 传 `--dry-run` 时只打印将生成的 YAML，不写文件。

运行时不在 `Config.__init__()` 中自动迁移。迁移是升级步骤，不是应用启动副作用。

### 5.4 删除 tmdb_id_mapping.conf 能力

删除：

```python
init_tmdb_id_mapping()
check_and_reload_tmdb_id_mapping()
get_tmdb_id_mapping()
get_tmdb_id_mapping_file()
```

以及：

```python
_tmdb_id_mapping
_r_tmdb_id_mapping
_tmdb_id_mapping_mtime
```

同时删除 `Media().get_media_info()` 和 `Media().get_media_info_on_files()` 中对 `Config().get_tmdb_id_mapping(title_or_file_name)` 的调用。

不保留兼容方法，不保留配置项，不读取 `/config/tmdb_id_mapping.conf`。

### 5.5 Media 识别链路

`Media().get_media_info()` 的目标流程：

```text
MetaInfo(title, subtitle)
  -> 得到 raw_name / get_name()
  -> Config().get_media_mapping(raw_name)
      -> 有 tmdbid + type：直接 get_tmdb_info()
      -> 有 title/type：覆盖 meta_info 名称/类型后搜索
      -> 有 title：覆盖 meta_info 名称后搜索
      -> 无 mapping：普通搜索
```

`Media().get_media_info_on_files()` 的目标流程相同，但 key 必须来自解析后的 `meta_info.raw_name` 或 `meta_info.get_name()`，不能再使用完整 file basename。

为了避免名称覆盖逻辑散落，建议在 `app/media/media.py` 中新增私有辅助方法：

```python
def __apply_media_mapping(self, meta_info):
    mapping = Config().get_media_mapping(meta_info.raw_name or meta_info.get_name())
    if not mapping:
        return None, None
    media_type = mapping.get("type")
    tmdbid = mapping.get("tmdbid")
    if tmdbid:
        mapped_tmdb_info = self.get_tmdb_info(mtype=media_type, tmdbid=tmdbid)
        return mapping, mapped_tmdb_info
    return mapping, None
```

其中：

- `mapping` 用于 title/type 覆盖。
- `mapped_tmdb_info` 用于 `tmdbid + type` 直接命中的场景。

## 六、Action 接口设计

废弃：

```text
get_video_name_mappings
set_video_name_mapping
delete_video_name_mapping
```

新增：

```text
get_media_mappings
set_media_mapping
delete_media_mapping
```

### 6.1 get_media_mappings

请求：

```json
{
  "name": "Climax"
}
```

响应：

```json
{
  "code": 0,
  "data": {
    "climax": {
      "title": "Climax",
      "type": "tv",
      "tmdbid": "241860"
    }
  }
}
```

### 6.2 set_media_mapping

请求：

```json
{
  "key": "Climax",
  "title": "Climax",
  "type": "tv",
  "tmdbid": "241860"
}
```

后端校验：

```text
key 必填
tmdbid 存在时必须是数字
tmdbid 存在时 type 必填
tmdbid 不存在时 title 必填
type 存在时必须是 movie 或 tv
```

响应：

```json
{
  "code": 0,
  "msg": "保存成功"
}
```

### 6.3 delete_media_mapping

请求：

```json
{
  "key": "Climax"
}
```

响应：

```json
{
  "code": 0,
  "msg": "删除成功"
}
```

## 七、测试计划

### 7.1 Config 单元测试

覆盖：

- `get_media_mapping("The Long Season")` 命中 `the_long_season`
- 保存 `title` only 成功
- 保存 `title + type` 成功
- 保存 `tmdbid + type` 成功
- 保存 `tmdbid` without `type` 失败
- 保存空 `title` 且空 `tmdbid` 失败
- 删除 mapping 后不再命中

### 7.2 迁移脚本测试

覆盖：

- `video_name_mapping.yaml` 转换为 `media_mapping.yaml`
- `the_long_season: 漫长的季节` 转换为 `the_long_season: {title: 漫长的季节}`
- 目标 `media_mapping.yaml` 已存在时默认失败
- 目标 `media_mapping.yaml` 已存在且传 `--overwrite` 时覆盖
- 传 `--dry-run` 时输出 YAML 但不写文件
- 空 source 文件生成空 mapping 或清晰提示
- source 文件不存在时返回非零退出码和错误信息

### 7.3 Media 识别测试

覆盖：

- `Climax.S01E01.1080p.friDay.WEB-DL.AAC2.0.H.264-MWeb.mkv` 解析出 raw name 后命中 `climax`
- `tmdbid + type` 命中时不走名称搜索，直接调用 `get_tmdb_info`
- `title` only 命中时使用映射 title 搜索
- `title + type` 命中时使用映射 title 和指定 type 搜索
- 未命中时保持旧识别行为

### 7.4 Web Action 测试

覆盖：

- `get_media_mappings`
- `set_media_mapping`
- `delete_media_mapping`
- 后端校验错误消息

### 7.5 文件管理页手工验证

验证流程：

1. 打开文件管理页。
2. 对 `Climax.S01E01.1080p.friDay.WEB-DL.AAC2.0.H.264-MWeb.mkv` 点击“媒体映射”。
3. 弹窗显示原始名称 `Climax`。
4. 填写 TMDB ID `241860`，不选类型，保存失败。
5. 选择电视剧，保存成功。
6. 自动重新识别当前文件，chips 显示 TMDB ID `241860`。
7. 对 `Climax.S01E02.1080p.friDay.WEB-DL.AAC2.0.H.264-MWeb.mkv` 点击识别，应同样命中 `241860`。
8. 点击刮削，应使用同一 TMDB ID 生成 NFO 和图片。

## 八、实施计划

### Task 1: 新增 media_mapping 配置层

**Files:**

- Modify: `config.py`
- Test: `tests/test_media_mapping.py`

- [ ] 新增 `_media_mapping`、`_media_mapping_mtime`
- [ ] 新增 `get_media_mapping_file()`
- [ ] 新增 `normalize_media_mapping_key()`
- [ ] 新增 `init_media_mapping()`
- [ ] 新增 `check_and_reload_media_mapping()`
- [ ] 新增 `get_media_mapping()`
- [ ] 新增 `list_media_mapping()`
- [ ] 新增 `set_media_mapping()`
- [ ] 新增 `delete_media_mapping()`
- [ ] 新增保存时的原子写入逻辑
- [ ] 编写 Config 测试并通过

### Task 2: 编写 video_name_mapping 迁移脚本

**Files:**

- Create: `scripts/migrate_video_name_mapping.py`
- Test: `tests/test_media_mapping_migration.py`

- [ ] 新增脚本入口 `scripts/migrate_video_name_mapping.py`
- [ ] 支持 `--source`
- [ ] 支持 `--target`
- [ ] 支持 `--overwrite`
- [ ] 支持 `--dry-run`
- [ ] 读取 YAML dict 并转换为 `{title: value}`
- [ ] 目标文件存在且未传 `--overwrite` 时返回非零退出码
- [ ] 写入时使用临时文件加 `os.replace()` 原子替换
- [ ] 编写迁移脚本测试并通过

### Task 3: 删除 tmdb_id_mapping 运行时链路

**Files:**

- Modify: `config.py`
- Modify: `app/media/media.py`
- Test: `tests/test_media_mapping.py`

- [ ] 从 `Config.__init__()` 移除 `init_tmdb_id_mapping()`
- [ ] 从 `config.py` 删除 `_tmdb_id_mapping`、`_r_tmdb_id_mapping`、`_tmdb_id_mapping_mtime`
- [ ] 从 `config.py` 删除 `init_tmdb_id_mapping()`
- [ ] 从 `config.py` 删除 `check_and_reload_tmdb_id_mapping()`
- [ ] 从 `config.py` 删除 `get_tmdb_id_mapping()`
- [ ] 从 `config.py` 删除 `get_tmdb_id_mapping_file()`
- [ ] 从识别链路移除 `Config().get_tmdb_id_mapping(title)`
- [ ] 从文件识别链路移除 `Config().get_tmdb_id_mapping(file_name)`
- [ ] 全仓确认没有 `get_tmdb_id_mapping` 调用点
- [ ] 确认运行时不再读取 `tmdb_id_mapping.conf`

### Task 4: 接入 media_mapping 到 Media 识别

**Files:**

- Modify: `app/media/media.py`
- Modify: `app/media/meta/metavideo.py` if needed
- Test: `tests/test_media_mapping.py`

- [ ] 在 `get_media_info()` 中用解析后的 raw name 查询 `media_mapping`
- [ ] 在 `get_media_info_on_files()` 中用解析后的 raw name 查询 `media_mapping`
- [ ] `tmdbid + type` 命中时直接调用 `get_tmdb_info`
- [ ] `title` 命中时覆盖搜索名称
- [ ] `type` 命中时覆盖或补充媒体类型
- [ ] 保持未命中时旧行为不变

### Task 5: 替换 Web Action

**Files:**

- Modify: `web/action.py`
- Test: existing action-level script or new tests

- [ ] 注册 `get_media_mappings`
- [ ] 注册 `set_media_mapping`
- [ ] 注册 `delete_media_mapping`
- [ ] 实现后端校验：`tmdbid -> type required`
- [ ] 实现后端校验：`no tmdbid -> title required`
- [ ] 移除旧 `get_video_name_mappings`
- [ ] 移除旧 `set_video_name_mapping`
- [ ] 移除旧 `delete_video_name_mapping`
- [ ] 同步前端调用为新 action

### Task 6: 改造文件管理页媒体映射 UI

**Files:**

- Modify: `web/templates/rename/mediafile.html`

- [ ] 将“名称映射”按钮改为“媒体映射”
- [ ] 将 modal 标题改为“媒体映射配置”
- [ ] 增加 `映射名称` 输入框，对应 `title`
- [ ] 增加 `媒体类型` select，对应 `type`
- [ ] 增加 `TMDB ID` 输入框，对应 `tmdbid`
- [ ] 打开弹窗时调用 `name_test` 获取 `raw_name` 和识别出的 `type`
- [ ] 调用 `get_media_mappings` 回填已有配置
- [ ] 保存时执行前端校验
- [ ] 保存成功后自动重新识别当前文件
- [ ] 删除成功后自动重新识别当前文件

### Task 7: 文档与验证

**Files:**

- Modify: project README or config docs if present
- Test: manual verification

- [ ] 记录 `media_mapping.yaml` 示例
- [ ] 说明 `video_name_mapping.yaml` 通过脚本迁移但不再运行时读取
- [ ] 说明 `tmdb_id_mapping.conf` 已废弃、不迁移、不兼容
- [ ] 记录迁移脚本用法和 `--dry-run` 示例
- [ ] 跑单元测试
- [ ] 手工验证文件管理页识别和刮削

## 九、风险与决策

### 9.1 `type` 是否必填

决策：

```text
tmdbid 存在时 type 必填
只有 title 时 type 可选
```

这是因为 TMDB 的 movie 和 tv 详情接口不同，只靠 ID 不能可靠调用详情接口。

### 9.2 是否保留 tmdb_id_mapping.conf

决策：

```text
不保留，不迁移，不兼容，运行时彻底删除。
```

原因：

- 这是未使用能力，没有历史数据。
- 它的 key 是原始文件名/正则，不符合作品级映射心智。
- 保留会形成三套配置并存。

### 9.3 是否继续读取 video_name_mapping.yaml

决策：

```text
用显式脚本迁移，不运行时读取。
```

原因：

- 它有历史数据，必须保护用户已有配置。
- 迁移是升级动作，应由脚本显式执行，避免应用启动时产生文件写入副作用。
- 迁移后若继续读取，会造成优先级混乱。

### 9.4 是否把 media_mapping 写回 video_name_mapping.yaml

决策：

```text
不写回。
```

原因：

- `media_mapping.yaml` 是新唯一源。
- 双写会引入一致性问题。

## 十、完成标准

- `media_mapping.yaml` 成为唯一运行时映射配置。
- 历史 `video_name_mapping.yaml` 可通过脚本迁移。
- `tmdb_id_mapping.conf` 相关代码被删除，不再参与识别。
- 文件管理页“媒体映射”可同时配置 `title`、`type`、`tmdbid`。
- UI 和后端都强制执行：有 `tmdbid` 时 `type` 必填。
- `Climax.S01E01` 到 `S01E10` 只需配置一次 `climax` 即可全部命中同一个 TMDB ID。
