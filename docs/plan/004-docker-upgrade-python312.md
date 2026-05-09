# Plan 004: Docker 镜像升级 — Alpine latest + Python 3.12 + Edge ffmpeg 8.1.1 + 依赖全面更新

> 目标：将 Docker 基础镜像升级到 `alpine:latest`（当前指向 3.23.4），使用 Python 3.12，ffmpeg 及 VAAPI 驱动从 edge 仓库升级到 8.1.1，pip 依赖按安全策略升级。

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
- `pip install --break-system-packages` 是权宜之计，应使用虚拟环境
- `requirements.txt` 中大量依赖版本锁定（`==`），很多已过时且有安全漏洞
- ffmpeg 从默认仓库安装，版本较旧（当前 latest 的 ffmpeg 8.0.1）

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

---

## 二、方案

### 2.1 架构

```
FROM alpine:latest AS Builder
  ├── apk add python3 py3-pip  (来自 latest 仓库 → Python 3.12)
  ├── apk add ... --repository=edge/community  (ffmpeg 8.1.1 + VAAPI 驱动)
  ├── python3 -m venv /opt/venv  (替代 --break-system-packages)
  ├── pip install -r requirements.txt  (到 venv)
  └── COPY rootfs

FROM scratch AS APP
  └── COPY --from=Builder / /
```

**关键点**：
- `alpine:latest` 当前指向 3.23.4，提供 Python 3.12.x
- ffmpeg / intel-media-driver / libva-* 从 **edge 仓库**安装，获取 8.1.1
- 其余系统包从 latest（3.23）仓库安装

### 2.2 混用 edge 的 ABI 风险控制

ffmpeg 和 VAAPI 驱动是纯用户态库，依赖的 musl/libc 接口稳定。edge 和 3.23 的 musl 差异极小，混用风险可控。

**策略**：
1. ffmpeg 8.1.1 从 edge 安装，连带依赖（zimg、libdav1d 等）也从 edge 拉取
2. Python 3.12 及运行时包仅从 latest 安装，不混用 edge
3. 构建时先安装 latest 的包，再 overlay edge 的 ffmpeg 包

### 2.3 与 Plan 003 的协调

Plan 003 要求 ffmpeg 8.1.1 + zscale/tonemap/hwdownload。本方案通过 edge 仓库满足此需求，003 无需改动。

```
003 (HDR/GPU)  +  004 (Docker 升级)
       │              │
       │              ├─ alpine:latest (Python 3.12, 系统包)
       │              └─ edge repo (ffmpeg 8.1.1, VAAPI 驱动)
       │
       └─ 使用 ffmpeg 8.1.1 的 zscale/tonemap/vaapi
```

---

## 三、具体改动

### 3.1 Dockerfile 重构

```dockerfile
FROM alpine:latest AS Builder

# 构建依赖（编译 Python 包所需，含 Python 头文件）
RUN apk add --no-cache --virtual .build-deps \
        python3-dev \
        libffi-dev \
        gcc \
        musl-dev \
        libxml2-dev \
        libxslt-dev \
        linux-headers

# 运行时依赖（从 latest 仓库）
RUN apk add --no-cache \
        python3 \
        py3-pip \
        git tzdata zip curl bash fuse3 xvfb \
        inotify-tools chromium-chromedriver \
        s6-overlay redis wget shadow sudo \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && curl https://rclone.org/install.sh | bash \
    && if [ "$(uname -m)" = "x86_64" ]; then ARCH=amd64; elif [ "$(uname -m)" = "aarch64" ]; then ARCH=arm64; fi \
    && curl https://dl.min.io/client/mc/release/linux-${ARCH}/mc --create-dirs -o /usr/bin/mc \
    && chmod +x /usr/bin/mc

# ffmpeg 及 VAAPI 驱动从 edge 仓库安装（8.1.1）
RUN apk add --no-cache \
        ffmpeg \
        intel-media-driver \
        libva-dev \
        libva-utils \
        --repository=https://dl-cdn.alpinelinux.org/alpine/edge/community

# 使用 Python 虚拟环境，避免 --break-system-packages
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 升级 pip 工具链，安装依赖
# setuptools<81 保留原有 pin，避免 legacy 依赖不兼容
RUN pip install --upgrade pip wheel \
    && pip install "setuptools<81" \
    && pip install cython \
    && pip install -r https://raw.githubusercontent.com/alpha-86/nas-tools/master/requirements.txt --no-build-isolation

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
    && python_ver=$(python3 -V | awk '{print $2}') \
    && echo "${WORKDIR}/" > /opt/venv/lib/python${python_ver%.*}/site-packages/nas-tools.pth \
    && echo 'fs.inotify.max_user_watches=5242880' >> /etc/sysctl.conf \
    && echo 'fs.inotify.max_user_instances=5242880' >> /etc/sysctl.conf \
    && echo "nt ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers \
    && if [ -d third_party ]; then cd third_party && git submodule init && git submodule update; fi

EXPOSE 3000
VOLUME ["/config"]
ENTRYPOINT ["/init"]
```

