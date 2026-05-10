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
HDR10_TONEMAP_FILTER = (
    "zscale=tin=smpte2084:pin=bt2020:min=bt2020nc:t=linear:npl=100,"
    "format=gbrpf32le,zscale=p=bt709,tonemap=hable,"
    "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)

# HLG tone-mapping 滤镜链（CPU 侧）
HLG_TONEMAP_FILTER = (
    "zscale=tin=arib-std-b67:pin=bt2020:min=bt2020nc:t=linear:npl=100,"
    "format=gbrpf32le,zscale=p=bt709,tonemap=hable,"
    "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)


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

    @staticmethod
    def detect_hdr_type(video_path):
        """
        检测视频 HDR 类型，返回 HdrType 枚举。
        UNKNOWN 表示检测失败（ffprobe 不可用或无元数据）。
        """
        metadata = FfmpegHelper.get_video_metadata(video_path)
        if not metadata:
            return HdrType.UNKNOWN

        has_video_stream = False
        for stream in metadata.get("streams", []):
            if stream.get("codec_type") != "video":
                continue

            # 跳过 attached picture（封面图等非主视频流）
            if stream.get("codec_name", "").lower() in ("mjpeg", "png", "bmp", "gif"):
                continue

            has_video_stream = True
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

            # 有视频流但 color_transfer 缺失 — 跳过，继续扫描后续视频流
            if not color_transfer:
                continue

            # color_transfer 存在但不是 HDR 标识（如 bt709）— 记为 SDR
            return HdrType.SDR

        # 无视频流（音频/字幕/图片文件）— 无法生成缩略图
        if not has_video_stream:
            return HdrType.UNKNOWN

        # 所有视频流均缺少 color_transfer，无法判断
        return HdrType.UNKNOWN

    @staticmethod
    def _get_tonemap_filter(hdr_type):
        """根据 HDR 类型返回对应的 tone-mapping 滤镜链"""
        if hdr_type == HdrType.HDR10_PQ or hdr_type == HdrType.DOLBY_VISION:
            return HDR10_TONEMAP_FILTER
        elif hdr_type == HdrType.HLG:
            return HLG_TONEMAP_FILTER
        else:
            # SDR 或未知：不做 tone-mapping
            return None

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
            # scale_vaapi 缩放到 1080p：mjpeg_vaapi 不支持 4K 编码
            return [
                "ffmpeg", "-hide_banner", "-loglevel", "warning",
                "-hwaccel", "vaapi", "-hwaccel_device", device_path,
                "-hwaccel_output_format", "vaapi",
                "-ss", frames, "-i", video_path,
                "-frames:v", "1", "-update", "1",
                "-vf", "scale_vaapi=w=1920:h=1080:format=nv12",
                "-c:v", "mjpeg_vaapi", "-y", image_path
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

    @staticmethod
    def _gen_thumb_sdr_cpu(video_path, image_path, frames):
        """SDR CPU 截图：构建命令 → 执行 → 返回结果"""
        cmd = FfmpegHelper._build_sdr_cpu_cmd(video_path, image_path, frames)
        success, _ = FfmpegHelper._run_ffmpeg(cmd)
        return success

    @staticmethod
    def _gen_thumb_hdr_cpu(video_path, image_path, frames, tonemap_filter):
        """HDR CPU 截图：构建命令 → 执行 → 返回结果"""
        cmd = FfmpegHelper._build_hdr_cpu_cmd(video_path, image_path, frames, tonemap_filter)
        success, _ = FfmpegHelper._run_ffmpeg(cmd)
        return success

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

    @staticmethod
    def get_thumb_image_from_video(video_path, image_path, frames="00:06:01"):
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

    @staticmethod
    def get_intel_gpu_device_path():
        """deprecated: 使用 detect_gpu_type() 替代"""
        return "/dev/dri/renderD128"

    @staticmethod
    def intel_gpu_exist_check():
        """deprecated: 使用 detect_gpu_type() 替代"""
        device_path = FfmpegHelper().get_intel_gpu_device_path()
        return os.path.exists(device_path)

    @staticmethod
    def get_video_metadata(video_path):
        """
        获取视频元数据
        """
        if not video_path:
            return False

        try:
            command = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', video_path]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if result.returncode == 0:
                return json.loads(result.stdout.decode("utf-8"))
        except subprocess.TimeoutExpired:
            log.warn(f"【FfmpegHelper】ffprobe 执行超时（30s）：{video_path}")
        except Exception as e:
            print(e)
        return None

    @staticmethod
    def extract_wav_from_video(video_path, audio_path, audio_index=None):
        """
        使用ffmpeg从视频文件中提取16000hz, 16-bit的wav格式音频
        """
        if not video_path or not audio_path:
            return False

        # 提取指定音频流
        if audio_index:
            command = ['ffmpeg', "-hide_banner", "-loglevel", "warning", '-y', '-i', video_path,
                       '-map', f'0:a:{audio_index}',
                       '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000', audio_path]
        else:
            command = ['ffmpeg', "-hide_banner", "-loglevel", "warning", '-y', '-i', video_path,
                       '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000', audio_path]

        ret = subprocess.run(command).returncode
        if ret == 0:
            return True
        return False

    @staticmethod
    def extract_subtitle_from_video(video_path, subtitle_path, subtitle_index=None):
        """
        从视频中提取字幕
        """
        if not video_path or not subtitle_path:
            return False

        if subtitle_index:
            command = ['ffmpeg', "-hide_banner", "-loglevel", "warning", '-y', '-i', video_path,
                       '-map', f'0:s:{subtitle_index}',
                       subtitle_path]
        else:
            command = ['ffmpeg', "-hide_banner", "-loglevel", "warning", '-y', '-i', video_path, subtitle_path]
        ret = subprocess.run(command).returncode
        if ret == 0:
            return True
        return False
