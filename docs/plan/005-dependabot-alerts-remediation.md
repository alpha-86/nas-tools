# Dependabot Alerts Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all 29 open GitHub Dependabot alerts for `alpha-86/nas-tools` by upgrading vulnerable Python packages and preserving the Docker/runtime dependency installation path.

**Architecture:** Treat `requirements.txt` as the single source of Python dependency truth. Build-time Docker installs must copy and install the repository-local `requirements.txt`; runtime/web upgrades must reinstall with `/opt/venv/bin/pip` so the app uses the venv instead of system Python.

**Tech Stack:** Python 3, Flask/Werkzeug, pip, Alpine Docker image, s6-overlay init scripts, GitHub Dependabot.

---

## 背景

本计划基于 2026-05-10 在仓库 `/home/work/code/nas-tools` 执行的 GitHub CLI 查询：

```bash
gh api --paginate 'repos/alpha-86/nas-tools/dependabot/alerts?state=open&per_page=100'
```

查询结果：open alerts 共 29 个，全部来自 `requirements.txt` 的 pip runtime 依赖。严重级别分布为 high 12 个、medium 13 个、low 4 个。最高风险项集中在 `Werkzeug`、`urllib3`、`Pillow`、`cryptography`、`PyJWT`、`lxml`、`Mako`。

当前关键文件现状：

| 文件 | 现状 | 计划约束 |
|---|---|---|
| `requirements.txt` | 多个直接依赖仍低于 Dependabot first patched version | 只升级被 alert 命中的包，避免无关依赖大范围漂移 |
| `docker/Dockerfile` | 已 `COPY requirements.txt /tmp/requirements.txt` 并在 venv 中 `pip install -r /tmp/requirements.txt` | 必须保留本地 requirements 安装路径，不能回退到远程 requirements 或系统 pip |
| `docker/rootfs/etc/cont-init.d/010-update` | `requirements_update` 已使用 `/opt/venv/bin/pip`，但 Debian 分支仍含 Alpine 包名 `musl-dev`，且 `package_cn` 只适配 apk | 必须明确 Alpine/Debian 分支，或收敛为 Alpine-only 并删除/禁用 Debian 路径 |
| `web/action.py` | Web 更新已使用 `sudo /opt/venv/bin/pip install -r /nas-tools/requirements.txt` | 必须保留 venv pip，建议补齐 `--no-build-isolation` 与镜像参数一致性 |

## Alerts 汇总表

