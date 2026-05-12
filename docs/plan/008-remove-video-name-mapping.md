# 008 — 下线 video_name_mapping.yaml

> 目标：`media_mapping.yaml` 已完全替代 `video_name_mapping.yaml`，清理 git 仓库中所有残留代码和配置，使项目不再对 `video_name_mapping` 有任何运行时依赖或认知负担。

## 1. 背景

006 计划已完成 `media_mapping.yaml` 统一替代：
- `app/` 目录中 **零引用** `video_name_mapping`，运行时已完全走 `__apply_media_mapping` → `Config().get_media_mapping()` 路径
- 迁移脚本 `scripts/migrate_video_name_mapping.py` 已提供，用户可将旧数据一次性迁移

以下 git 跟踪文件仍残留 `video_name_mapping` 引用，需清理：

| 残留项 | 位置 | 类型 |
|---|---|---|
| `video_name_mapping_file` 配置项 | `config/config.yaml:60-61` | 孤立配置 |
| 迁移脚本 | `scripts/migrate_video_name_mapping.py` | 一次性工具 |
| 迁移脚本测试 | `tests/test_media_mapping_migration.py` | 测试 |
| 旧调试脚本 | `tests/test_mapping.py` | 开发期临时脚本 |
| 旧编码调试脚本 | `tests/test_encoding.py` | 开发期临时脚本 |

**不在清理范围**：
- `docs/plan/002-video-name-mapping-ui.md`、`docs/plan/006-media-mapping-unification.md` — 历史决策记录，保留
- 根目录 `video_name_mapping.yaml` — 未跟踪文件（`??`），非 git 管辖

## 2. 影响分析

### 2.1 运行时影响

**无运行时影响**。`app/` 代码已完全不含 `video_name_mapping` 的引用：
- `config/config.yaml` 中的 `video_name_mapping_file` 键：`Config()` 不再读取此键，属于孤立配置
- 删除后 YAML 加载器忽略未知键，不会报错

### 2.2 用户迁移影响

部分用户可能仍持有 `/config/video_name_mapping.yaml`（Docker 挂载卷中），尚未迁移。清理策略：
- 迁移脚本 **保留一个版本周期**，移至 `scripts/deprecated/` 并标注废弃
- Release Notes 中告知用户：下一版本将移除迁移脚本

## 3. 清理范围

### Task 1: 删除 `config/config.yaml` 中的废弃配置项

**文件**: `config/config.yaml`

**操作**: 删除第 60-61 行：

```yaml
  # 视频名称mapping的路径
  video_name_mapping_file: /config/video_name_mapping.yaml
```

保留紧邻的 `media_mapping_file` 配置不变。

### Task 2: 迁移脚本移至 deprecated

**文件**: `scripts/migrate_video_name_mapping.py`

**操作**:
1. `mkdir -p scripts/deprecated`
2. `git mv scripts/migrate_video_name_mapping.py scripts/deprecated/`
3. 在文件头部 docstring 中增加废弃警告：
   ```
   DEPRECATED: This script will be removed in a future release.
   video_name_mapping.yaml is no longer used at runtime. Use media_mapping.yaml instead.
   ```

> **理由**：保留一个版本过渡期，避免已部署用户升级后找不到迁移工具。下一版本可彻底删除 `scripts/deprecated/`。

### Task 3: 删除迁移脚本测试

**文件**: `tests/test_media_mapping_migration.py`

**操作**: 删除。迁移脚本是一次性工具，非核心功能，不值得保留测试。脚本本身逻辑极简（YAML key:value → key:{title:value}），无需长期维护。

### Task 4: 删除旧调试脚本

**文件**:
- `tests/test_mapping.py` — 手动 `os.system("cp ...")`，依赖宿主机路径，非 CI 测试
- `tests/test_encoding.py` — 测试 `video_name_mapping-2.yaml` 编码转换，开发期临时脚本

**操作**: 删除。两者均非自动化测试，是开发者临时调试脚本，且依赖不存在的外部文件。

## 4. 不做的事

| 不做 | 原因 |
|---|---|
| 彻底删除 `scripts/migrate_video_name_mapping.py` | 保留一个版本周期，给用户迁移时间 |
| 修改 `app/` 代码 | 已无引用，无需修改 |
| 修改前端代码 | 已无引用，无需修改 |
| 删除 `docs/plan/002-video-name-mapping-ui.md` | 历史决策记录，保留 |
| 处理根目录 `video_name_mapping.yaml` | 未跟踪文件，非 git 管辖 |

## 5. 执行顺序

```
1. 删除 config/config.yaml 中的 video_name_mapping_file 配置项
2. mkdir -p scripts/deprecated && git mv scripts/migrate_video_name_mapping.py scripts/deprecated/
3. 在脚本头部添加 DEPRECATED 警告
4. git rm tests/test_media_mapping_migration.py
5. git rm tests/test_mapping.py
6. git rm tests/test_encoding.py
```

## 6. 验证

1. `git ls-files | xargs grep "video_name_mapping" | grep -v docs/plan/ | grep -v scripts/deprecated/` → 零结果
2. `grep "video_name_mapping" config/config.yaml` → 零结果
3. `scripts/deprecated/migrate_video_name_mapping.py` 存在且带 DEPRECATED 标记
4. 项目可正常启动，`media_mapping` 功能不受影响
5. 现有测试通过（`pytest tests/`）
