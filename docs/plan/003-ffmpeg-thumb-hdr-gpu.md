# Plan 003: FFmpeg 缩略图生成 — HDR/DV 色偏修复 + GPU 加速重构

> 目标：修复现有 ffmpeg 缩略图生成的 Intel GPU 路径 bug，解决 HDR/DV 视频色偏问题，扩展 GPU 检测支持，统一命令构建方式为 subprocess list。

---

## 一、现状与痛点

### 1.1 核心代码

- **`app/helper/ffmpeg_helper.py`** — FfmpegHelper 类，包含 `get_thumb_image_from_video()` 等方法
- **`app/media/scraper.py:674`** — 剧集刮削时调用 `FfmpegHelper().get_thumb_image_from_video()` 生成 episode thumb

### 1.2 现有逻辑

```python
def get_thumb_image_from_video(video_path, image_path, frames="00:03:01"):
    if FfmpegHelper().intel_gpu_exist_check():
        # GPU 路径（Intel VAAPI）— 有 bug
        cmd = 'ffmpeg -hwaccel vaapi -hwaccel_device {device_path} -hwaccel_output_format vaapi '
              '-i "{video_path}" -ss {frames} -frames:v 1 -c:v mjpeg_vaapi -f "{image_path}"'
    else:
        # CPU 路径
        cmd = 'ffmpeg -i "{video_path}" -ss {frames} -vframes 1 -f image2 "{image_path}"'
```

### 1.3 问题清单

| # | 问题 | 影响 | 严重度 |
|---|------|------|--------|
| 1 | **GPU 路径 `-f "{image_path}"` bug** | `-f` 是格式参数，不是输出文件路径。正确写法是 `-f image2 "{image_path}"` 或不用 `-f` 直接写输出路径。当前命令会报错，**Intel GPU 路径完全不可用** | 严重 |
| 2 | **无 HDR/DV 检测** | HDR/DV 视频直接截图，生成的缩略图色偏/过曝（如杜比视界 Profile 7 的双层 BL+EL+RPU） | 严重 |
| 3 | **仅支持 Intel GPU** | 只检测 `/dev/dri/renderD128`，不支持 NVIDIA CUDA、AMD VAAPI | 中等 |
| 4 | **字符串拼接命令** | `cmd = 'ffmpeg -i "..."'.format()` 方式存在命令注入风险，文件名含特殊字符（`$`、`;`、反引号等）会导致安全问题 | 中等 |
| 5 | **无 fallback 逻辑** | GPU 命令失败后不会 fallback 到 CPU，直接返回失败 | 低 |
| 6 | **`-ss` 在 `-i` 之后** | 先解码再 seek，效率低。应改为 `-ss` 在 `-i` 之前（input seeking，跳读） | 低 |

### 1.4 Docker 环境

Docker 镜像基于 `alpine:latest`，`package_list.txt` 中包含 `ffmpeg`、`intel-media-driver`、`libva-dev`、`libva-utils`。

Alpine edge 仓库中 ffmpeg 版本为 **8.1.1**（2026-05-04），支持 zscale/tonemap/vaapi 等滤镜。

本机当前无 ffmpeg/ffprobe（venv 中未安装，系统也未安装），需要确认 Docker 镜像中 ffmpeg 的编译选项。

---

## 二、解决方案

### 2.1 整体架构

```
get_thumb_image_from_video(video_path, image_path, frames)
    │
    ├─ 1. ffprobe 检测视频 HDR 类型
    │      ├─ HDR10/PQ → 2a: PQ tone-mapping 路径
    │      ├─ HLG      → 2a: HLG tone-mapping 路径
    │      ├─ DV       → 2a: DV tone-mapping 路径（剥离 RPU 后按 PQ 处理）
    │      ├─ 未知/检测失败 → 2c: degraded 模式（记录 warning）
    │      └─ SDR      → 2b: SDR 路径
    │
    ├─ 2a. HDR 路径（根据 HDR 类型选择滤镜链）
    │      ├─ GPU 可用 → GPU 解码 → hwdownload(p010le 10-bit) → CPU zscale/tonemap → JPEG
    │      └─ GPU 不可用 → CPU 解码 → CPU zscale/tonemap → JPEG
    │
    ├─ 2b. SDR 路径
    │      ├─ GPU 可用 → GPU 硬解码 + 硬编码输出 → JPEG（最快）
    │      └─ GPU 不可用 → CPU 解码 → JPEG
    │
    ├─ 2c. 检测失败降级
    │      ├─ 走 SDR 路径 + 记录 warning 日志
    │      └─ 如果配置项 force_tonemap_unknown=true → 走 HDR 路径（保守策略）
    │
    └─ 3. fallback：GPU 路径失败 → 自动降级到 CPU 路径重试
           所有路径完成后验证输出文件存在且 size > 0
```

### 2.2 HDR/DV 检测策略

通过 `ffprobe` 读取视频流的 `color_transfer`、`color_primaries`、`color_space` 以及 `side_data_list`，**区分 HDR10/PQ、HLG、DV 三种类型**，返回枚举值：

```python
class HdrType(Enum):
    SDR = "sdr"
    HDR10_PQ = "hdr10_pq"       # PQ / SMPTE 2084
    HLG = "hlg"                 # HLG / ARIB STD-B67
    DOLBY_VISION = "dolby_vision"
    UNKNOWN = "unknown"         # 检测失败
```