| # | Package | Manifest | Severity | Summary | CVE/GHSA | Vulnerable range | First patched | URL |
|---:|---|---|---|---|---|---|---|---|
| 72 | pillow | `requirements.txt` | high | Pillow vulnerability can cause write buffer overflow on BCn encoding | CVE-2025-48379 / GHSA-xg8h-j46f-w952 | `>= 11.2.0, < 11.3.0` | 11.3.0 | https://github.com/alpha-86/nas-tools/security/dependabot/72 |
| 71 | urllib3 | `requirements.txt` | medium | urllib3 does not control redirects in browsers and Node.js | CVE-2025-50182 / GHSA-48p4-8xcf-vxj5 | `>= 2.2.0, < 2.5.0` | 2.5.0 | https://github.com/alpha-86/nas-tools/security/dependabot/71 |
| 70 | Mako | `requirements.txt` | high | Mako vulnerable to path traversal via backslash URI on Windows in TemplateLookup | CVE-2026-44307 / GHSA-2h4p-vjrc-8xpq | `<= 1.3.11` | 1.3.12 | https://github.com/alpha-86/nas-tools/security/dependabot/70 |
| 69 | pillow | `requirements.txt` | medium | Pillow has a PDF Parsing Trailer Infinite Loop (DoS) | CVE-2026-42310 / GHSA-r73j-pqj5-w3x7 | `>= 4.2.0, < 12.2.0` | 12.2.0 | https://github.com/alpha-86/nas-tools/security/dependabot/69 |
| 68 | pillow | `requirements.txt` | medium | Pillow has an integer overflow when processing fonts | CVE-2026-42308 / GHSA-wjx4-4jcj-g98j | `< 12.2.0` | 12.2.0 | https://github.com/alpha-86/nas-tools/security/dependabot/68 |
| 67 | pillow | `requirements.txt` | high | Pillow has an OOB Write with Invalid PSD Tile Extents (Integer Overflow) | CVE-2026-42311 / GHSA-pwv6-vv43-88gr | `>= 10.3.0, < 12.2.0` | 12.2.0 | https://github.com/alpha-86/nas-tools/security/dependabot/67 |
| 66 | lxml | `requirements.txt` | high | lxml default configuration of iterparse() and ETCompatXMLParser() allows XXE to local files | CVE-2026-41066 / GHSA-vfmq-68hx-4jfw | `< 6.1.0` | 6.1.0 | https://github.com/alpha-86/nas-tools/security/dependabot/66 |
| 65 | python-dotenv | `requirements.txt` | medium | python-dotenv symlink following in set_key allows arbitrary file overwrite via cross-device rename fallback | CVE-2026-28684 / GHSA-mf9w-mj56-hr94 | `< 1.2.2` | 1.2.2 | https://github.com/alpha-86/nas-tools/security/dependabot/65 |
| 64 | Mako | `requirements.txt` | medium | Mako path traversal via double-slash URI prefix in TemplateLookup | CVE-2026-41205 / GHSA-v92g-xgxw-vvmm | `<= 1.3.10` | 1.3.11 | https://github.com/alpha-86/nas-tools/security/dependabot/64 |
| 63 | pillow | `requirements.txt` | high | FITS GZIP decompression bomb in Pillow | CVE-2026-40192 / GHSA-whj4-6x5x-4v2j | `>= 10.3.0, < 12.2.0` | 12.2.0 | https://github.com/alpha-86/nas-tools/security/dependabot/63 |
| 62 | Pygments | `requirements.txt` | low | Pygments has Regular Expression Denial of Service due to inefficient regex for GUID matching | CVE-2026-4539 / GHSA-5239-wwwm-4pmq | `< 2.20.0` | 2.20.0 | https://github.com/alpha-86/nas-tools/security/dependabot/62 |
| 61 | cryptography | `requirements.txt` | low | cryptography has incomplete DNS name constraint enforcement on peer names | CVE-2026-34073 / GHSA-m959-cc7f-wv43 | `< 46.0.6` | 46.0.6 | https://github.com/alpha-86/nas-tools/security/dependabot/61 |
| 60 | requests | `requirements.txt` | medium | Requests has insecure temp file reuse in extract_zipped_paths() | CVE-2026-25645 / GHSA-gc5v-m9x4-r6x2 | `< 2.33.0` | 2.33.0 | https://github.com/alpha-86/nas-tools/security/dependabot/60 |
| 58 | PyJWT | `requirements.txt` | high | PyJWT accepts unknown `crit` header extensions | CVE-2026-32597 / GHSA-752w-5fwx-jx9f | `<= 2.11.0` | 2.12.0 | https://github.com/alpha-86/nas-tools/security/dependabot/58 |
| 57 | werkzeug | `requirements.txt` | medium | Werkzeug safe_join() allows Windows special device names | CVE-2026-27199 / GHSA-29vq-49wr-vm6x | `< 3.1.6` | 3.1.6 | https://github.com/alpha-86/nas-tools/security/dependabot/57 |
| 56 | flask | `requirements.txt` | low | Flask session does not add `Vary: Cookie` header when accessed in some ways | CVE-2026-27205 / GHSA-68rp-wp8r-4726 | `< 3.1.3` | 3.1.3 | https://github.com/alpha-86/nas-tools/security/dependabot/56 |
| 55 | pillow | `requirements.txt` | high | Pillow affected by out-of-bounds write when loading PSD images | CVE-2026-25990 / GHSA-cfh3-3jmp-rvhc | `>= 10.3.0, < 12.1.1` | 12.1.1 | https://github.com/alpha-86/nas-tools/security/dependabot/55 |
| 54 | cryptography | `requirements.txt` | high | cryptography vulnerable to a subgroup attack due to missing subgroup validation for SECT curves | CVE-2026-26007 / GHSA-r6ph-v2qm-q3c2 | `<= 46.0.4` | 46.0.5 | https://github.com/alpha-86/nas-tools/security/dependabot/54 |
| 53 | Werkzeug | `requirements.txt` | medium | Werkzeug safe_join() allows Windows special device names with compound extensions | CVE-2026-21860 / GHSA-87hc-h4r5-73f7 | `< 3.1.5` | 3.1.5 | https://github.com/alpha-86/nas-tools/security/dependabot/53 |
| 52 | urllib3 | `requirements.txt` | high | Decompression-bomb safeguards bypassed when following HTTP redirects (streaming API) | CVE-2026-21441 / GHSA-38jv-5279-wg99 | `>= 1.22, < 2.6.3` | 2.6.3 | https://github.com/alpha-86/nas-tools/security/dependabot/52 |
| 51 | urllib3 | `requirements.txt` | high | urllib3 streaming API improperly handles highly compressed data | CVE-2025-66471 / GHSA-2xpw-w6gg-jr37 | `>= 1.0, < 2.6.0` | 2.6.0 | https://github.com/alpha-86/nas-tools/security/dependabot/51 |
| 50 | urllib3 | `requirements.txt` | high | urllib3 allows an unbounded number of links in the decompression chain | CVE-2025-66418 / GHSA-gm62-xv2j-4w53 | `>= 1.24, < 2.6.0` | 2.6.0 | https://github.com/alpha-86/nas-tools/security/dependabot/50 |
| 49 | werkzeug | `requirements.txt` | medium | Werkzeug safe_join() allows Windows special device names | CVE-2025-66221 / GHSA-hgf8-39gv-g3f2 | `< 3.1.4` | 3.1.4 | https://github.com/alpha-86/nas-tools/security/dependabot/49 |
| 47 | urllib3 | `requirements.txt` | medium | urllib3 redirects are not disabled when retries are disabled on PoolManager instantiation | CVE-2025-50181 / GHSA-pq67-6m6q-mj2v | `< 2.5.0` | 2.5.0 | https://github.com/alpha-86/nas-tools/security/dependabot/47 |
| 46 | requests | `requirements.txt` | medium | Requests vulnerable to .netrc credentials leak via malicious URLs | CVE-2024-47081 / GHSA-9hjg-9r4m-mvj7 | `< 2.32.4` | 2.32.4 | https://github.com/alpha-86/nas-tools/security/dependabot/46 |
| 42 | cryptography | `requirements.txt` | low | Vulnerable OpenSSL included in cryptography wheels | CVE-2024-12797 / GHSA-79v4-65xg-pq4g | `>= 42.0.0, < 44.0.1` | 44.0.1 | https://github.com/alpha-86/nas-tools/security/dependabot/42 |
| 38 | werkzeug | `requirements.txt` | medium | Werkzeug possible resource exhaustion when parsing file data in forms | CVE-2024-49767 / GHSA-q34m-jh98-gwm2 | `<= 3.0.5` | 3.0.6 | https://github.com/alpha-86/nas-tools/security/dependabot/38 |
| 37 | Werkzeug | `requirements.txt` | medium | Werkzeug safe_join not safe on Windows | CVE-2024-49766 / GHSA-f9vj-2wh5-fj8j | `<= 3.0.5` | 3.0.6 | https://github.com/alpha-86/nas-tools/security/dependabot/37 |
| 29 | Werkzeug | `requirements.txt` | high | Werkzeug debugger vulnerable to remote execution when interacting with attacker controlled domain | CVE-2024-34069 / GHSA-2g68-c3qc-8985 | `< 3.0.3` | 3.0.3 | https://github.com/alpha-86/nas-tools/security/dependabot/29 |

