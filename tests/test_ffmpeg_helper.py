"""
Unit tests for app/helper/ffmpeg_helper.py — Plan 003

These tests mock the config.Config dependency to avoid needing
the NASTOOL_CONFIG environment variable set.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Mock config.Config before importing the module under test
mock_config_module = MagicMock()
sys.modules['config'] = mock_config_module

from app.helper.ffmpeg_helper import (
    FfmpegHelper, GpuType, HdrType,
    GPU_DEVICE_PATHS, HDR10_TONEMAP_FILTER, HLG_TONEMAP_FILTER,
)


# ── ffprobe JSON fixtures ──────────────────────────────────────────────

FIXTURE_SDR = {
    "streams": [{
        "codec_type": "video",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
        "color_space": "bt709",
    }]
}

FIXTURE_HDR10 = {
    "streams": [{
        "codec_type": "video",
        "color_transfer": "smpte2084",
        "color_primaries": "bt2020",
        "color_space": "bt2020nc",
    }]
}

FIXTURE_HLG = {
    "streams": [{
        "codec_type": "video",
        "color_transfer": "arib-std-b67",
        "color_primaries": "bt2020",
        "color_space": "bt2020nc",
    }]
}

FIXTURE_DV = {
    "streams": [{
        "codec_type": "video",
        "color_transfer": "smpte2084",
        "color_primaries": "bt2020",
        "color_space": "bt2020nc",
        "side_data_list": [{
            "side_data_type": "DOVI configuration record",
        }]
    }]
}

FIXTURE_NO_METADATA = {
    "streams": [{
        "codec_type": "video",
    }]
}

FIXTURE_NO_VIDEO = {
    "streams": [{
        "codec_type": "audio",
        "codec_name": "aac",
    }]
}

FIXTURE_EMPTY = {"streams": []}


# ── Test: HdrType detection ────────────────────────────────────────────

class TestDetectHdrType(unittest.TestCase):

    @patch.object(FfmpegHelper, 'get_video_metadata', return_value=FIXTURE_SDR)
    def test_sdr(self, mock_meta):
        result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
        self.assertEqual(result, HdrType.SDR)

    @patch.object(FfmpegHelper, 'get_video_metadata', return_value=FIXTURE_HDR10)
    def test_hdr10(self, mock_meta):
        result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
        self.assertEqual(result, HdrType.HDR10_PQ)

    @patch.object(FfmpegHelper, 'get_video_metadata', return_value=FIXTURE_HLG)
    def test_hlg(self, mock_meta):
        result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
        self.assertEqual(result, HdrType.HLG)

    @patch.object(FfmpegHelper, 'get_video_metadata', return_value=FIXTURE_DV)
    def test_dolby_vision(self, mock_meta):
        result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
        self.assertEqual(result, HdrType.DOLBY_VISION)

    @patch.object(FfmpegHelper, 'get_video_metadata', return_value=FIXTURE_NO_METADATA)
    def test_no_metadata_returns_unknown(self, mock_meta):
        result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
        self.assertEqual(result, HdrType.UNKNOWN)

    def test_skip_attached_picture_stream(self):
        """Attached picture streams (mjpeg/png) should be skipped"""
        fixture = {
            "streams": [
                {"codec_type": "video", "codec_name": "mjpeg", "color_transfer": "bt709"},
                {"codec_type": "video", "codec_name": "hevc", "color_transfer": "smpte2084"},
            ]
        }
        with patch.object(FfmpegHelper, 'get_video_metadata', return_value=fixture):
            result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
            self.assertEqual(result, HdrType.HDR10_PQ)

    def test_multiple_streams_no_metadata_continues(self):
        """Missing color_transfer on first video stream should not short-circuit"""
        fixture = {
            "streams": [
                {"codec_type": "video", "codec_name": "hevc"},  # no color_transfer
                {"codec_type": "video", "codec_name": "hevc", "color_transfer": "arib-std-b67"},
            ]
        }
        with patch.object(FfmpegHelper, 'get_video_metadata', return_value=fixture):
            result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
            self.assertEqual(result, HdrType.HLG)

    @patch.object(FfmpegHelper, 'get_video_metadata', return_value=None)
    def test_ffprobe_failure_returns_unknown(self, mock_meta):
        result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
        self.assertEqual(result, HdrType.UNKNOWN)

    @patch.object(FfmpegHelper, 'get_video_metadata', return_value=FIXTURE_NO_VIDEO)
    def test_no_video_stream_returns_unknown(self, mock_meta):
        result = FfmpegHelper.detect_hdr_type("/fake/audio.aac")
        self.assertEqual(result, HdrType.UNKNOWN)

    @patch.object(FfmpegHelper, 'get_video_metadata', return_value=FIXTURE_EMPTY)
    def test_empty_streams_returns_unknown(self, mock_meta):
        result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
        self.assertEqual(result, HdrType.UNKNOWN)

    @patch.object(FfmpegHelper, 'get_video_metadata', return_value=FIXTURE_DV)
    def test_dv_detected_before_hdr10(self, mock_meta):
        """DV should be detected before PQ even when color_transfer=smpte2084"""
        result = FfmpegHelper.detect_hdr_type("/fake/video.mkv")
        self.assertEqual(result, HdrType.DOLBY_VISION)


# ── Test: tonemap filter selection ─────────────────────────────────────

class TestGetTonemapFilter(unittest.TestCase):

    def test_hdr10_returns_hdr10_filter(self):
        self.assertEqual(FfmpegHelper._get_tonemap_filter(HdrType.HDR10_PQ), HDR10_TONEMAP_FILTER)

    def test_dv_returns_hdr10_filter(self):
        self.assertEqual(FfmpegHelper._get_tonemap_filter(HdrType.DOLBY_VISION), HDR10_TONEMAP_FILTER)

    def test_hlg_returns_hlg_filter(self):
        self.assertEqual(FfmpegHelper._get_tonemap_filter(HdrType.HLG), HLG_TONEMAP_FILTER)

    def test_sdr_returns_none(self):
        self.assertIsNone(FfmpegHelper._get_tonemap_filter(HdrType.SDR))

    def test_unknown_returns_none(self):
        self.assertIsNone(FfmpegHelper._get_tonemap_filter(HdrType.UNKNOWN))


# ── Test: command building ─────────────────────────────────────────────

class TestBuildSdrCpuCmd(unittest.TestCase):

    def test_basic_command(self):
        cmd = FfmpegHelper._build_sdr_cpu_cmd("/video.mkv", "/out.jpg", "00:03:01")
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("-hide_banner", cmd)
        self.assertIn("-loglevel", cmd)
        self.assertIn("warning", cmd)
        # -ss before -i (input seeking)
        ss_idx = cmd.index("-ss")
        i_idx = cmd.index("-i")
        self.assertLess(ss_idx, i_idx)
        self.assertEqual(cmd[ss_idx + 1], "00:03:01")
        self.assertEqual(cmd[i_idx + 1], "/video.mkv")
        self.assertIn("-f", cmd)
        self.assertIn("image2", cmd)
        self.assertEqual(cmd[-1], "/out.jpg")

    def test_no_shell_meta_issues(self):
        """subprocess list form is safe with special characters in filenames"""
        cmd = FfmpegHelper._build_sdr_cpu_cmd(
            "/path/to/[test]$file.mkv", "/out.jpg", "00:01:00")
        self.assertEqual(cmd[cmd.index("-i") + 1], "/path/to/[test]$file.mkv")


class TestBuildSdrGpuCmd(unittest.TestCase):

    def test_vaapi_command(self):
        cmd = FfmpegHelper._build_sdr_gpu_cmd("/video.mkv", "/out.jpg", "00:03:01", GpuType.VAAPI)
        self.assertIn("-hwaccel", cmd)
        self.assertIn("vaapi", cmd)
        self.assertIn("-hwaccel_device", cmd)
        self.assertIn("/dev/dri/renderD128", cmd)
        self.assertIn("-hwaccel_output_format", cmd)
        self.assertIn("vaapi", cmd)
        self.assertIn("-c:v", cmd)
        self.assertIn("mjpeg_vaapi", cmd)
        self.assertIn("-update", cmd)
        self.assertIn("scale_vaapi", " ".join(cmd))
        # -ss before -i
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))
        self.assertEqual(cmd[-1], "/out.jpg")

    def test_cuda_command(self):
        cmd = FfmpegHelper._build_sdr_gpu_cmd("/video.mkv", "/out.jpg", "00:03:01", GpuType.NVIDIA_CUDA)
        self.assertIn("-hwaccel", cmd)
        self.assertIn("cuda", cmd)
        self.assertIn("-c:v", cmd)
        self.assertIn("mjpeg", cmd)

    def test_none_returns_none(self):
        self.assertIsNone(FfmpegHelper._build_sdr_gpu_cmd("/v", "/o", "0", GpuType.NONE))


class TestBuildHdrCpuCmd(unittest.TestCase):

    def test_basic_command(self):
        cmd = FfmpegHelper._build_hdr_cpu_cmd("/video.mkv", "/out.jpg", "00:03:01", HDR10_TONEMAP_FILTER)
        self.assertIn("-vf", cmd)
        vf_idx = cmd.index("-vf")
        self.assertIn("zscale", cmd[vf_idx + 1])
        self.assertIn("tonemap", cmd[vf_idx + 1])
        # -ss before -i
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))


class TestBuildHdrGpuCmd(unittest.TestCase):

    def test_vaapi_p010(self):
        cmd = FfmpegHelper._build_hdr_gpu_cmd(
            "/video.mkv", "/out.jpg", "00:03:01", GpuType.VAAPI, HDR10_TONEMAP_FILTER, use_p010=True)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("scale_vaapi=format=p010", vf)
        self.assertIn("hwdownload", vf)
        self.assertIn("format=p010le", vf)
        self.assertIn("zscale=tin=smpte2084", vf)

    def test_vaapi_nv12(self):
        cmd = FfmpegHelper._build_hdr_gpu_cmd(
            "/video.mkv", "/out.jpg", "00:03:01", GpuType.VAAPI, HDR10_TONEMAP_FILTER, use_p010=False)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("scale_vaapi=format=nv12", vf)
        self.assertIn("format=nv12", vf)

    def test_vaapi_hlg_filter(self):
        cmd = FfmpegHelper._build_hdr_gpu_cmd(
            "/video.mkv", "/out.jpg", "00:03:01", GpuType.VAAPI, HLG_TONEMAP_FILTER, use_p010=True)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("arib-std-b67", vf)

    def test_cuda_command(self):
        cmd = FfmpegHelper._build_hdr_gpu_cmd(
            "/video.mkv", "/out.jpg", "00:03:01", GpuType.NVIDIA_CUDA, HDR10_TONEMAP_FILTER)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("hwdownload", vf)
        self.assertIn("format=nv12", vf)
        self.assertIn("zscale=tin=smpte2084", vf)

    def test_none_returns_none(self):
        self.assertIsNone(FfmpegHelper._build_hdr_gpu_cmd(
            "/v", "/o", "0", GpuType.NONE, HDR10_TONEMAP_FILTER))


# ── Test: GPU detection with caching ───────────────────────────────────

class TestDetectGpuType(unittest.TestCase):

    def setUp(self):
        FfmpegHelper._gpu_type_cache = None

    def tearDown(self):
        FfmpegHelper._gpu_type_cache = None

    @patch.object(FfmpegHelper, '_get_ffmpeg_hwaccels', return_value=["vaapi"])
    @patch('os.path.exists', return_value=True)
    def test_vaapi_detected(self, mock_exists, mock_hwaccels):
        result = FfmpegHelper.detect_gpu_type()
        self.assertEqual(result, GpuType.VAAPI)

    @patch.object(FfmpegHelper, '_get_ffmpeg_hwaccels', return_value=["cuda"])
    @patch('os.path.exists', return_value=True)
    def test_no_vaapi_in_hwaccels(self, mock_exists, mock_hwaccels):
        result = FfmpegHelper.detect_gpu_type()
        self.assertEqual(result, GpuType.NONE)

    @patch.object(FfmpegHelper, '_get_ffmpeg_hwaccels', return_value=["vaapi"])
    @patch('os.path.exists', return_value=False)
    def test_vaapi_no_device(self, mock_exists, mock_hwaccels):
        result = FfmpegHelper.detect_gpu_type()
        self.assertEqual(result, GpuType.NONE)

    @patch.object(FfmpegHelper, '_get_ffmpeg_hwaccels', return_value=["vaapi"])
    @patch('os.path.exists', return_value=True)
    def test_cache_works(self, mock_exists, mock_hwaccels):
        """Second call should use cache and not call _get_ffmpeg_hwaccels again"""
        FfmpegHelper.detect_gpu_type()
        FfmpegHelper.detect_gpu_type()
        self.assertEqual(mock_hwaccels.call_count, 1)

    @patch.object(FfmpegHelper, '_get_ffmpeg_hwaccels', return_value=[])
    def test_empty_hwaccels(self, mock_hwaccels):
        result = FfmpegHelper.detect_gpu_type()
        self.assertEqual(result, GpuType.NONE)


# ── Test: _run_ffmpeg execution ────────────────────────────────────────

class TestRunFfmpeg(unittest.TestCase):

    def setUp(self):
        # Mock log.warn to avoid Logger init issues in test environment
        self._log_warn_patcher = patch('app.helper.ffmpeg_helper.log.warn')
        self.mock_log_warn = self._log_warn_patcher.start()

    def tearDown(self):
        self._log_warn_patcher.stop()

    @patch('subprocess.run')
    @patch('os.path.exists', return_value=True)
    @patch('os.path.getsize', return_value=1024)
    def test_success(self, mock_size, mock_exists, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        success, stderr = FfmpegHelper._run_ffmpeg(["ffmpeg", "-i", "in", "-y", "out.jpg"])
        self.assertTrue(success)
        self.assertEqual(stderr, "")

    @patch('subprocess.run')
    def test_nonzero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="error details")
        success, stderr = FfmpegHelper._run_ffmpeg(["ffmpeg", "-i", "in", "-y", "out.jpg"])
        self.assertFalse(success)
        self.assertIn("error details", stderr)

    @patch('subprocess.run')
    @patch('os.path.exists', return_value=False)
    def test_output_file_missing(self, mock_exists, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        success, stderr = FfmpegHelper._run_ffmpeg(["ffmpeg", "-i", "in", "-y", "out.jpg"])
        self.assertFalse(success)
        self.assertIn("missing or empty", stderr)

    @patch('subprocess.run', side_effect=FileNotFoundError)
    def test_ffmpeg_not_found(self, mock_run):
        success, stderr = FfmpegHelper._run_ffmpeg(["ffmpeg", "-i", "in", "-y", "out.jpg"])
        self.assertFalse(success)
        self.assertEqual(stderr, "ffmpeg not found")

    @patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=120))
    def test_timeout(self, mock_run):
        success, stderr = FfmpegHelper._run_ffmpeg(["ffmpeg", "-i", "in", "-y", "out.jpg"])
        self.assertFalse(success)
        self.assertEqual(stderr, "timeout")

    @patch('subprocess.run', side_effect=OSError("permission denied"))
    def test_generic_exception(self, mock_run):
        success, stderr = FfmpegHelper._run_ffmpeg(["ffmpeg", "-i", "in", "-y", "out.jpg"])
        self.assertFalse(success)
        self.assertIn("permission denied", stderr)


# ── Test: main entry point get_thumb_image_from_video ──────────────────

class TestGetThumbImageFromVideo(unittest.TestCase):

    def setUp(self):
        FfmpegHelper._gpu_type_cache = None
        # Setup mock Config
        self._mock_config = MagicMock()
        self._mock_config.get_config.return_value = {'force_tonemap_unknown': False}
        mock_config_module.Config.return_value = self._mock_config
        # Mock log.warn to avoid Logger init issues
        self._log_warn_patcher = patch('app.helper.ffmpeg_helper.log.warn')
        self.mock_log_warn = self._log_warn_patcher.start()

    def tearDown(self):
        FfmpegHelper._gpu_type_cache = None
        self._log_warn_patcher.stop()

    def test_empty_video_path(self):
        self.assertFalse(FfmpegHelper.get_thumb_image_from_video("", "/out.jpg"))

    def test_empty_image_path(self):
        self.assertFalse(FfmpegHelper.get_thumb_image_from_video("/video.mkv", ""))

    @patch.object(FfmpegHelper, 'detect_gpu_type', return_value=GpuType.NONE)
    @patch.object(FfmpegHelper, 'detect_hdr_type', return_value=HdrType.SDR)
    @patch.object(FfmpegHelper, '_gen_thumb_sdr_cpu', return_value=True)
    def test_sdr_cpu_path(self, mock_sdr_cpu, mock_hdr, mock_gpu):
        result = FfmpegHelper.get_thumb_image_from_video("/video.mkv", "/out.jpg")
        self.assertTrue(result)
        mock_sdr_cpu.assert_called_once()

    @patch.object(FfmpegHelper, 'detect_gpu_type', return_value=GpuType.VAAPI)
    @patch.object(FfmpegHelper, 'detect_hdr_type', return_value=HdrType.SDR)
    @patch.object(FfmpegHelper, '_run_ffmpeg', return_value=(True, ""))
    def test_sdr_gpu_path(self, mock_run, mock_hdr, mock_gpu):
        result = FfmpegHelper.get_thumb_image_from_video("/video.mkv", "/out.jpg")
        self.assertTrue(result)
        cmd = mock_run.call_args[0][0]
        self.assertIn("mjpeg_vaapi", cmd)

    @patch.object(FfmpegHelper, 'detect_gpu_type', return_value=GpuType.VAAPI)
    @patch.object(FfmpegHelper, 'detect_hdr_type', return_value=HdrType.SDR)
    @patch.object(FfmpegHelper, '_run_ffmpeg', return_value=(False, "GPU error"))
    @patch.object(FfmpegHelper, '_gen_thumb_sdr_cpu', return_value=True)
    def test_sdr_gpu_fallback_to_cpu(self, mock_sdr_cpu, mock_run, mock_hdr, mock_gpu):
        result = FfmpegHelper.get_thumb_image_from_video("/video.mkv", "/out.jpg")
        self.assertTrue(result)
        mock_sdr_cpu.assert_called_once()

    @patch.object(FfmpegHelper, 'detect_gpu_type', return_value=GpuType.NONE)
    @patch.object(FfmpegHelper, 'detect_hdr_type', return_value=HdrType.HDR10_PQ)
    @patch.object(FfmpegHelper, '_gen_thumb_hdr_cpu', return_value=True)
    def test_hdr_cpu_path(self, mock_hdr_cpu, mock_hdr, mock_gpu):
        result = FfmpegHelper.get_thumb_image_from_video("/video.mkv", "/out.jpg")
        self.assertTrue(result)
        mock_hdr_cpu.assert_called_once()

    @patch.object(FfmpegHelper, 'detect_gpu_type', return_value=GpuType.VAAPI)
    @patch.object(FfmpegHelper, 'detect_hdr_type', return_value=HdrType.HDR10_PQ)
    @patch.object(FfmpegHelper, '_gen_thumb_with_hdr_gpu_fallback', return_value=True)
    def test_hdr_gpu_path(self, mock_hdr_gpu_fb, mock_hdr, mock_gpu):
        result = FfmpegHelper.get_thumb_image_from_video("/video.mkv", "/out.jpg")
        self.assertTrue(result)
        mock_hdr_gpu_fb.assert_called_once()

    @patch.object(FfmpegHelper, 'detect_gpu_type', return_value=GpuType.NONE)
    @patch.object(FfmpegHelper, 'detect_hdr_type', return_value=HdrType.UNKNOWN)
    @patch.object(FfmpegHelper, '_gen_thumb_sdr_cpu', return_value=True)
    def test_unknown_hdr_default_sdr(self, mock_sdr_cpu, mock_hdr, mock_gpu):
        result = FfmpegHelper.get_thumb_image_from_video("/video.mkv", "/out.jpg")
        self.assertTrue(result)
        mock_sdr_cpu.assert_called_once()

    @patch.object(FfmpegHelper, 'detect_gpu_type', return_value=GpuType.NONE)
    @patch.object(FfmpegHelper, 'detect_hdr_type', return_value=HdrType.UNKNOWN)
    @patch.object(FfmpegHelper, '_gen_thumb_hdr_cpu', return_value=True)
    def test_unknown_hdr_force_tonemap(self, mock_hdr_cpu, mock_hdr, mock_gpu):
        self._mock_config.get_config.return_value = {'force_tonemap_unknown': True}
        result = FfmpegHelper.get_thumb_image_from_video("/video.mkv", "/out.jpg")
        self.assertTrue(result)
        mock_hdr_cpu.assert_called_once()

    @patch.object(FfmpegHelper, 'detect_gpu_type', return_value=GpuType.NONE)
    @patch.object(FfmpegHelper, 'detect_hdr_type', return_value=HdrType.HLG)
    @patch.object(FfmpegHelper, '_gen_thumb_hdr_cpu', return_value=True)
    def test_hlg_uses_hlg_filter(self, mock_hdr_cpu, mock_hdr, mock_gpu):
        result = FfmpegHelper.get_thumb_image_from_video("/video.mkv", "/out.jpg")
        self.assertTrue(result)
        # Verify HLG filter was passed
        call_args = mock_hdr_cpu.call_args
        tonemap_filter = call_args[0][3]
        self.assertIn("arib-std-b67", tonemap_filter)


# ── Test: HDR GPU multi-level fallback ─────────────────────────────────

class TestHdrGpuFallback(unittest.TestCase):

    def setUp(self):
        self._log_warn_patcher = patch('app.helper.ffmpeg_helper.log.warn')
        self.mock_log_warn = self._log_warn_patcher.start()

    def tearDown(self):
        self._log_warn_patcher.stop()

    @patch.object(FfmpegHelper, '_run_ffmpeg', return_value=(True, ""))
    def test_p010_success(self, mock_run):
        result = FfmpegHelper._gen_thumb_with_hdr_gpu_fallback(
            "/v.mkv", "/o.jpg", "00:01:00", GpuType.VAAPI, HDR10_TONEMAP_FILTER)
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 1)
        cmd = mock_run.call_args[0][0]
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("p010", vf)

    @patch.object(FfmpegHelper, '_run_ffmpeg')
    @patch.object(FfmpegHelper, '_gen_thumb_hdr_cpu', return_value=True)
    def test_p010_fail_nv12_success(self, mock_hdr_cpu, mock_run):
        mock_run.side_effect = [(False, "p010 error"), (True, "")]
        result = FfmpegHelper._gen_thumb_with_hdr_gpu_fallback(
            "/v.mkv", "/o.jpg", "00:01:00", GpuType.VAAPI, HDR10_TONEMAP_FILTER)
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        mock_hdr_cpu.assert_not_called()

    @patch.object(FfmpegHelper, '_run_ffmpeg', return_value=(False, "error"))
    @patch.object(FfmpegHelper, '_gen_thumb_hdr_cpu', return_value=True)
    def test_all_gpu_fail_fallback_to_cpu(self, mock_hdr_cpu, mock_run):
        result = FfmpegHelper._gen_thumb_with_hdr_gpu_fallback(
            "/v.mkv", "/o.jpg", "00:01:00", GpuType.VAAPI, HDR10_TONEMAP_FILTER)
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)  # p010 + nv12
        mock_hdr_cpu.assert_called_once()


# ── Test: deprecated methods ───────────────────────────────────────────

class TestDeprecatedMethods(unittest.TestCase):

    def test_get_intel_gpu_device_path(self):
        self.assertEqual(FfmpegHelper.get_intel_gpu_device_path(), "/dev/dri/renderD128")

    @patch('os.path.exists', return_value=True)
    def test_intel_gpu_exist_check(self, mock_exists):
        self.assertTrue(FfmpegHelper.intel_gpu_exist_check())


# ── Test: constants ────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_gpu_device_paths(self):
        self.assertEqual(GPU_DEVICE_PATHS[GpuType.VAAPI], "/dev/dri/renderD128")
        self.assertEqual(GPU_DEVICE_PATHS[GpuType.NVIDIA_CUDA], "/dev/nvidia0")

    def test_tonemap_filters_contain_zscale(self):
        self.assertIn("zscale", HDR10_TONEMAP_FILTER)
        self.assertIn("tonemap", HDR10_TONEMAP_FILTER)
        self.assertIn("zscale", HLG_TONEMAP_FILTER)
        self.assertIn("arib-std-b67", HLG_TONEMAP_FILTER)

    def test_hdr10_filter_uses_smpte2084(self):
        self.assertIn("smpte2084", HDR10_TONEMAP_FILTER)

    def test_hlg_filter_uses_arib_std_b67(self):
        self.assertIn("arib-std-b67", HLG_TONEMAP_FILTER)


if __name__ == '__main__':
    unittest.main()