```python
@staticmethod
def detect_hdr_type(video_path):
    """
    检测视频 HDR 类型，返回 HdrType 枚举。
    UNKNOWN 表示检测失败（ffprobe 不可用或无元数据）。
    """
    metadata = FfmpegHelper.get_video_metadata(video_path)
    if not metadata:
        return HdrType.UNKNOWN

    for stream in metadata.get("streams", []):
        if stream.get("codec_type") != "video":
            continue

        color_transfer = stream.get("color_transfer", "")

        # 杜比视界优先检测（side_data_list 中包含 DOVI 配置）
        for side_data in stream.get("side_data_list", []):
            side_data_type = side_data.get("side_data_type", "")
            if "DOVI" in side_data_type or "dolby" in side_data_type.lower():
                return HdrType.DOLBY_VISION

        # HDR10 / PQ
        if color_transfer == "smpte2084":
            return HdrType.HDR10_PQ

        # HLG（含 HDRVivid 基础层，CUVA HDR 通常基于 HLG 或 PQ）
        if color_transfer == "arib-std-b67":
            return HdrType.HLG

        # 有视频流但 color_transfer 缺失 — 无法判断，返回 UNKNOWN
        if not color_transfer:
            return HdrType.UNKNOWN

    return HdrType.SDR
```

**注意**：`ffprobe` 输出 `side_data_list` 需要 ffmpeg 5.0+。Alpine edge 仓库的 ffmpeg 8.1.1 满足要求。

#### 检测失败的降级策略

`HdrType.UNKNOWN`（ffprobe 不可用或无元数据）时不简单按 SDR 处理，而是：

1. **默认行为**：走 SDR 路径 + 记录 `warning` 日志（`"视频 HDR 检测失败，按 SDR 处理，可能存在色偏"`）
2. **可选配置**：在 `config.yaml` 中增加 `force_tonemap_unknown: true`，对未知视频强制走 HDR tone-mapping 路径。注意：SDR 视频走 tone-mapping 可能导致颜色偏淡/过曝，仅在对大量视频色偏无把握时启用

```yaml
# app 配置中新增
force_tonemap_unknown: false
```

#### HDRVivid（CUVA HDR）特殊处理

HDRVivid 是中国超高清视频产业联盟（CUVA）制定的 HDR 标准，常见于国产影视内容。其实现通常基于 HLG 或 PQ 作为底层传递函数，并附加动态元数据。

**检测方式**：
- ffprobe 通常不输出专门的 "HDRVivid" 标识，而是通过 `color_transfer` 字段体现底层传递函数
- 常见值：`arib-std-b67`（HLG 基础）或 `smpte2084`（PQ 基础）
- 部分文件可能在 `tags` 中包含 `HDRVivid` 或 `CUVA` 字符串

**处理策略**：
- 如果 `color_transfer == "arib-std-b67"` → 按 HLG 处理（`tin=arib-std-b67` 滤镜链）
- 如果 `color_transfer == "smpte2084"` → 按 HDR10/PQ 处理（`tin=smpte2084` 滤镜链）
- 如果检测到 `tags` 中有 HDRVivid 标识但 `color_transfer` 缺失 → 返回 UNKNOWN，由 `force_tonemap_unknown` 决定降级策略

**测试文件 3**（Lady.Liberty）标注为 HDRVivid，开发前需用 ffprobe 确认其实际 `color_transfer` 值，以验证上述检测逻辑。

### 2.3 HDR Tone-mapping 滤镜链

**关键设计原则**：显式声明输入色彩空间参数（`tin`/`pin`/`min`），避免依赖 ffmpeg 自动检测（元数据缺失时会默认为 SDR，导致滤镜链不执行或结果错误）。

#### PQ (HDR10) 滤镜链

输入假设：`transfer=smpte2084, primaries=bt2020, matrix=bt2020nc`

```
zscale=tin=smpte2084:pin=bt2020:min=bt2020nc:t=linear:npl=100,
format=gbrpf32le,
zscale=p=bt709,
tonemap=hable,
zscale=t=bt709:m=bt709:r=tv,
format=yuv420p
```

#### HLG 滤镜链

输入假设：`transfer=arib-std-b67, primaries=bt2020, matrix=bt2020nc`

```
zscale=tin=arib-std-b67:pin=bt2020:min=bt2020nc:t=linear:npl=100,
format=gbrpf32le,
zscale=p=bt709,
tonemap=hable,
zscale=t=bt709:m=bt709:r=tv,
format=yuv420p
```

#### 杜比视界滤镜链

DV Profile 7 为双层结构（BL + EL + RPU），ffmpeg 硬件解码时可能融合 BL+EL（取决于驱动和 ffmpeg 版本），RPU 动态元数据通常被忽略。融合后的视频按 PQ 处理：

```
zscale=tin=smpte2084:pin=bt2020:min=bt2020nc:t=linear:npl=100,
format=gbrpf32le,
zscale=p=bt709,
tonemap=hable,
zscale=t=bt709:m=bt709:r=tv,
format=yuv420p
```

**说明**：DV Profile 5（单层 IPTPQc2）在 ffmpeg 中可能不被完整支持，此时 ffprobe 不输出 DOVI side_data，会降级到 PQ 或 SDR 处理。