## 按包合并后的目标版本建议

| Package | Current in `requirements.txt` | Alerts | Highest severity | Target version | Rationale |
|---|---:|---|---|---:|---|
| `pillow` | 11.2.1 | 55, 63, 67, 68, 69, 72 | high | 12.2.0 | 覆盖所有 Pillow first patched version，其中最高要求为 12.2.0 |
| `urllib3` | 2.4.0 | 47, 50, 51, 52, 71 | high | 2.6.3 | 覆盖 2.5.0、2.6.0、2.6.3，且与 `requests` 新版通常兼容 |
| `Werkzeug` | 2.3.8 | 29, 37, 38, 49, 53, 57 | high | 3.1.6 | 覆盖所有 Werkzeug alerts；必须与 Flask 3.1.3 同步升级 |
| `Flask` | 2.2.5 | 56 | low | 3.1.3 | Flask alert 要求 3.1.3；因 Werkzeug 3.1.6 需要 Flask 3.x 配套 |
| `cryptography` | 44.0.0 | 42, 54, 61 | high | 46.0.6 | 覆盖 44.0.1、46.0.5、46.0.6；注意 Rust/OpenSSL/wheel 平台差异 |
| `requests` | 2.32.3 | 46, 60 | medium | 2.33.0 | 覆盖 2.32.4、2.33.0；同时配套 `urllib3==2.6.3` 验证 |
| `PyJWT` | 2.6.0 | 58 | high | 2.12.0 | `web/security.py` 使用 `jwt.encode/decode`，需验证返回类型和异常兼容 |
| `lxml` | 5.3.2 | 66 | high | 6.1.0 | 修复默认 parser XXE 行为；需验证 XPath/XML 解析代码 |
| `Mako` | 1.2.3 | 64, 70 | high | 1.3.12 | 覆盖 Windows path traversal 修复；主要由 Alembic/SQLAlchemy 间接使用 |
| `python-dotenv` | 0.20.0 | 65 | medium | 1.2.2 | 项目未见直接使用，但直接依赖被 alert 命中 |
| `Pygments` | 2.15.0 | 62 | low | 2.20.0 | 低风险安全修复，项目未见核心路径直接调用 |

