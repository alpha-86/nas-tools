# NAS 媒体库自动化管理工具

这是一个面向个人 NAS / 家庭影音服务器的媒体库自动化系统。它把 PT 站点检索、RSS 订阅、下载器管理、文件整理、媒体识别、元数据刮削、媒体服务器联动和消息通知串在一起，目标是减少从“发现资源”到“媒体库可播放”之间的手工操作。

## 项目说明

`NAStool/nas-tools` 已归档并停止维护，且上游曾删除或下线代码，不再作为可持续维护的主线使用。本项目是个人维护的一份 nas-tools 代码，用于自用部署、兼容性修复、安全整改和功能增强。

## 本分支主要迭代

- Docker 运行环境升级：使用 Alpine latest、Python 3.12、虚拟环境安装依赖，并升级 ffmpeg / VAAPI 相关运行时组件。
- 依赖安全修复：升级 Flask、Werkzeug、Pillow、cryptography、lxml、urllib3、Mako、PyJWT 等存在安全告警的 Python 依赖。
- 安全整改：移除失效的 `nastool.org` 远程调用，收敛自动更新执行面，替换危险 `eval()`、pickle 缓存和不安全 YAML 加载，恢复默认 TLS 证书校验，加强 API Key、Webhook、弱口令和 Session Cookie 处理。
- 用户与站点配置兼容：补齐纯 Python 用户/站点配置模块，减少对特定 Python 版本 `.so` 文件的依赖，适配 Python 3.10 / 3.12 运行环境。
- Kodi MySQL 媒体服务器支持：新增只读 Kodi MySQL 视频库接入，支持媒体存在性检查、媒体库同步、首页继续观看/最新入库/活动数据、海报缓存和内置媒体库浏览。
- 媒体识别映射统一：使用 `media_mapping.yaml` 统一替代旧的 `video_name_mapping.yaml`，支持按名称、类型和 TMDB ID 更稳定地修正识别结果。
- FFmpeg 缩略图增强：重构缩略图命令构建，修复 Intel GPU 路径问题，增加 HDR / Dolby Vision tone-mapping，支持 GPU 失败后降级到 CPU。
- 豆瓣与图片缓存优化：修复豆瓣排序默认值，代理豆瓣海报图片并增加磁盘缓存、CDN 轮询和失败重试，减少反盗链和外部 CDN 波动影响。
- Web 体验与稳定性修复：优化实时日志连接序号跟踪，修复首页媒体库跳转、空链接、Kodi 同步并发、海报同步线程隔离等问题。

## 它能做什么

- 聚合搜索 PT 站点资源，并按规则择优下载。
- 管理电影、电视剧、动漫订阅，支持 RSS 定时检查和定量搜索。
- 对接 qBittorrent、Transmission，跟踪下载中和已完成任务。
- 下载完成后自动识别媒体信息，按命名规则整理到媒体库。
- 支持硬链接、软链接、复制、移动、rclone、MinIO 等转移方式。
- 按电影、电视剧、动漫及自定义二级分类组织媒体目录。
- 生成 NFO、海报等刮削数据，辅助媒体服务器识别。
- 对接 Emby、Jellyfin、Plex、Kodi MySQL 视频库，支持媒体库同步、Webhook 和播放数据。
- 管理站点 Cookie、站点统计、刷流任务、下载历史和未识别文件。
- 支持微信、Telegram、Slack、Synology Chat、Bark、PushPlus、Gotify、IYUU、ntfy 等消息通知或交互入口。
- 提供 Web 管理界面和 `/api/v1` 接口，适合部署在 NAS、家用服务器或 Docker 环境。

## 典型使用流程

1. 在 Web 界面配置 TMDB API Key、代理、下载器、媒体库目录和媒体服务器。
2. 添加 PT 站点和站点 Cookie，测试站点连通性。
3. 通过搜索、订阅或 RSS 规则选择要下载的资源。
4. 下载器完成任务后，系统按规则识别、重命名并转移到媒体库。
5. 媒体服务器收到 Webhook 或定时同步后刷新资料库。
6. 通过 Web、消息机器人或通知渠道查看状态、触发搜索、订阅或下载。

## 快速开始

### Docker 部署

```bash
docker pull alpha8686/nas-tools:latest
```