#### 滤镜链选择逻辑

```python
def _get_tonemap_filter(hdr_type):
    """根据 HDR 类型返回对应的 tone-mapping 滤镜链"""
    if hdr_type == HdrType.HDR10_PQ or hdr_type == HdrType.DOLBY_VISION:
        # PQ / DV: tin=smpte2084, pin=bt2020, min=bt2020nc
        return (
            "zscale=tin=smpte2084:pin=bt2020:min=bt2020nc:t=linear:npl=100,"
            "format=gbrpf32le,zscale=p=bt709,tonemap=hable,"
            "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
        )
    elif hdr_type == HdrType.HLG:
        # HLG: tin=arib-std-b67, pin=bt2020, min=bt2020nc
        return (
            "zscale=tin=arib-std-b67:pin=bt2020:min=bt2020nc:t=linear:npl=100,"
            "format=gbrpf32le,zscale=p=bt709,tonemap=hable,"
            "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
        )
    else:
        # SDR 或未知：不做 tone-mapping
        return None
```

### 2.4 GPU HDR 路径：保留 10-bit 精度

**问题**：原方案在 `hwdownload` 前用 `scale_vaapi=format=nv12` 将 10-bit HDR 压成 8-bit NV12，会损失高光和色彩精度，加重 banding。

**修复**：优先使用 `p010le`（10-bit）格式从 VAAPI 下载到 CPU：

```
# GPU HDR 路径滤镜链（保留 10-bit）
scale_vaapi=format=p010,hwdownload,format=p010le,
zscale=tin=smpte2084:pin=bt2020:min=bt2020nc:t=linear:npl=100,
format=gbrpf32le,zscale=p=bt709,tonemap=hable,
zscale=t=bt709:m=bt709:r=tv,format=yuv420p
```

**兼容性处理**：如果 `scale_vaapi=format=p010` 不被支持（旧版 ffmpeg 或驱动），fallback 到 `nv12` 8-bit 路径并记录 warning。实现方式：先尝试 p010 路径，如果 ffmpeg 返回非零退出码，自动降级到 nv12 路径重试。

### 2.5 GPU 检测策略

采用 **ffmpeg 能力自检 + 设备文件检测 + 驱动验证** 策略：

```python
class GpuType(Enum):
    NONE = "none"
    VAAPI = "vaapi"           # 通用 VAAPI（Intel 或 AMD）
    NVIDIA_CUDA = "nvidia_cuda"  # 预留，暂不主动检测
```

**关键改动**：不再把 VAAPI 设为 `INTEL_VAAPI`，改为通用的 `VAAPI`。Intel 和 AMD 共享 `/dev/dri/renderD128`，在无 `vainfo` 或驱动名检测的情况下无法区分，也不需要区分——两者的 ffmpeg 命令参数相同。

```python
@staticmethod
def detect_gpu_type():
    """
    检测 GPU 类型，返回 GpuType 枚举。
    VAAPI 检测：ffmpeg 支持 vaapi + 设备文件存在。
    额外验证：尝试 vaapi 初始化，失败则缓存结果避免重复检测。
    """
    hwaccels = FfmpegHelper._get_ffmpeg_hwaccels()
    if "vaapi" in hwaccels and os.path.exists("/dev/dri/renderD128"):
        # 可选：通过 vainfo 或 ffmpeg 试初始化验证驱动可用
        # 简化方案：信任设备文件存在 + ffmpeg 报告的 hwaccel 支持
        # 如果后续 vaapi 调用失败，fallback 逻辑会兜底
        return GpuType.VAAPI
    # NVIDIA 预留（暂不主动检测）
    # if "cuda" in hwaccels and os.path.exists("/dev/nvidia0"):
    #     return GpuType.NVIDIA_CUDA
    return GpuType.NONE
```

**Fallback 日志**：GPU 路径失败时记录 `warning` 日志（含 stderr），便于排查是驱动问题还是文件问题：

```python
log.warn(f"【FfmpegHelper】GPU 路径失败，降级到 CPU：{stderr_output}")
```

**检测结果缓存**：首次检测后缓存结果到类变量，避免每次调用都执行 `ffmpeg -hwaccels`：

```python
_gpu_type_cache = None

@staticmethod
def detect_gpu_type():
    if FfmpegHelper._gpu_type_cache is not None:
        return FfmpegHelper._gpu_type_cache
    # ... 检测逻辑 ...
    FfmpegHelper._gpu_type_cache = result
    return result
```

### 2.6 命令构建与执行

**命令构建**：所有 ffmpeg 命令统一使用 **subprocess list** 形式，命令构建和执行拆开，便于单元测试：

```python
@staticmethod
def _build_sdr_cpu_cmd(video_path, image_path, frames):
    """构建 SDR CPU 截图命令（可单元测试）"""
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-ss", frames,
        "-i", video_path,
        "-vframes", "1",
        "-f", "image2",
        "-y", image_path
    ]
```

**命令执行**：封装 `_run_ffmpeg()` 方法，处理异常、超时、stderr 日志：