建议一次性修改 `requirements.txt` 中上述 11 行，不升级未命中的包。这样 Dependabot 会在下一次扫描中关闭 29 个 alerts，同时降低兼容性变量。

## 兼容性风险

### Flask/Werkzeug 2 -> 3

风险最高。当前为 `Flask==2.2.5` + `Werkzeug==2.3.8`，目标为 `Flask==3.1.3` + `Werkzeug==3.1.6`。需要重点验证：

- `web/main.py` 的 `send_file`、`send_from_directory`、request/session/cookie 行为。
- `flask-restx==1.0.6` 与 Flask 3 的兼容性。若启动报错，优先升级 `flask-restx` 到兼容 Flask 3 的 1.3.x，而不是降级 Flask/Werkzeug。
- `flask-compress==1.13`、`flask-sock==0.6.0` 在 Flask 3 下的初始化和 websocket 行为。
- Werkzeug 3 移除部分历史 API；全仓搜索 `werkzeug.` 直接使用点，当前关键直接引用为 `web/action.py` 的 `generate_password_hash`，通常兼容。

### Pillow 12.2.0

项目使用点包括 `app/utils/image_utils.py` 和验证码/图片处理插件。Pillow 12 可能移除历史常量或变更图片格式细节。当前代码使用 `Image.BILINEAR`，需要验证在 12.2.0 下是否仍可用；若被弃用或移除，改为 `Image.Resampling.BILINEAR`，并保留兼容 fallback。

### lxml 6.1.0

项目大量使用 `lxml.etree.HTML` 和少量 `etree.XML`。lxml 6.1.0 的安全默认值改变主要影响 `iterparse()` 与 `ETCompatXMLParser()`，但仍需验证 RSS、豆瓣、站点解析：

- `app/rsschecker.py`
- `app/helper/site_helper.py`
- `app/media/doubanapi/webapi.py`
- `app/sites/siteuserinfo/*`
- `app/plugins/modules/*`

如发现 XML 实体解析相关行为差异，应显式设置 parser 安全参数，不要恢复不安全默认值。

### cryptography 46.0.6

`cryptography` 46 可能需要 Rust toolchain 或可用 wheel。当前 Dockerfile 已安装 `cargo`、`openssl-dev`，适合 source build；但 Alpine/musl 平台仍要验证 wheel/source build。若 pip 选择 source build 失败，优先保留 Dockerfile 的 `cargo` 和 `openssl-dev`，并检查 `pip install --no-build-isolation` 是否影响 cryptography 构建。

### requests 2.33.0 / urllib3 2.6.3

项目 HTTP 请求多，风险在代理、TLS verify、redirect、stream 行为。重点验证：

- `app/utils/http_utils.py`
- `app/media/tmdbv3api/tmdb.py`
- `app/sites/siteuserinfo/_base.py`
- 消息客户端 `app/message/client/*.py`
- 下载器客户端和插件中的 `requests.Session`

