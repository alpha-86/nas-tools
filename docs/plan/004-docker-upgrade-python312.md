# Plan 004: Docker 镜像升级 — Alpine 3.21 + Python 3.12 + 依赖全面更新

> 目标：将 Docker 基础镜像升级到较新稳定版，明确使用 Python 3.12，系统包和 pip 依赖尽可能升级到最新版。同时与 Plan 003（alpine:edge + ffmpeg 8.1.1）协调，避免冲突。

---

## 一、现状分析

### 1.1 当前 Dockerfile

```dockerfile
FROM alpine:latest AS Builder
RUN apk add --no-cache --virtual .build-deps \
        libffi-dev gcc musl-dev libxml2-dev libxslt-dev \
    && apk add --no-cache $(echo $(wget .../package_list.txt)) \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && pip install ... --break-system-packages
...
FROM scratch AS APP
COPY --from=Builder / /
```

**问题**：
- `alpine:latest` 指向版本不固定，构建不可复现
- Python 版本未明确指定，依赖 alpine 仓库的默认 `python3` 包
- `requirements.txt` 中大量依赖版本锁定（`==`），很多已过时
- `--break-system-packages` 是 alpine pip 的权宜之计，镜像应使用虚拟环境

### 1.2 当前依赖版本

| 类型 | 文件 | 状态 |
|------|------|------|
| Alpine 系统包 | `package_list.txt` | 无版本号，安装 alpine 仓库中的最新版 |
| Python 包 | `requirements.txt` | 大量 `==` 固定版本，部分包有安全漏洞或已弃用 |
| 第三方库 | `third_party.txt` | git submodule 形式，版本由子模块控制 |

**requirements.txt 中关键依赖当前版本 vs 最新版**：

| 包 | 当前 | 最新(2026-05) | 升级风险 |
|---|---|---|---|
| Flask | 2.2.5 | 3.1.x | **高** — API 变更（如 `session_cookie_name` 移除） |
| Werkzeug | 2.3.8 | 3.1.x | **高** — Flask 2 不兼容 Werkzeug 3 |
| flask-restx | 1.0.6 | 1.3.x | 中 — 1.x 系列兼容性较好 |
| SQLAlchemy | 2.0.4 | 2.0.x | **低** — 同主版本，内部修复 |
| openai | 0.27.2 | 1.75.x | **极高** — API 完全重写，代码需重构 |
| cryptography | 42.0.4 | 44.x | 中 — 可能有编译问题 |
| selenium | 4.4.3 | 4.x | 中 — WebDriver 初始化 API 有变更 |
| pillow | 10.3.0 | 11.x | 低 |
| lxml | 5.3.0 | 5.3.x | 低 — 已较新 |
| requests | 2.32.2 | 2.32.x | 低 |
| Jinja2 | 3.1.4 | 3.1.x | 低 |
| beautifulsoup4 | 4.11.1 | 4.13.x | 低 |
| APScheduler | 3.10.0 | 3.11.x | 中 — 3.11 有行为调整 |

> 代码中使用 `openai.api_key = ...`（0.x 风格），升级到 1.x 需重写 `app/helper/openai_helper.py`。

### 1.3 Alpine 版本映射

| Alpine 版本 | Python 版本 | ffmpeg 版本 | 状态 |
|---|---|---|---|
| 3.19/3.20 | 3.11 | ~6.0 | 旧 |
| **3.21** (当前 latest) | **3.12.13** | **6.1.2** | **目标** |
| edge | 3.14.3 | 8.1.1 | 003 所需 |

**核心冲突**：Plan 003 要求 `alpine:edge`（ffmpeg 8.1.1 + zscale/tonemap），Plan 004 要求 Python 3.12。但 edge 的 Python 是 3.14，不是 3.12。

---

## 二、方案选项

### 方案 A：alpine 3.21 全稳定版（推荐）

- **基础镜像**：`alpine:3.21`（明确版本，不漂移）
- **Python**：从 alpine 3.21 仓库安装 `python3`（即 3.12.13）
- **ffmpeg**：使用 alpine 3.21 自带的 ffmpeg 6.1.2
- **依赖**：全部从 3.21 仓库安装，**不混用 edge**

**与 003 的协调**：Plan 003 要求 ffmpeg 8.1.1 主要是为了 zscale/tonemap/hwdownload。ffmpeg 6.1.2 已内置 tonemap/hwdownload；zscale 需要 libzimg，需验证 alpine 3.21 的 ffmpeg 包是否编译了此依赖。

**验证路径**：构建后执行 `ffmpeg -filters 2>&1 | grep zscale`，如果存在则 003 和 004 完全兼容，无需 edge。

**优势**：零 ABI 风险，镜像干净，可复现。

**风险**：如果 alpine 3.21 的 ffmpeg 缺少 zscale，003 的 HDR tone-mapping 滤镜链不可用。