```python
@staticmethod
def _run_ffmpeg(cmd, timeout=120):
    """
    执行 ffmpeg 命令，捕获异常和超时，记录 stderr。
    返回 (success: bool, stderr: str)
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            # 额外验证：输出文件存在且大小 > 0
            if os.path.exists(cmd[-1]) and os.path.getsize(cmd[-1]) > 0:
                return True, ""
            else:
                log.warn(f"【FfmpegHelper】ffmpeg 返回 0 但输出文件无效：{cmd[-1]}")
                return False, "output file missing or empty"
        else:
            return False, result.stderr
    except FileNotFoundError:
        log.warn("【FfmpegHelper】ffmpeg/ffprobe 未安装或不在 PATH 中")
        return False, "ffmpeg not found"
    except subprocess.TimeoutExpired:
        log.warn(f"【FfmpegHelper】ffmpeg 执行超时（{timeout}s）：{' '.join(cmd[:5])}...")
        return False, "timeout"
    except Exception as e:
        log.warn(f"【FfmpegHelper】ffmpeg 执行异常：{str(e)}")
        return False, str(e)
```

**移除 `SystemUtils` 导入**：重构后不再使用 `SystemUtils.execute()`，从 import 中移除。

### 2.7 四条执行路径

#### 路径 A：SDR + GPU（纯 GPU，最快）

```python
# VAAPI（Intel/AMD 通用）
cmd = [
    "ffmpeg", "-hide_banner", "-loglevel", "warning",
    "-hwaccel", "vaapi",
    "-hwaccel_device", device_path,
    "-hwaccel_output_format", "vaapi",
    "-ss", frames,                     # input seeking（跳读，高效）
    "-i", video_path,
    "-frames:v", "1",
    "-c:v", "mjpeg_vaapi",             # GPU 编码输出 JPEG
    "-y", image_path                   # 输出文件（不用 -f，直接写路径）
]
```

#### 路径 B：SDR + CPU

```python
cmd = [
    "ffmpeg", "-hide_banner", "-loglevel", "warning",
    "-ss", frames,                     # input seeking
    "-i", video_path,
    "-vframes", "1",
    "-f", "image2",
    "-y", image_path
]
```

#### 路径 C：HDR/DV + GPU（混合模式：GPU 解码 + CPU tone-mapping，10-bit 优先）

```python
# 优先 p010le（10-bit），失败后 fallback 到 nv12（8-bit）
cmd = [
    "ffmpeg", "-hide_banner", "-loglevel", "warning",
    "-hwaccel", "vaapi",
    "-hwaccel_device", device_path,
    "-hwaccel_output_format", "vaapi",
    "-ss", frames,
    "-i", video_path,
    "-frames:v", "1",
    "-vf", f"scale_vaapi=format=p010,hwdownload,format=p010le,{tonemap_filter}",
    "-f", "image2",
    "-y", image_path
]
# 如果 p010 失败，fallback 到 nv12 路径：
cmd_nv12 = [
    "ffmpeg", "-hide_banner", "-loglevel", "warning",
    "-hwaccel", "vaapi",
    "-hwaccel_device", device_path,
    "-hwaccel_output_format", "vaapi",
    "-ss", frames,
    "-i", video_path,
    "-frames:v", "1",
    "-vf", f"scale_vaapi=format=nv12,hwdownload,format=nv12,{tonemap_filter}",
    "-f", "image2",
    "-y", image_path
]
```

#### 路径 D：HDR/DV + CPU（纯 CPU tone-mapping）

```python
cmd = [
    "ffmpeg", "-hide_banner", "-loglevel", "warning",
    "-ss", frames,
    "-i", video_path,
    "-vframes", "1",
    "-vf", tonemap_filter,             # 根据 HDR 类型选择
    "-f", "image2",
    "-y", image_path
]
```

### 2.8 Fallback 逻辑

```
尝试 GPU 路径 → 失败？
  ├─ 是 → 记录 warning 日志（含 stderr）
  │       ├─ HDR 场景：先尝试 p010 → 失败则 nv12 → 失败则纯 CPU
  │       └─ SDR 场景：直接 fallback 到 CPU
  └─ 否 → 验证输出文件存在且 size > 0
          ├─ 是 → 返回成功
          └─ 否 → fallback 到 CPU 重试
```

### 2.9 `-ss` 位置策略

- **默认**：`-ss` 在 `-i` 之前（input seeking），高效但可能不精确
- **Fallback**：如果 input seeking 截图结果异常（输出文件为空或 ffmpeg 报错），自动用 `-ss` 在 `-i` 之后（output seeking）重试
- **说明**：input seeking 对 MKV/MP4 精度足够；对 TS 流容器可能存在关键帧偏差，但本场景是生成缩略图，轻微偏差可接受

### 2.10 Docker 镜像修改

**方案**：基础镜像改为 `alpine:edge`，统一从 edge 仓库安装所有包，避免混用 stable + edge 带来 ABI 风险。

```dockerfile
# 修改前
FROM alpine:latest AS Builder

# 修改后
FROM alpine:edge AS Builder
```

**优势**：
- 所有包版本一致，无 ABI 兼容性问题
- ffmpeg 8.1.1 自带 zscale/tonemap/hwdownload 滤镜
- 简单直接，无需 `--repository` 覆盖

**风险**：`alpine:edge` 是滚动更新，偶尔可能有包不兼容。如果 Dockerfile 使用多阶段构建（Builder + Runtime），两个阶段都需使用 `alpine:edge`，否则 Runtime 阶段的 ffmpeg 版本可能与 Builder 不一致。构建时通过固定镜像 digest 可减小滚动更新风险。