如果第三方库对 `urllib3<2.6` 有上限，先通过 `pip check` 定位约束，再决定是否同步升级该第三方库。

### PyJWT 2.12.0

`web/security.py` 使用 `jwt.encode` 和 `jwt.decode`。验证点：

- `jwt.encode(...)` 返回值是否仍是 `str`，登录 token 响应格式不变。
- 过期 token 分支捕获 `jwt.ExpiredSignatureError` 后再次 decode 的行为是否仍符合预期。
- `jwt.DecodeError`、`jwt.InvalidTokenError`、`jwt.ImmatureSignatureError` 异常路径是否仍存在。

### Mako 1.3.12

主要用于 Alembic/SQLAlchemy 模板路径。项目没有明显直接调用 `TemplateLookup`。风险较低，但迁移/初始化命令必须跑一遍，避免间接依赖版本范围冲突。

### python-dotenv 1.2.2

项目未见直接导入。风险主要来自传递依赖或插件。如果 `pip check` 通过，通常无需代码变更。

### Pygments 2.20.0

项目未见核心路径直接导入。风险较低；只需验证安装和启动。

## 实施策略

1. 先创建依赖升级分支，并确认工作区未覆盖他人变更：

```bash
git status --short
git switch -c dependabot-alerts-remediation
```

2. 只修改 `requirements.txt` 中被 Dependabot 命中的 11 个直接依赖：

```text
cryptography==46.0.6
Flask==3.1.3
lxml==6.1.0
Mako==1.3.12
pillow==12.2.0
Pygments==2.20.0
PyJWT==2.12.0
python-dotenv==1.2.2
requests==2.33.0
urllib3==2.6.3
Werkzeug==3.1.6
```

3. 保持 Dockerfile 的本地 requirements 安装路径：

```dockerfile
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip wheel \
    && pip install "setuptools<81" \
    && pip install cython hatchling \
    && pip install -r /tmp/requirements.txt --no-build-isolation
```

4. 保持运行时和网页升级路径使用 venv pip：

```bash
/opt/venv/bin/pip install -r requirements.txt --no-build-isolation
sudo /opt/venv/bin/pip install -r /nas-tools/requirements.txt --no-build-isolation
```

5. 对 `010-update` 的 OS 分支做一次明确收敛：

- 推荐方案：当前 Dockerfile 已收敛到 Alpine，`010-update` 运行路径也收敛为 Alpine-only。删除 Debian 分支或让 Debian 分支直接打印“不支持 Debian runtime auto update”并退出该分支。
- 可选方案：继续支持 Debian，但必须把 Debian 构建依赖替换为真实 apt 包名，不能保留 `musl-dev`；`package_cn` 调用必须按 OS 选择 `package_cn_debian` 或 `package_cn`。

推荐采用 Alpine-only，因为当前镜像 `FROM alpine:latest`，维护两套运行时更新路径会扩大测试矩阵。

## 具体文件改动清单

### `requirements.txt`

修改以下行：

| Line | From | To |
|---:|---|---|
| 21 | `cryptography==44.0.0` | `cryptography==46.0.6` |
| 27 | `Flask==2.2.5` | `Flask==3.1.3` |
| 47 | `lxml==5.3.2` | `lxml==6.1.0` |
| 48 | `Mako==1.2.3` | `Mako==1.3.12` |
| 59 | `pillow==11.2.1` | `pillow==12.2.0` |
| 67 | `Pygments==2.15.0` | `Pygments==2.20.0` |
| 68 | `PyJWT==2.6.0` | `PyJWT==2.12.0` |
| 77 | `python-dotenv==0.20.0` | `python-dotenv==1.2.2` |
| 85 | `requests==2.32.3` | `requests==2.33.0` |
| 106 | `urllib3==2.4.0` | `urllib3==2.6.3` |
| 112 | `Werkzeug==2.3.8` | `Werkzeug==3.1.6` |

### `docker/Dockerfile`

Verify-only unless current file changes before implementation. Required invariants:

- `COPY requirements.txt /tmp/requirements.txt` exists before pip install.
- `pip install -r /tmp/requirements.txt --no-build-isolation` uses the repository-local file.
- `/opt/venv/bin` is in `PATH` in both builder and final runtime.
- Build deps include `cargo` and `openssl-dev` for `cryptography` source build fallback.