**关键变更**：
1. `FROM alpine:latest` 保留（用户要求不固定版本）
2. 新增 `python3 -m venv /opt/venv` — 虚拟环境替代 `--break-system-packages`
3. ffmpeg 及 VAAPI 驱动从 edge 仓库单独安装
4. 更新 `PATH` 包含 `/opt/venv/bin`
5. `.pth` 路径用 `python${python_ver%.*}` 动态计算（兼容不同 Python 次版本）

### 3.2 package_list.txt 调整

将 `ffmpeg`、`intel-media-driver`、`libva-dev`、`libva-utils` 从 `package_list.txt` 中移除（改为在 Dockerfile 中从 edge 安装），避免 010-update 脚本从 latest 仓库重复安装旧版 ffmpeg。

```diff
# package_list.txt
git
-python3-dev
-py3-pip
+python3
+py3-pip
 tzdata
 zip
 curl
 bash
 fuse3
 xvfb
 inotify-tools
 chromium-chromedriver
 s6-overlay
-ffmpeg
 redis
 wget
 shadow
 sudo
-intel-media-driver
-libva-dev
-libva-utils
```

> 注：`python3-dev` 改为 `python3`（运行时不需要 dev 包），ffmpeg 和 VAAPI 驱动从 edge 安装不在 package_list.txt 中。

### 3.3 requirements.txt 升级策略

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

### 3.4 010-update 脚本适配

`docker/rootfs/etc/cont-init.d/010-update` 中的依赖更新逻辑需要完整适配虚拟环境，镜像构建时的行为（build deps、setuptools pin、cython、--no-build-isolation、清理）在自动更新时也要保持一致：

```diff
  function requirements_update {
      ...
+     # 安装构建依赖（与 Dockerfile 的 .build-deps 保持一致）
+     apk add --no-cache --virtual .update-build-deps \
+         python3-dev libffi-dev gcc musl-dev \
+         libxml2-dev libxslt-dev linux-headers
+
      if [ "${NASTOOL_CN_UPDATE}" = "true" ]; then
          package_cn
-         apk add --no-cache libffi-dev gcc musl-dev libxml2-dev libxslt-dev
-         pip install --upgrade pip setuptools wheel -i "${PYPI_MIRROR}"
-         pip install -r requirements.txt -i "${PYPI_MIRROR}"
+         /opt/venv/bin/pip install --upgrade pip wheel -i "${PYPI_MIRROR}"
+         /opt/venv/bin/pip install "setuptools<81" -i "${PYPI_MIRROR}"
+         /opt/venv/bin/pip install cython -i "${PYPI_MIRROR}"
+         /opt/venv/bin/pip install -r requirements.txt --no-build-isolation -i "${PYPI_MIRROR}"
+         install_status=$?
      else
-         apk add --no-cache libffi-dev gcc musl-dev libxml2-dev libxslt-dev
-         pip install --upgrade pip setuptools wheel
-         pip install -r requirements.txt
+         /opt/venv/bin/pip install --upgrade pip wheel
+         /opt/venv/bin/pip install "setuptools<81"
+         /opt/venv/bin/pip install cython
+         /opt/venv/bin/pip install -r requirements.txt --no-build-isolation
+         install_status=$?
      fi
+
+     # 清理构建依赖，避免镜像膨胀
+     apk del --purge .update-build-deps
+
+     # 检查 pip install 结果（必须在清理后，用保存的状态）
+     if [ "${install_status}" -ne 0 ]; then
+         echo "依赖安装失败，请检查日志"
+         exit 1
+     fi
      ...
  }
```

**注意**：
1. build deps 安装和清理与 Dockerfile 的 `.build-deps` 保持一致（含 `python3-dev`、`linux-headers`）
2. `setuptools<81` pin 保留，与 Dockerfile 一致
3. `--no-build-isolation` 保留，某些包需要预装 cython
4. cython 在 requirements.txt 安装前显式安装
5. 010-update 的 `package_update` 函数目前从 `package_list.txt` 安装系统包。由于 ffmpeg 已从 package_list.txt 移除，自动更新时不会覆盖 edge 的 ffmpeg 8.1.1。但如果未来 `package_list.txt` 中重新加入 `ffmpeg`，会从 latest 安装旧版。需确保维护者知晓此约束。

### 3.5 NAStool 服务脚本适配

`docker/rootfs/etc/services.d/NAStool/run` 中的 `python3` 调用需要改为虚拟环境路径：

```diff
  exec \
      s6-notifyoncheck ... \
-     cd ${WORKDIR} s6-setuidgid nt python3 run.py
+     cd ${WORKDIR} s6-setuidgid nt /opt/venv/bin/python3 run.py
```

---