**验证清单**（构建后需确认）：

```bash
# 在 Docker 容器中执行
ffmpeg -version                      # 确认版本 >= 6.0
ffmpeg -filters 2>&1 | grep zscale   # 确认 zscale 滤镜可用
ffmpeg -filters 2>&1 | grep tonemap  # 确认 tonemap 滤镜可用
ffmpeg -filters 2>&1 | grep hwdownload  # 确认 hwdownload 可用
ffmpeg -hwaccels 2>&1 | grep vaapi   # 确认 vaapi 硬件加速
```

如果 edge 的 ffmpeg 缺少 zscale（未编译 `--enable-libzimg`），备选方案为在 `package_list.txt` 中添加 `zimg` 包，或从 `jrottenberg/ffmpeg` 镜像拷贝 ffmpeg 二进制。

---

## 三、代码改动

### 3.1 `app/helper/ffmpeg_helper.py` — 整体重构

#### 3.1.1 新增枚举和常量

```python
import json
import log
import os
import subprocess
from enum import Enum

from config import Config


class GpuType(Enum):
    """GPU 类型枚举"""
    NONE = "none"
    VAAPI = "vaapi"                  # 通用 VAAPI（Intel 或 AMD）
    NVIDIA_CUDA = "nvidia_cuda"      # 预留，暂不主动检测


class HdrType(Enum):
    """视频 HDR 类型枚举"""
    SDR = "sdr"
    HDR10_PQ = "hdr10_pq"           # PQ / SMPTE 2084
    HLG = "hlg"                     # HLG / ARIB STD-B67
    DOLBY_VISION = "dolby_vision"   # 杜比视界
    UNKNOWN = "unknown"             # 检测失败


# GPU 设备路径映射
GPU_DEVICE_PATHS = {
    GpuType.VAAPI: "/dev/dri/renderD128",
    GpuType.NVIDIA_CUDA: "/dev/nvidia0",
}

# HDR10/PQ/DV tone-mapping 滤镜链（CPU 侧）
# 显式声明输入色彩空间：tin=smpte2084, pin=bt2020, min=bt2020nc
HDR10_TONEMAP_FILTER = (
    "zscale=tin=smpte2084:pin=bt2020:min=bt2020nc:t=linear:npl=100,"
    "format=gbrpf32le,zscale=p=bt709,tonemap=hable,"
    "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)

# HLG tone-mapping 滤镜链（CPU 侧）
# 显式声明输入色彩空间：tin=arib-std-b67, pin=bt2020, min=bt2020nc
HLG_TONEMAP_FILTER = (
    "zscale=tin=arib-std-b67:pin=bt2020:min=bt2020nc:t=linear:npl=100,"
    "format=gbrpf32le,zscale=p=bt709,tonemap=hable,"
    "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)
```

#### 3.1.2 GPU 检测方法（含缓存）

```python
class FfmpegHelper:
    _gpu_type_cache = None

    @staticmethod
    def detect_gpu_type():
        """
        检测 GPU 类型，返回 GpuType 枚举。结果缓存到类变量。
        """
        if FfmpegHelper._gpu_type_cache is not None:
            return FfmpegHelper._gpu_type_cache

        hwaccels = FfmpegHelper._get_ffmpeg_hwaccels()
        if "vaapi" in hwaccels and os.path.exists(GPU_DEVICE_PATHS[GpuType.VAAPI]):
            FfmpegHelper._gpu_type_cache = GpuType.VAAPI
            return GpuType.VAAPI

        # NVIDIA 预留
        # if "cuda" in hwaccels and os.path.exists(GPU_DEVICE_PATHS[GpuType.NVIDIA_CUDA]):
        #     FfmpegHelper._gpu_type_cache = GpuType.NVIDIA_CUDA
        #     return GpuType.NVIDIA_CUDA

        FfmpegHelper._gpu_type_cache = GpuType.NONE
        return GpuType.NONE

    @staticmethod
    def _get_ffmpeg_hwaccels():
        """获取 ffmpeg 支持的硬件加速列表"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-hwaccels"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return [line.strip() for line in result.stdout.strip().split('\n')[1:] if line.strip()]
        except Exception:
            pass
        return []
```

#### 3.1.3 HDR 检测方法

见 2.2 节 `detect_hdr_type()` 代码。

#### 3.1.4 命令执行封装

见 2.6 节 `_run_ffmpeg()` 代码。

#### 3.1.5 滤镜链选择

见 2.3 节 `_get_tonemap_filter()` 代码。

#### 3.1.6 重构 `get_thumb_image_from_video`