### `docker/rootfs/etc/cont-init.d/010-update`

Modify this file if it still contains mixed Alpine/Debian behavior at implementation time. Recommended concrete change:

```bash
function is_debian_runtime {
    grep -Eqi "Debian" /etc/issue 2>/dev/null || grep -Eq "Debian" /etc/os-release 2>/dev/null
}

function requirements_update {
    hash_old=$(cat /tmp/requirements.txt.sha256sum)
    hash_new=$(sha256sum requirements.txt)
    if [ "${hash_old}" != "${hash_new}" ]; then
        echo "检测到requirements.txt有变化，重新安装依赖..."

        if is_debian_runtime; then
            echo "当前镜像已收敛为 Alpine，Debian runtime 自动依赖更新不在支持范围内。"
            exit 1
        fi

        apk add --no-cache --virtual .update-build-deps \
            python3-dev libffi-dev gcc musl-dev \
            libxml2-dev libxslt-dev linux-headers \
            openssl-dev cargo

        if [ "${NASTOOL_CN_UPDATE}" = "true" ]; then
            package_cn
            /opt/venv/bin/pip install --upgrade pip wheel -i "${PYPI_MIRROR}"
            /opt/venv/bin/pip install "setuptools<81" -i "${PYPI_MIRROR}"
            /opt/venv/bin/pip install cython hatchling -i "${PYPI_MIRROR}"
            /opt/venv/bin/pip install -r requirements.txt --no-build-isolation -i "${PYPI_MIRROR}"
            install_status=$?
        else
            /opt/venv/bin/pip install --upgrade pip wheel
            /opt/venv/bin/pip install "setuptools<81"
            /opt/venv/bin/pip install cython hatchling
            /opt/venv/bin/pip install -r requirements.txt --no-build-isolation
            install_status=$?
        fi

        apk del --purge .update-build-deps 2>/dev/null || true

        if [ "${install_status}" -ne 0 ]; then
            echo "无法安装依赖，请更新镜像！"
            exit 1
        fi

        echo "依赖安装成功"
        sha256sum requirements.txt > /tmp/requirements.txt.sha256sum
    fi
}
```

If Debian support must remain, replace the Alpine-only guard with apt packages:

```bash
apt-get install -y python3-dev libffi-dev gcc \
    libxml2-dev libxslt-dev linux-headers-amd64 \
    libssl-dev cargo pkg-config
```

and never call `package_cn` in the Debian branch; call `package_cn_debian`.

### `web/action.py`

Verify that the update path remains venv-only. Recommended concrete line:

```python
os.system('sudo /opt/venv/bin/pip install -r /nas-tools/requirements.txt --no-build-isolation')
```

Do not replace it with `pip`, `python3 -m pip`, or system package manager commands.

## 分阶段任务

### Task 1: Update direct dependency pins

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Edit only the 11 vulnerable direct pins**

Apply these exact replacements:

```diff
-cryptography==44.0.0
+cryptography==46.0.6
-Flask==2.2.5
+Flask==3.1.3
-lxml==5.3.2
+lxml==6.1.0
-Mako==1.2.3
+Mako==1.3.12
-pillow==11.2.1
+pillow==12.2.0
-Pygments==2.15.0
+Pygments==2.20.0
-PyJWT==2.6.0
+PyJWT==2.12.0
-python-dotenv==0.20.0
+python-dotenv==1.2.2
-requests==2.32.3
+requests==2.33.0
-urllib3==2.4.0
+urllib3==2.6.3
-Werkzeug==2.3.8
+Werkzeug==3.1.6
```

- [ ] **Step 2: Install into a clean local venv**

Run:

```bash
python3 -m venv /tmp/nas-tools-deps-check
/tmp/nas-tools-deps-check/bin/pip install --upgrade pip wheel
/tmp/nas-tools-deps-check/bin/pip install "setuptools<81" cython hatchling
/tmp/nas-tools-deps-check/bin/pip install -r requirements.txt --no-build-isolation
/tmp/nas-tools-deps-check/bin/pip check
```

Expected: install succeeds and `pip check` reports no broken requirements.

- [ ] **Step 3: Commit dependency pins**

Run:

```bash
git add requirements.txt
git commit -m "fix: update vulnerable Python dependencies"
```

