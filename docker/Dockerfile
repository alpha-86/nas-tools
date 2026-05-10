FROM alpine:latest AS Builder

# 构建依赖（编译 Python 包所需，含 Python 头文件）
RUN apk add --no-cache --virtual .build-deps \
        python3-dev \
        libffi-dev \
        gcc \
        musl-dev \
        libxml2-dev \
        libxslt-dev \
        linux-headers \
        openssl-dev \
        cargo

# ffmpeg 及 VAAPI 驱动先从 edge 仓库安装（8.1.x），确保 edge 的库优先
# 必须同时添加 edge/main（glslang 等依赖）和 edge/community
RUN apk add --no-cache \
        ffmpeg \
        intel-media-driver \
        libva-dev \
        libva-utils \
        --repository=https://dl-cdn.alpinelinux.org/alpine/edge/main \
        --repository=https://dl-cdn.alpinelinux.org/alpine/edge/community

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

# 使用 Python 虚拟环境，避免 --break-system-packages
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 升级 pip 工具链，安装依赖
# setuptools<82: 82+ 移除了 pkg_resources（cn2an 等依赖）
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip wheel \
    && pip install "setuptools<82" \
    && pip install cython hatchling hatch-requirements-txt \
    && pip install -r /tmp/requirements.txt --no-build-isolation

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
ENTRYPOINT [ "/init" ]