```python
@staticmethod
def get_thumb_image_from_video(video_path, image_path, frames="00:03:01"):
    """
    使用 ffmpeg 从视频文件中截取缩略图。
    自动检测 HDR/DV 类型和 GPU 类型，选择最优路径。
    GPU 路径失败时自动 fallback 到 CPU。
    """
    if not video_path or not image_path:
        return False

    gpu_type = FfmpegHelper.detect_gpu_type()
    hdr_type = FfmpegHelper.detect_hdr_type(video_path)
    force_tonemap = Config().get_config('app').get('force_tonemap_unknown', False)

    # 检测失败的降级处理
    if hdr_type == HdrType.UNKNOWN:
        if force_tonemap:
            log.warn(f"【FfmpegHelper】视频 HDR 检测失败，配置 force_tonemap_unknown=true，按 HDR10 处理")
            hdr_type = HdrType.HDR10_PQ
        else:
            log.warn(f"【FfmpegHelper】视频 HDR 检测失败，按 SDR 处理，如存在色偏请启用 force_tonemap_unknown")

    tonemap_filter = FfmpegHelper._get_tonemap_filter(hdr_type)
    is_hdr = tonemap_filter is not None

    # 选择路径
    if is_hdr and gpu_type != GpuType.NONE:
        # 路径 C：HDR + GPU（p010 优先 → nv12 fallback → 纯 CPU fallback）
        return FfmpegHelper._gen_thumb_with_hdr_gpu_fallback(
            video_path, image_path, frames, gpu_type, tonemap_filter)
    elif is_hdr:
        # 路径 D：HDR + CPU
        return FfmpegHelper._gen_thumb_hdr_cpu(video_path, image_path, frames, tonemap_filter)
    elif gpu_type != GpuType.NONE:
        # 路径 A：SDR + GPU
        success, stderr = FfmpegHelper._run_ffmpeg(
            FfmpegHelper._build_sdr_gpu_cmd(video_path, image_path, frames, gpu_type))
        if success:
            return True
        log.warn(f"【FfmpegHelper】GPU 路径失败，降级到 CPU：{stderr}")
        # Fallback：SDR + CPU
        return FfmpegHelper._gen_thumb_sdr_cpu(video_path, image_path, frames)
    else:
        # 路径 B：SDR + CPU
        return FfmpegHelper._gen_thumb_sdr_cpu(video_path, image_path, frames)
```

#### 3.1.7 HDR GPU 路径的多级 fallback

```python
@staticmethod
def _gen_thumb_with_hdr_gpu_fallback(video_path, image_path, frames, gpu_type, tonemap_filter):
    """
    HDR + GPU 路径，多级 fallback：
    1. p010le (10-bit) 优先
    2. nv12 (8-bit) 降级
    3. 纯 CPU 最终兜底
    """
    # 尝试 p010le（保留 10-bit 精度）
    cmd = FfmpegHelper._build_hdr_gpu_cmd(video_path, image_path, frames, gpu_type, tonemap_filter, use_p010=True)
    success, stderr = FfmpegHelper._run_ffmpeg(cmd)
    if success:
        return True

    log.warn(f"【FfmpegHelper】HDR GPU (p010) 失败，尝试 nv12：{stderr}")

    # 尝试 nv12（8-bit 降级）
    cmd = FfmpegHelper._build_hdr_gpu_cmd(video_path, image_path, frames, gpu_type, tonemap_filter, use_p010=False)
    success, stderr = FfmpegHelper._run_ffmpeg(cmd)
    if success:
        return True

    log.warn(f"【FfmpegHelper】HDR GPU (nv12) 失败，降级到 CPU：{stderr}")

    # 最终兜底：纯 CPU
    return FfmpegHelper._gen_thumb_hdr_cpu(video_path, image_path, frames, tonemap_filter)
```

#### 3.1.8 命令构建方法（可单元测试）

所有 `_build_*_cmd` 方法仅构建命令列表，不执行：

```python
@staticmethod
def _build_sdr_cpu_cmd(video_path, image_path, frames):
    """构建 SDR CPU 截图命令"""
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-ss", frames, "-i", video_path,
        "-vframes", "1", "-f", "image2", "-y", image_path
    ]

@staticmethod
def _build_sdr_gpu_cmd(video_path, image_path, frames, gpu_type):
    """构建 SDR GPU 截图命令"""
    device_path = GPU_DEVICE_PATHS.get(gpu_type)
    if gpu_type == GpuType.VAAPI:
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-hwaccel", "vaapi", "-hwaccel_device", device_path,
            "-hwaccel_output_format", "vaapi",
            "-ss", frames, "-i", video_path,
            "-frames:v", "1", "-c:v", "mjpeg_vaapi", "-y", image_path
        ]
    elif gpu_type == GpuType.NVIDIA_CUDA:
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-hwaccel", "cuda",
            "-ss", frames, "-i", video_path,
            "-frames:v", "1", "-c:v", "mjpeg", "-y", image_path
        ]
    return None

@staticmethod
def _build_hdr_cpu_cmd(video_path, image_path, frames, tonemap_filter):
    """构建 HDR CPU 截图命令"""
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-ss", frames, "-i", video_path,
        "-vframes", "1", "-vf", tonemap_filter,
        "-f", "image2", "-y", image_path
    ]

@staticmethod
def _build_hdr_gpu_cmd(video_path, image_path, frames, gpu_type, tonemap_filter, use_p010=True):
    """构建 HDR GPU 截图命令（p010 或 nv12）"""
    device_path = GPU_DEVICE_PATHS.get(gpu_type)
    if gpu_type == GpuType.VAAPI:
        pixel_fmt = "p010" if use_p010 else "nv12"
        dl_fmt = "p010le" if use_p010 else "nv12"
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-hwaccel", "vaapi", "-hwaccel_device", device_path,
            "-hwaccel_output_format", "vaapi",
            "-ss", frames, "-i", video_path,
            "-frames:v", "1",
            "-vf", f"scale_vaapi=format={pixel_fmt},hwdownload,format={dl_fmt},{tonemap_filter}",
            "-f", "image2", "-y", image_path
        ]
    elif gpu_type == GpuType.NVIDIA_CUDA:
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-hwaccel", "cuda",
            "-ss", frames, "-i", video_path,
            "-frames:v", "1",
            "-vf", f"hwdownload,format=nv12,{tonemap_filter}",
            "-f", "image2", "-y", image_path
        ]
    return None
```