### Task 2: Preserve build and runtime install paths

**Files:**
- Verify: `docker/Dockerfile`
- Modify if needed: `docker/rootfs/etc/cont-init.d/010-update`
- Modify if needed: `web/action.py`

- [ ] **Step 1: Verify Dockerfile local requirements install**

Run:

```bash
rg -n "COPY requirements.txt /tmp/requirements.txt|pip install -r /tmp/requirements.txt|/opt/venv/bin" docker/Dockerfile
```

Expected: all three patterns are present.

- [ ] **Step 2: Normalize runtime update script**

If `010-update` still contains Debian package installation with Alpine package names, apply the Alpine-only `requirements_update` implementation from the section above. Keep every pip command as `/opt/venv/bin/pip`.

- [ ] **Step 3: Normalize web update command**

If `web/action.py` lacks `--no-build-isolation`, update the dependency reinstall line to:

```python
os.system('sudo /opt/venv/bin/pip install -r /nas-tools/requirements.txt --no-build-isolation')
```

- [ ] **Step 4: Shell syntax check**

Run:

```bash
bash -n docker/rootfs/etc/cont-init.d/010-update
python3 -m py_compile web/action.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit install-path changes**

Run:

```bash
git add docker/Dockerfile docker/rootfs/etc/cont-init.d/010-update web/action.py
git commit -m "fix: keep dependency updates inside application venv"
```

If only verification was needed and no file changed, skip this commit.

### Task 3: Run compatibility smoke tests

**Files:**
- Verify runtime imports and focused code paths.

- [ ] **Step 1: Import vulnerable packages at target versions**

Run:

```bash
/tmp/nas-tools-deps-check/bin/python - <<'PY'
import cryptography, flask, lxml, mako, PIL, pygments, jwt, dotenv, requests, urllib3, werkzeug
print("cryptography", cryptography.__version__)
print("flask", flask.__version__)
print("lxml", lxml.__version__)
print("mako", mako.__version__)
print("pillow", PIL.__version__)
print("pygments", pygments.__version__)
print("pyjwt", jwt.__version__)
print("requests", requests.__version__)
print("urllib3", urllib3.__version__)
print("werkzeug", werkzeug.__version__)
PY
```

Expected: printed versions match target versions.

- [ ] **Step 2: Compile core Python modules**

Run:

```bash
/tmp/nas-tools-deps-check/bin/python -m compileall app web config.py
```

Expected: compile completes without syntax/import-time failures.

- [ ] **Step 3: Run available focused tests**

Run:

```bash
pytest -q
```

If the repository has no maintained test suite, record that result and run at least:

```bash
/tmp/nas-tools-deps-check/bin/python -m py_compile web/security.py web/main.py web/action.py app/utils/image_utils.py app/utils/http_utils.py
```

Expected: commands exit 0.

### Task 4: Build Docker image and verify application starts

**Files:**
- Verify: `docker/Dockerfile`
- Verify: `docker/rootfs/etc/cont-init.d/010-update`

- [ ] **Step 1: Build image**

Run:

```bash
docker build -t nas-tools:dependabot-remediation .
```

Expected: build succeeds and pip installs from `/tmp/requirements.txt`.

- [ ] **Step 2: Inspect installed versions inside image**

Run:

```bash
docker run --rm nas-tools:dependabot-remediation /opt/venv/bin/python - <<'PY'
import cryptography, flask, lxml, mako, PIL, pygments, jwt, dotenv, requests, urllib3, werkzeug
print(cryptography.__version__, flask.__version__, lxml.__version__, mako.__version__)
print(PIL.__version__, pygments.__version__, jwt.__version__, requests.__version__, urllib3.__version__, werkzeug.__version__)
PY
```

Expected: target versions are installed from `/opt/venv`.

- [ ] **Step 3: Start container smoke test**

Run:

```bash
docker run --rm -d --name nas-tools-deps-smoke -p 3000:3000 nas-tools:dependabot-remediation
sleep 20
docker logs --tail 200 nas-tools-deps-smoke
curl -I http://127.0.0.1:3000/
docker rm -f nas-tools-deps-smoke
```

Expected: container stays up long enough to serve HTTP; logs do not show Flask/Werkzeug import errors.

### Task 5: Confirm Dependabot closure

**Files:**
- Verify only.

- [ ] **Step 1: Push branch and wait for Dependabot/security scan**

Run:

```bash
git push -u origin dependabot-alerts-remediation
```

- [ ] **Step 2: Re-query open alerts**

Run after GitHub has scanned the branch/PR:

```bash
gh api --paginate 'repos/alpha-86/nas-tools/dependabot/alerts?state=open&per_page=100' \
  | jq -r '.[] | [.number, .dependency.package.name, .security_vulnerability.severity, .security_advisory.summary, .security_vulnerability.first_patched_version.identifier, .html_url] | @tsv'
