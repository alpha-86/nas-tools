# NAS媒体库管理工具

基于 [NAStool/nas-tools](https://github.com/NAStool/nas-tools) 的个人维护分支，包含上游问题修复和功能改进。

## 与上游的差异

- **TMDB 跨语言识别修复**：搜索别名时附加 `alternative_titles,translations`，解决非英语标题（如"Perfect Crown"→"21世纪大君夫人"）在中文 locale 下无法匹配的问题
- **统一媒体映射**：`media_mapping.yaml` 替代旧的 `video_name_mapping.yaml`，支持 title/tmdbid/type 三种映射方式
- **Docker 自动更新**：默认开启 `NASTOOL_AUTO_UPDATE=true`，容器启动时自动从 GitHub 拉取最新代码
- **Python 3.12**：运行环境升级到 Python 3.12 + Alpine

## 安装

### Docker（推荐）

```bash
docker pull alpha8686/nas-tools:latest
```

```bash
docker run -d \
  --name nastools \
  -v /path/to/config:/config \
  -v /path/to/media:/media \
  -p 3000:3000 \
  --restart always \
  alpha8686/nas-tools:latest
```

首次启动时，程序会自动将默认配置模板复制到 `/config/config.yaml`，通过 `http://<IP>:3000` 访问 Web 界面进行配置。

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NASTOOL_AUTO_UPDATE` | `true` | 启动时自动 git pull 更新代码 |
| `NASTOOL_VERSION` | `main` | 更新目标分支 |
| `NASTOOL_CN_UPDATE` | `true` | 使用国内镜像源更新 pip/apk |
| `PUID` / `PGID` | `0` / `0` | 运行用户 UID/GID |
| `UMASK` | `000` | 文件权限掩码 |
| `TZ` | `Asia/Shanghai` | 时区 |

## 配置

- `/config/config.yaml` — 主配置文件（Web 界面可管理全部配置项）
- `/config/media_mapping.yaml` — 媒体名称映射（替代旧的 `video_name_mapping.yaml`）

### media_mapping.yaml 示例

```yaml
the_long_season:
  title: 漫长的季节
perfect_crown:
  title: Perfect Crown
  type: tv
  tmdbid: 278573
```

## 免责声明

1) 本软件仅供学习交流使用，对用户的行为及内容毫不知情，使用本软件产生的任何责任需由使用者本人承担。
2) 本软件代码开源，基于开源代码进行修改，人为去除相关限制导致软件被分发、传播并造成责任事件的，需由代码修改发布者承担全部责任，不建议对用户认证机制进行规避或修改并公开发布。
3) 本项目没有在任何地方发布捐赠信息页面，也不会接受捐赠或收费，请仔细辨别避免误导。