### 方案 B：alpine 3.21 + edge ffmpeg（混用）

- **基础镜像**：`alpine:3.21`
- **Python**：3.12（从 3.21 仓库）
- **ffmpeg 及 VAAPI 驱动**：从 edge 仓库单独安装

```dockerfile
# 添加 edge 仓库仅用于 ffmpeg
RUN echo "https://dl-cdn.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories \
    && apk add --no-cache ffmpeg intel-media-driver libva-dev libva-utils zimg \
       --repository=https://dl-cdn.alpinelinux.org/alpine/edge/community
```

**优势**：既能用 Python 3.12，又能用 ffmpeg 8.1.1，003 功能无损。

**风险**：edge 和 3.21 的 ABI 差异可能导致运行时问题（edge 的 glibc/musl 库版本更新）。

### 方案 C：`python:3.12-alpine3.21` 官方镜像

- **基础镜像**：`python:3.12-alpine3.21`（Docker 官方，已预装 Python 3.12.9+）
- **不需要**从 alpine 安装 `python3-dev` / `py3-pip`
- ffmpeg 同方案 A 或 B

**优势**：Python 版本完全明确，不受 alpine 仓库影响；`pip` 已预装，不需要 `--break-system-packages`。

**风险**：官方镜像比 `alpine:3.21` 大 ~50MB；仍需解决 ffmpeg 版本问题。

---

## 三、推荐方案

**采用方案 A（alpine 3.21 全稳定版）为主路径，以方案 B 为 fallback。**

```
1. 先用 alpine:3.21 构建，验证 ffmpeg 6.1.2 的 zscale/tonemap/hwdownload
   ├─ 全部通过 → 用方案 A，不碰 edge
   └─ 缺少 zscale 或 tonemap → fallback 到方案 B（3.21 + edge ffmpeg）
```

**理由**：
- 003 的核心需求是"zscale/tonemap/hwdownload 可用"，不是"ffmpeg 必须是 8.1.1"
- ffmpeg 6.1.2 已支持 tonemap/hwdownload；zscale 依赖 libzimg 编译选项，大概率已包含
- 避免 edge 的滚动更新风险，构建更稳定

---

## 四、具体改动

### 4.1 Dockerfile 重构

```dockerfile
# 明确指定 alpine 版本，避免 latest 漂移
FROM alpine:3.21 AS Builder

# 构建依赖（编译 Python 包所需）
RUN apk add --no-cache --virtual .build-deps \
        libffi-dev \
        gcc \
        musl-dev \
        libxml2-dev \
        libxslt-dev \
        linux-headers

# 运行时依赖（从 package_list.txt + python3）
RUN apk add --no-cache \
        python3 \
        py3-pip \
        git tzdata zip curl bash fuse3 xvfb \
        inotify-tools chromium-chromedriver \
        s6-overlay ffmpeg redis wget shadow sudo \
        intel-media-driver libva-dev libva-utils \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && curl https://rclone.org/install.sh | bash \
    && if [ "$(uname -m)" = "x86_64" ]; then ARCH=amd64; elif [ "$(uname -m)" = "aarch64" ]; then ARCH=arm64; fi \
    && curl https://dl.min.io/client/mc/release/linux-${ARCH}/mc --create-dirs -o /usr/bin/mc \
    && chmod +x /usr/bin/mc

# 使用 Python 虚拟环境，避免 --break-system-packages
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 升级 pip 工具链，安装依赖
RUN pip install --upgrade pip wheel setuptools \
    && pip install cython \
    && pip install -r https://raw.githubusercontent.com/alpha-86/nas-tools/master/requirements.txt

# 清理
RUN apk del --purge .build-deps \
    && rm -rf /tmp/* /root/.cache /var/cache/apk/*

COPY --chmod=755 ./docker/rootfs /

FROM scratch AS APP
COPY --from=Builder / /

ENV S6_SERVICES_GRACETIME=30000 \
    S6_KILL_GRACETIME=60000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_SYNC_DISKS=1 \
    HOME="/nt" \
    TERM="xterm" \
    PATH="/opt/venv/bin:/usr/lib/chromium:$PATH" \
    LANG="C.UTF-8" \
    TZ="Asia/Shanghai" \
    NASTOOL_CONFIG="/config/config.yaml" \
    NASTOOL_AUTO_UPDATE=false \
    NASTOOL_CN_UPDATE=true \
    NASTOOL_VERSION=master \
    PS1="\u@\h:\w \$ " \
    REPO_URL="https://github.com/alpha-86/nas-tools.git" \
    PYPI_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple" \
    ALPINE_MIRROR="mirrors.ustc.edu.cn" \
    PUID=0 \
    PGID=0 \
    UMASK=000 \
    WORKDIR="/nas-tools"

COPY . /${WORKDIR}
WORKDIR ${WORKDIR}

RUN addgroup -S nt -g 911 \
    && adduser -S nt -G nt -h ${HOME} -s /bin/bash -u 911 \
    && echo "${WORKDIR}/" > /opt/venv/lib/python3.12/site-packages/nas-tools.pth \
    && echo 'fs.inotify.max_user_watches=5242880' >> /etc/sysctl.conf \
    && echo 'fs.inotify.max_user_instances=5242880' >> /etc/sysctl.conf \
    && echo "nt ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers \
    && if [ -d third_party ]; then cd third_party && git submodule init && git submodule update; fi

EXPOSE 3000
VOLUME ["/config"]
ENTRYPOINT ["/init"]
```