```

Expected: alerts for the 11 packages above are closed or no longer applicable. If an alert remains, compare the package casing in `requirements.txt` with Dependabot's package name and verify the target version is installed in the manifest Dependabot scans.

## 验证命令

Use these commands as the minimum acceptance gate:

```bash
git diff -- requirements.txt docker/Dockerfile docker/rootfs/etc/cont-init.d/010-update web/action.py
python3 -m venv /tmp/nas-tools-deps-check
/tmp/nas-tools-deps-check/bin/pip install --upgrade pip wheel
/tmp/nas-tools-deps-check/bin/pip install "setuptools<81" cython hatchling
/tmp/nas-tools-deps-check/bin/pip install -r requirements.txt --no-build-isolation
/tmp/nas-tools-deps-check/bin/pip check
bash -n docker/rootfs/etc/cont-init.d/010-update
/tmp/nas-tools-deps-check/bin/python -m py_compile web/security.py web/main.py web/action.py app/utils/image_utils.py app/utils/http_utils.py
/tmp/nas-tools-deps-check/bin/python -m compileall app web config.py
docker build -t nas-tools:dependabot-remediation .
```

If `pytest` is available and tests are present:

```bash
pytest -q
```

## 回滚策略

Rollback should be package-grouped, not all-or-nothing, so security fixes remain where possible:

1. If Flask/Werkzeug 3 breaks app startup, first upgrade Flask extensions (`flask-restx`, `flask-compress`, `flask-sock`) to compatible versions and rerun tests. Only if that fails, temporarily split into two PRs: non-Flask dependencies first, Flask/Werkzeug migration second.
2. If Pillow 12 breaks image code, update the code for new Pillow APIs (`Image.Resampling.BILINEAR`) instead of downgrading below 12.2.0.
3. If cryptography 46 fails to build on Alpine, keep the security target and fix build deps (`cargo`, `openssl-dev`, `pkgconfig/pkgconf`, `rust`) before considering a lower patched version. Do not go below 46.0.6 because alert 61 requires it.
4. If requests/urllib3 conflicts with a third-party dependency, identify the conflicting dependency with `pip check` and upgrade that dependency in the same PR. Do not pin urllib3 below 2.6.3 because alerts 50-52 require it.
5. If lxml 6 changes parser behavior, add explicit safe parser options at call sites. Do not restore unsafe entity resolution.

Exact rollback command for a single failed package group before committing:

```bash
git diff -- requirements.txt
git restore -p requirements.txt
```

If a commit has already been made, revert only the problematic commit:

```bash
git revert <commit-sha>
```

Do not use `git reset --hard` in this repository because other agents may have uncommitted work.

## 给 Claude 的执行提示

- Do not edit `docs/plan/001-*` through `docs/plan/004-*`.
- Assume the worktree may contain other people's uncommitted changes. Inspect `git status --short` before editing and avoid reverting unrelated changes.
- Start with `requirements.txt`; keep the change set narrow to the 11 vulnerable direct dependencies.
- Preserve Dockerfile's local `requirements.txt` install. Any plan that fetches requirements from GitHub during build is incorrect.
- Use `/opt/venv/bin/pip` in runtime and web update paths. Any plan that uses bare `pip`, system `python3 -m pip`, or `--break-system-packages` is incorrect.
- Resolve the `010-update` Alpine/Debian ambiguity explicitly. Preferred outcome: Alpine-only runtime auto-update because the current Docker image is `alpine:latest`.
- Treat Flask/Werkzeug migration as the main compatibility risk. Run import/startup checks before broad manual testing.
- After changes, re-run the `gh api` alert query and include before/after alert counts in the PR notes.