#### 3.1.9 保留现有方法（兼容）

`get_video_metadata()`、`extract_wav_from_video()`、`extract_subtitle_from_video()` 保持不变。

`intel_gpu_exist_check()` 和 `get_intel_gpu_device_path()` 标记为 deprecated：

```python
@staticmethod
def get_intel_gpu_device_path():
    """deprecated: 使用 detect_gpu_type() 替代"""
    return "/dev/dri/renderD128"

@staticmethod
def intel_gpu_exist_check():
    """deprecated: 使用 detect_gpu_type() 替代"""
    device_path = FfmpegHelper().get_intel_gpu_device_path()
    return os.path.exists(device_path)
```

### 3.2 `docker/Dockerfile` — 基础镜像改为 alpine:edge

```dockerfile
# 修改前
FROM alpine:latest AS Builder

# 修改后
FROM alpine:edge AS Builder
```

统一从 edge 仓库安装所有包（包括 ffmpeg 8.1.1），避免混用 stable + edge 的 ABI 风险。

### 3.3 `config/config.yaml` — 新增配置项

```yaml
app:
  # ... existing config ...
  # 对 HDR 检测失败的视频强制走 tone-mapping 路径（保守策略，避免色偏）
  force_tonemap_unknown: false
```

---

## 四、文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `app/helper/ffmpeg_helper.py` | 整体重构 | 新增 GpuType/HdrType 枚举、detect_gpu_type()（含缓存）、detect_hdr_type()、_get_tonemap_filter()、_run_ffmpeg()（异常/超时/stderr）、_build_*_cmd()（可测试）；重构 get_thumb_image_from_video() 为四路径 + 多级 fallback；所有命令改为 subprocess list；移除 SystemUtils 导入；deprecated 旧方法 |
| `docker/Dockerfile` | 1 行 | 基础镜像从 `alpine:latest` 改为 `alpine:edge` |
| `config/config.yaml` | +2 行 | 新增 `force_tonemap_unknown: false` 配置项 |
| `app/media/scraper.py` | 无改动 | 调用接口不变，仍是 `FfmpegHelper().get_thumb_image_from_video(video_path, image_path)` |

---

## 五、验证方式

### 5.1 测试文件

| # | 类型 | 文件路径 | 说明 |
|---|------|---------|------|
| 1 | **杜比视界 (DV)** | `/mnt/nas23_video5/movie/Bad.Boys.Ride.or.Die.2024.UHD.Blu-ray.2160p.10bit.DoVi.2Audio.TrueHD(Atmos).7.1.x265-beAst/Bad.Boys.Ride.or.Die.2024.UHD.Blu-ray.2160p.10bit.DoVi.2Audio.TrueHD(Atmos).7.1.x265-beAst.mkv` | DV Profile 7 双层，4K 10bit，TrueHD Atmos |
| 2 | **杜比视界 (DV)** | `/mnt/nas23_video5/movie/加勒比海盗3：世界的尽头.Pirates.of.the.Caribbean.At.Worlds.End.2007.UHD.BluRay.2160p.x265.10bit.DoVi.2Audios.mUHD-FRDS/Pirates.of.the.Caribbean.At.Worlds.End.2007.UHD.BluRay.2160p.x265.10bit.DoVi.2Audios.mUHD-FRDS.mkv` | DV Profile 7 双层，4K 10bit，文件名含中文和特殊字符 |
| 3 | **HDR Vivid** | `/mnt/nas23_video/tv/[爱情没有神话].Lady.Liberty.2026.S01.Complete.2160p.WEB-DL.60Fps.HDRVivid.H265.10bit.AAC-UBWEB/[爱情没有神话].Lady.Liberty.2026.S01E01.2160p.WEB-DL.60Fps.HDRVivid.H265.10bit.AAC-UBWEB.mkv` | HDR Vivid（国产 HDR 标准），4K 10bit 60fps，文件名含中文和方括号 |
| 4 | **SDR 1080p** | `/mnt/nas23_video/tv/[努力克服自卑的我们].We.Are.All.Trying.Here.2026.S01.Complete.1080p.NF.WEB-DL.H264.AAC-UBWEB/[努力克服自卑的我们].We.Are.All.Trying.Here.2026.S01E01.1080p.NF.WEB-DL.H264.AAC-UBWEB.mkv` | SDR 1080p H264，普通视频基准 |
| 5 | **SDR 4K** | `/mnt/nas23_video5/tv/Delightfully.Deceitful.2023.S01.Complete.2160p.WEB-DL.H265.DDP5.1-HHWEB/Delightfully.Deceitful.2023.S01E01.2160p.WEB-DL.H265.DDP5.1-HHWEB.mkv` | SDR 4K H265，验证 4K SDR 在 GPU/CPU 路径下的表现 |