**关键变更**：
1. `FROM alpine:latest` → `FROM alpine:3.21`（版本固定）
2. 显式安装 `python3` 和 `py3-pip`（alpine 3.21 提供 Python 3.12.13）
3. 新增 `python3 -m venv /opt/venv` — 虚拟环境替代 `--break-system-packages`
4. 更新 `PATH` 包含 `/opt/venv/bin`
5. `.pth` 路径改为 `/opt/venv/lib/python3.12/...`

### 4.2 package_list.txt 调整

当前 `package_list.txt` 中的 `python3-dev` 和 `py3-pip` 在 Dockerfile 中改为显式安装（因为需要放在 `.build-deps` 之外）。

如果保留 `package_list.txt` 作为运行时自动更新源，需要移除 `python3-dev`（纯开发包，运行时不需要）：

```diff
# package_list.txt
git
-python3-dev
-py3-pip
+python3
+py3-pip
 tzdata
 zip
 ...
```

或者保持 `package_list.txt` 不变，在 Dockerfile 中额外显式安装 `python3 py3-pip`。

### 4.3 requirements.txt 升级策略

**策略：分阶段升级，先安全后激进。**

#### 阶段 1：安全升级（无代码改动）

只升级同主版本内的最新版（`==` → 同主版本最新 patch/minor）：

```
# 低风险：直接升级到同主版本最新
cryptography==44.0.0
pillow==11.2.0
requests==2.32.3
beautifulsoup4==4.13.3
Jinja2==3.1.6
lxml==5.3.2
SQLAlchemy==2.0.40
loguru==0.7.3
psutil==7.0.0
pymongo==4.12.0
PyMySQL==1.1.1
certifi==2025.4.26
idna==3.10
urllib3==2.4.0
```

#### 阶段 2：框架升级（需验证）

Flask/Werkzeug 2→3 是重大变更，需在隔离环境验证后再升级：

```
# 暂不升级，保持当前版本直到验证通过
Flask==2.2.5
Werkzeug==2.3.8
flask-restx==1.0.6
flask-compress==1.13
flask-sock==0.6.0
Flask-Login==0.6.2
```

> 验证方法：构建容器后跑一轮完整的 WEB 功能测试（登录、文件整理、媒体识别等）。

#### 阶段 3：高风险包（需代码改动）

| 包 | 现状 | 升级方式 |
|---|---|---|
| `openai` | 0.27.2（0.x API） | 暂不升级；如需升级需重写 `openai_helper.py` |
| `selenium` | 4.4.3 | 升级到 4.31+，验证 WebDriver 初始化逻辑 |
| `APScheduler` | 3.10.0 | 升级到 3.11+，验证定时任务调度 |

### 4.4 010-update 脚本适配

`docker/rootfs/etc/cont-init.d/010-update` 中的依赖更新逻辑需要适配虚拟环境：

```diff
  function requirements_update {
      ...
-     pip install --upgrade pip setuptools wheel
-     pip install -r requirements.txt
+     /opt/venv/bin/pip install --upgrade pip setuptools wheel
+     /opt/venv/bin/pip install -r requirements.txt
      ...
  }
```

### 4.5 NAStool 服务脚本适配

`docker/rootfs/etc/services.d/NAStool/run` 中的 `python3` 调用需要改为虚拟环境路径：

```diff
  exec \
      s6-notifyoncheck ... \
-     cd ${WORKDIR} s6-setuidgid nt python3 run.py
+     cd ${WORKDIR} s6-setuidgid nt /opt/venv/bin/python3 run.py
```

---

## 五、文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `docker/Dockerfile` | 重构 | `alpine:latest` → `alpine:3.21`；新增 Python 3.12 虚拟环境 `/opt/venv`；移除 `--break-system-packages`；更新 PATH 和 .pth 路径 |
| `package_list.txt` | 调整 | 将 `python3-dev` 改为 `python3`（运行时不需要 dev 包） |
| `requirements.txt` | 部分升级 | 阶段 1 安全升级（cryptography, pillow, requests 等同主版本最新）；阶段 2/3 保持原版本待验证 |
| `docker/rootfs/etc/services.d/NAStool/run` | 1 行 | `python3` → `/opt/venv/bin/python3` |
| `docker/rootfs/etc/cont-init.d/010-update` | 2 行 | `pip` → `/opt/venv/bin/pip` |
| `docs/plan/003-ffmpeg-thumb-hdr-gpu.md` | 协调 | 如果方案 A 验证通过（ffmpeg 6.1.2 支持 zscale），将 003 的 `alpine:edge` 改为 `alpine:3.21` |