## 四、文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `docker/Dockerfile` | 重构 | 保留 `alpine:latest`；新增 Python 虚拟环境 `/opt/venv`；移除 `--break-system-packages`；ffmpeg/VAAPI 驱动从 edge 安装；更新 PATH 和 .pth 路径 |
| `package_list.txt` | 移除 ffmpeg/VAAPI | 将 `ffmpeg`、`intel-media-driver`、`libva-dev`、`libva-utils` 移除（改从 edge 安装）；`python3-dev` 改为 `python3` |
| `requirements.txt` | 部分升级 | 阶段 1 安全升级（cryptography, pillow, requests 等同主版本最新）；阶段 2/3 保持原版本待验证 |
| `docker/rootfs/etc/services.d/NAStool/run` | 1 行 | `python3` → `/opt/venv/bin/python3` |
| `docker/rootfs/etc/cont-init.d/010-update` | 重写 requirements_update | 虚拟环境 pip 路径 + build-deps 安装/清理 + setuptools<81 pin + cython + --no-build-isolation + install_status 保存 |

---

## 五、验证方式

### 5.1 Docker 构建验证

```bash
# 1. 构建镜像
docker build -t nas-tools:test -f docker/Dockerfile .

# 2. 确认 Python 版本（覆盖 entrypoint /init）
docker run --rm --entrypoint python3 nas-tools:test --version
# 期望: Python 3.12.x

# 3. 确认 ffmpeg 版本及关键滤镜
docker run --rm --entrypoint ffmpeg nas-tools:test -version | head -1
# 期望: ffmpeg version 8.1.x
docker run --rm --entrypoint ffmpeg nas-tools:test -filters 2>&1 | grep -E "zscale|tonemap|hwdownload"
# 期望: 三条都输出非空

# 4. 确认虚拟环境
docker run --rm --entrypoint sh nas-tools:test -c "which python3"
# 期望: /opt/venv/bin/python3

# 5. 确认 pip 包安装成功
docker run --rm --entrypoint sh nas-tools:test -c "pip list | grep -E 'Flask|SQLAlchemy|requests'"
```

### 5.2 运行时功能验证

| # | 验证项 | 方法 |
|---|---|---|
| 1 | 服务启动 | `docker run` 后查看日志，确认无 ImportError |
| 2 | WEB 登录 | 访问 `http://IP:3000`，验证登录正常 |
| 3 | 文件整理识别 | 上传/整理一个视频文件，验证识别流程 |
| 4 | 定时任务 | 验证 RSS、订阅等定时任务正常触发 |
| 5 | ffmpeg 截图 | 用 Plan 003 的测试文件验证 thumb 生成 |
| 6 | 自动更新脚本 | 修改 requirements.txt 后重启容器，验证 010-update 正确重装依赖 |
| 7 | VAAPI GPU | `ffmpeg -hwaccels` 输出包含 vaapi |

---

## 六、风险与注意事项

1. **`alpine:latest` 滚动风险**：latest 会随 alpine 新版本发布而漂移（当前为 3.23.4，未来可能到 3.24+）。Python 版本可能从 3.12 变为 3.13 或 3.14，需要代码兼容。当前代码在 Python 3.12 上运行正常，但 3.13+ 的语法/API 变更需要持续验证。

2. **edge 仓库滚动风险**：edge 是滚动更新，ffmpeg 8.1.1 可能在某次构建时变为 8.2.x 或 9.0。API 兼容性通常保持向后兼容，但构建不可复现。如需锁定，可用 `apk add ffmpeg=8.1.1-r0 --repository=edge/community`，但 edge 包可能随时被移除旧版本。

3. **混用 ABI 风险**：edge 的 ffmpeg 8.1.1 依赖的库（zimg、libdav1d 等）版本可能高于 latest 仓库的其他包。实测中尚未发现 musl 不兼容，但如遇 segfault 需排查依赖版本。

4. **`--break-system-packages` 移除**：使用虚拟环境后不再需要此标志。010-update 和 Dockerfile 中的 pip 命令都需要指向 `/opt/venv/bin/pip`。

5. **Flask 2→3 升级**：Flask 3 移除 `session_cookie_name` 等旧属性，移除 `app.json_encoder`。当前代码未使用这些特性，但建议验证后再升级。

6. **openai 0→1 升级**：openai 1.x 是全新 API（`openai.OpenAI()` 客户端模式），`openai_helper.py` 需要完全重写。建议作为独立任务处理，不在 004 范围内升级 openai 包。

7. **alpine 的 Chromium**：`chromium-chromedriver` 包在 alpine 中可能版本较新，需验证与 `undetected-chromedriver` 的兼容性。

8. **镜像大小**：虚拟环境 `/opt/venv` 会增加 ~100-200MB 镜像大小。多阶段构建（`FROM scratch AS APP`）已将 Builder 层的临时文件剥离，venv 本身必须保留在最终镜像中。

9. **010-update 的 ffmpeg 覆盖风险**：如果未来维护者在 `package_list.txt` 中重新加入 `ffmpeg`，010-update 会从 latest 安装旧版 ffmpeg 覆盖 edge 的 8.1.1。建议在 010-update 中保留 edge 仓库配置，或在文档中明确标注 ffmpeg 必须从 edge 安装。