**特别说明**：
- 测试文件 2、3、5 的文件名包含中文、方括号 `[]`、点号等特殊字符，可验证 subprocess list 的安全性
- 测试文件 3 标注为 HDRVivid，这是国内 HDR 标准（CUVA HDR，通常基于 HLG 或 PQ），ffprobe 输出的 color_transfer 需要实际确认
- 开发前应先用 `ffprobe -show_streams -show_data` 查看每个测试文件的元数据，确认 color_transfer 和 side_data_list 的实际值

### 5.2 验证项目

1. **SDR 1080p + VAAPI GPU**：用测试文件 4，生成缩略图正确，命令走路径 A（纯 GPU）
2. **SDR 1080p + 无 GPU**：用测试文件 4，生成缩略图正确，命令走路径 B（CPU）
3. **SDR 4K + VAAPI GPU**：用测试文件 5，验证 4K SDR 在 GPU 路径下是否正常（路径 A）
4. **SDR 4K + 无 GPU**：用测试文件 5，验证 4K SDR 在 CPU 路径下是否正常（路径 B）
5. **HDR10/PQ 视频 + VAAPI GPU**：生成缩略图无色偏，命令走路径 C（GPU 解码 p010 → CPU tone-mapping）
6. **HDR10/PQ 视频 + 无 GPU**：生成缩略图无色偏，命令走路径 D（CPU tone-mapping）
7. **HLG 视频**：用测试文件 3（如确认为 HLG），滤镜链使用 `tin=arib-std-b67` 参数，生成缩略图无色偏
8. **HDRVivid 视频**：用测试文件 3，确认 ffprobe 检测到的底层传递函数（HLG 或 PQ），对应滤镜链正确处理
9. **杜比视界 Profile 7 视频**：用测试文件 1 和 2，ffprobe 检测 DOVI side_data，按 PQ 滤镜链处理，缩略图无色偏
10. **GPU 路径失败 fallback**：故意指定错误的 device_path → 自动降级到 CPU 路径
11. **HDR GPU p010 失败 → nv12 fallback**：在旧驱动环境测试 p010 不支持时自动降级
12. **文件名特殊字符**：用测试文件 2/3/4/5 验证文件名含中文、方括号等字符时，subprocess list 正确处理
13. **输出文件验证**：ffmpeg 返回 0 但输出文件不存在或为空时，正确判断为失败
14. **ffprobe 不存在时**：`detect_hdr_type()` 返回 UNKNOWN，记录 warning 日志，按 SDR 处理；如启用 `force_tonemap_unknown` 则按 HDR10 处理
15. **ffmpeg 超时**：大文件或网络盘卡住时，120s 超时后返回失败
16. **Docker 环境验证**：在容器中确认 `ffmpeg -filters` 包含 zscale/tonemap/hwdownload
17. **杜比视界 Profile 5**（如果 ffmpeg 不识别）：降级到 PQ 或 SDR 处理，记录 warning

### 单元测试覆盖

用 ffprobe JSON fixture 覆盖以下场景：

| fixture | color_transfer | side_data_list | 期望结果 |
|---------|---------------|----------------|---------|
| sdr.mkv | bt709 | 无 | HdrType.SDR |
| hdr10.mkv | smpte2084 | 无 | HdrType.HDR10_PQ |
| hlg.mkv | arib-std-b67 | 无 | HdrType.HLG |
| dv_p7.mkv | smpte2084 | DOVI configuration record | HdrType.DOLBY_VISION |
| no_metadata.mkv | (缺失) | 无 | HdrType.UNKNOWN |

`_build_*_cmd()` 方法可直接断言返回的命令列表内容。

---

## 六、风险与注意事项

1. **ffmpeg 编译选项**：zscale 滤镜依赖 `libzimg`。如果 Alpine edge 的 ffmpeg 未编译此依赖，需要额外安装 `zimg` 包或改用 `tonemap_opencl` 等替代滤镜。**开发前需先在 Docker 容器中验证。**
2. **p010le 兼容性**：`scale_vaapi=format=p010` 需要较新的 Mesa/Intel media-driver。如果不可用，会自动 fallback 到 nv12（8-bit），质量略降但不会失败。
3. **性能**：HDR tone-mapping（特别是 CPU 路径）比简单截图慢很多。对于剧集刮削（一次性批量生成），可以接受。如果未来需要实时生成，可考虑缓存策略。
4. **ffprobe 延迟**：每次生成缩略图前额外执行一次 ffprobe，增加约 0.5-1s 延迟。可通过缓存 video metadata 优化（后续改进）。
5. **NVIDIA 预留**：代码写好但未主动检测，避免在无对应硬件时误判。后续有环境时取消注释即可。
6. **`-ss` 位置**：从 `-i` 之后移到之前（input seeking），大幅提升 seek 效率。对 MKV/MP4 精度足够；对 TS 流可能有偏差，但 fallback 逻辑（输出文件为空时重试）可以兜底。
7. **alpine:edge 稳定性**：edge 是滚动更新，偶尔可能有包不兼容。作为 Builder 阶段镜像，构建时固定即可；如遇问题可回退到 stable + 单独安装 edge ffmpeg。
8. **DV Profile 5**：单层 IPTPQc2 格式在 ffmpeg 中支持不完整，ffprobe 可能不输出 DOVI side_data，会降级到 PQ 或 SDR 处理。