---

## 六、验证方式

### 6.1 Docker 构建验证

```bash
# 1. 构建镜像
docker build -t nas-tools:3.21-test -f docker/Dockerfile .

# 2. 确认 Python 版本
docker run --rm nas-tools:3.21-test python3 --version
# 期望: Python 3.12.13

# 3. 确认 ffmpeg 版本及关键滤镜
docker run --rm nas-tools:3.21-test ffmpeg -version | head -1
docker run --rm nas-tools:3.21-test ffmpeg -filters 2>&1 | grep -E "zscale|tonemap|hwdownload"
# 期望: 三条都输出非空（如为空，fallback 到方案 B）

# 4. 确认虚拟环境
docker run --rm nas-tools:3.21-test which python3
# 期望: /opt/venv/bin/python3

# 5. 确认 pip 包安装成功
docker run --rm nas-tools:3.21-test pip list | grep -E "Flask|SQLAlchemy|requests"
```

### 6.2 运行时功能验证

| # | 验证项 | 方法 |
|---|---|---|
| 1 | 服务启动 | `docker run` 后查看日志，确认无 ImportError |
| 2 | WEB 登录 | 访问 `http://IP:3000`，验证登录正常 |
| 3 | 文件整理识别 | 上传/整理一个视频文件，验证识别流程 |
| 4 | 定时任务 | 验证 RSS、订阅等定时任务正常触发 |
| 5 | ffmpeg 截图 | 用 Plan 003 的测试文件验证 thumb 生成（如果 003 已完成） |
| 6 | 自动更新脚本 | 修改 requirements.txt 后重启容器，验证 010-update 正确重装依赖 |

### 6.3 依赖兼容性验证

```bash
# 在容器内运行 pip check，查找版本冲突
pip check

# 扫描已知安全漏洞
pip install pip-audit
pip-audit
```

---

## 七、003/004 协调清单

| Plan 003 需求 | 在 004 方案 A 中的满足情况 | 验证项 |
|---|---|---|
| ffmpeg >= 6.0 | alpine 3.21 自带 ffmpeg 6.1.2 | `ffmpeg -version` |
| zscale 滤镜 | 依赖 alpine 编译选项，需验证 | `ffmpeg -filters \| grep zscale` |
| tonemap 滤镜 | ffmpeg 6.1.2 内置 | `ffmpeg -filters \| grep tonemap` |
| hwdownload 滤镜 | ffmpeg 6.1.2 VAAPI 支持 | `ffmpeg -filters \| grep hwdownload` |
| vaapi 硬件加速 | `intel-media-driver` + `libva` 从 3.21 安装 | `ffmpeg -hwaccels \| grep vaapi` |

**如果上述验证全部通过**：Plan 003 的 `alpine:edge` 建议同步改为 `alpine:3.21`，两个计划完全兼容。

**如果 zscale 缺失**：Plan 004 采用方案 B（3.21 + edge ffmpeg），Plan 003 保持 edge，两个计划通过混用协调。

---

## 八、风险与注意事项

1. **Python 虚拟环境路径**：`/opt/venv` 是硬编码路径。如果未来需要支持多 Python 版本，可改为 `/opt/venv-py312`。
2. **`--break-system-packages` 移除**：使用虚拟环境后不再需要此标志。但 010-update 脚本中的 `pip install` 也需要指向虚拟环境 pip。
3. **Flask 2→3 升级**：Flask 3 移除 `session_cookie_name` 等旧属性，移除 `app.json_encoder`。当前代码未使用这些特性，但建议验证后再升级。
4. **openai 0→1 升级**：openai 1.x 是全新 API（`openai.OpenAI()` 客户端模式），`openai_helper.py` 需要完全重写。建议作为独立任务处理，不在 004 范围内升级 openai 包。
5. **alpine 3.21 的 Chromium**：`chromium-chromedriver` 包在 alpine 中可能版本较新，需验证与 `undetected-chromedriver` 的兼容性。
6. **构建缓存**：明确指定 `alpine:3.21` 后，Docker 构建缓存更稳定；但首次构建会拉取新的基础镜像层。
7. **镜像大小**：虚拟环境 `/opt/venv` 会增加 ~100-200MB 镜像大小（所有 pip 包安装在 venv 而非系统 site-packages）。可通过多阶段构建优化（将 venv 从 Builder 复制到 APP）。
