# CLAUDE.md — 本项目测试环境说明

## 1. 本地 Python 测试环境

项目根目录下存在一个预配置的虚拟环境：

```
/home/work/code/nas-tools/nastools/
```

所有直接运行 Python 代码（单测、脚本、命令行验证等）都必须使用此 venv，**禁止创建新的虚拟环境**。

使用方法：

```bash
# 激活 venv
source /home/work/code/nas-tools/nastools/bin/activate

# 运行 pytest
pytest tests/

# 运行特定测试文件
pytest tests/test_safe_arith_eval.py

# 运行 Python 脚本
python scripts/some_script.py
```

依赖安装也必须在此 venv 内完成：

```bash
pip install -r requirements.txt
```

## 2. Docker 实际测试环境

本项目已有一个运行中的 Docker 容器：

- **容器名**: `nastools`
- **镜像**: `alpha8686/nas-tools:latest`
- **项目路径（容器内）**: `/nas-tools`

### 测试流程

**禁止重新打包 Docker 镜像**。测试时直接登录到运行中的容器内，用 git 拉取对应分支或 PR：

```bash
# 登录容器
docker exec -it nastools /bin/sh

# 进入项目目录
cd /nas-tools

# 拉取对应分支（示例）
git fetch origin
git checkout origin/security/009-audit-remediation

# 重启容器内服务使改动生效
# （根据容器内的 init 系统，通常是 s6-svc 或 kill 主进程）
```

### 容器内 Git 状态说明

容器内的 `/nas-tools` 目录挂载自宿主机（或通过 COPY 构建），具体取决于部署方式。如果容器内已有 git 仓库，直接 `git pull` 或 `git checkout` 即可生效。如果容器内代码是通过 `COPY` 构建的静态副本，则需手动克隆或挂载宿主机目录。

实际测试前，先确认容器内 `/nas-tools` 是否为 git 仓库：

```bash
docker exec nastools test -d /nas-tools/.git && echo "git repo exists" || echo "no git repo"
```

如果不是 git 仓库，可通过挂载宿主机目录方式让容器读取最新代码：

```bash
# 宿主机执行：重新启动容器并挂载当前代码目录
docker restart nastools
# 或在 docker-compose 中设置 volume 挂载
```