```bash
docker run -d \
  --name nastools \
  -p 3000:3000 \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/media:/media \
  --restart always \
  alpha8686/nas-tools:latest
```

启动后访问：

```text
http://<NAS_IP>:3000
```

默认登录用户为 `admin`。如果 `config.yaml` 中未配置 `app.login_password`，首次启动会自动生成随机密码并输出到日志。

查看日志：

```bash
docker logs -f nastools
```

### 本地运行

本地运行需要 Python 3 环境，并依赖 `requirements.txt` 中的包。

```bash
pip install -r requirements.txt
export NASTOOL_CONFIG=/absolute/path/to/config.yaml
python run.py
```

也可以指定 Web 端口：

```bash
python run.py --port 3001
```

首次运行时，如果 `NASTOOL_CONFIG` 指向的配置文件不存在，程序会从内置模板复制一份 `config.yaml`。

## 关键配置

主要配置文件是 `/config/config.yaml`。多数配置也可以在 Web 界面中维护，推荐优先使用 Web 页面配置。

部署前建议至少确认这些配置：

- `app.web_port`：Web 管理界面端口，默认 `3000`。
- `app.login_user` / `app.login_password`：管理界面账号密码。
- `app.rmt_tmdbkey`：TMDB API Key，媒体识别和重命名依赖它。
- `app.proxies`：访问 TMDB、fanart、Telegram 等外部服务时使用的代理。
- `media.movie_path` / `media.tv_path` / `media.anime_path`：媒体库目标目录。
- `media.default_rmt_mode`：默认转移方式，如 `link`、`copy`、`softlink`、`move`、`rclone`。
- `media.media_server`：媒体服务器类型，可选 Emby、Jellyfin、Plex。
- `pt.pt_check_interval`：RSS 订阅检查间隔。
- `security.api_key` / `security.check_apikey`：Webhook 和外部 API 的认证开关。

硬链接模式要求下载目录和媒体库目录在同一文件系统内。Docker 部署时应映射它们的共同上级目录，否则容器内可能被识别为跨盘，导致硬链接失败。

## 支持的集成

下载器：

- qBittorrent
- Transmission

媒体服务器：

- Emby
- Jellyfin
- Plex
- Kodi MySQL 视频库

通知与交互：

- 企业微信 / WeChat
- Telegram
- Slack
- Synology Chat
- ServerChan
- Bark
- PushPlus
- PushDeer
- Gotify
- IYUU
- ntfy

文件转移：

- 硬链接 `link`
- 软链接 `softlink`
- 复制 `copy`
- 移动 `move`
- rclone 移动 / 复制
- MinIO 移动 / 复制

## 目录结构

```text
app/                核心业务逻辑：搜索、订阅、下载、媒体识别、转移、通知、插件等
web/                Flask Web 界面、API、Webhook 和页面模板
config/             配置模板、默认分类策略
docker/             Docker 镜像和 s6 服务启动脚本
scripts/            数据库迁移、部署和维护脚本
tests/              单元测试和回归测试
package/            桌面打包相关文件
```

## 开发与测试

安装依赖后可以运行测试：

```bash
pytest tests/
```

项目包含下载器、媒体服务器、站点和 Webhook 等外部依赖，部分能力需要真实服务或测试配置才能完整验证。

## 安全建议

- 不要把 Web 管理界面直接暴露到公网，建议放在 VPN、反向代理认证或内网环境后面。
- 首次启动后立即设置强密码。
- 对 Webhook、Telegram、Synology Chat、Slack 等入口启用 IP 白名单或 API Key 校验。
- 不要公开包含站点 Cookie、下载器密码、媒体服务器 API Key、Telegram Token 的配置文件或日志。
- `move` 模式会移动原文件，可能影响做种；PT 场景通常优先考虑硬链接。

## 免责声明

1. 本软件仅供学习交流使用，对用户的行为及内容毫不知情，使用本软件产生的任何责任需由使用者本人承担。
2. 本软件代码开源，基于开源代码进行修改，人为去除相关限制导致软件被分发、传播并造成责任事件的，需由代码修改发布者承担全部责任，不建议对用户认证机制进行规避或修改并公开发布。
3. 本项目没有在任何地方发布捐赠信息页面，也不会接受捐赠或收费，请仔细辨别避免误导。
