"""Tests for migrate_video_name_mapping.py"""

import os
import subprocess
import sys
import textwrap

import yaml
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "migrate_video_name_mapping.py")


def run_migrate(*args, stdin=None):
    """Run the migration script and return (returncode, stdout, stderr)."""
    cmd = [sys.executable, SCRIPT] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(__file__))
    return result.returncode, result.stdout, result.stderr


class TestBasicConversion:
    """Basic conversion: key: value -> key: {title: value}"""

    def test_simple_entry(self, tmp_path):
        src = tmp_path / "source.yaml"
        dst = tmp_path / "target.yaml"
        src.write_text("the_long_season: 漫长的季节\n", encoding="utf-8")

        rc, out, err = run_migrate("--source", str(src), "--target", str(dst))
        assert rc == 0
        assert dst.exists()

        with open(dst, "r", encoding="utf-8") as f:
            result = yaml.safe_load(f)
        assert result == {"the_long_season": {"title": "漫长的季节"}}

    def test_multiple_entries(self, tmp_path):
        src = tmp_path / "source.yaml"
        dst = tmp_path / "target.yaml"
        src.write_text(
            "the_long_season: 漫长的季节\nclimax: Climax\n",
            encoding="utf-8",
        )

        rc, out, err = run_migrate("--source", str(src), "--target", str(dst))
        assert rc == 0

        with open(dst, "r", encoding="utf-8") as f:
            result = yaml.safe_load(f)
        assert result == {
            "the_long_season": {"title": "漫长的季节"},
            "climax": {"title": "Climax"},
        }


class TestTargetExistsNoOverwrite:
    """Target exists without --overwrite fails"""

    def test_fails_when_target_exists(self, tmp_path):
        src = tmp_path / "source.yaml"
        dst = tmp_path / "target.yaml"
        src.write_text("the_long_season: 漫长的季节\n", encoding="utf-8")
        dst.write_text("existing: data\n", encoding="utf-8")

        rc, out, err = run_migrate("--source", str(src), "--target", str(dst))
        assert rc != 0
        assert "already exists" in err

        # Target should not be modified
        assert dst.read_text(encoding="utf-8") == "existing: data\n"


class TestTargetExistsWithOverwrite:
    """Target exists with --overwrite succeeds"""

    def test_overwrites_when_flag_set(self, tmp_path):
        src = tmp_path / "source.yaml"
        dst = tmp_path / "target.yaml"
        src.write_text("the_long_season: 漫长的季节\n", encoding="utf-8")
        dst.write_text("existing: data\n", encoding="utf-8")

        rc, out, err = run_migrate("--source", str(src), "--target", str(dst), "--overwrite")
        assert rc == 0

        with open(dst, "r", encoding="utf-8") as f:
            result = yaml.safe_load(f)
        assert result == {"the_long_season": {"title": "漫长的季节"}}


class TestDryRun:
    """--dry-run outputs YAML but doesn't write file"""

    def test_dry_run_no_file_written(self, tmp_path):
        src = tmp_path / "source.yaml"
        dst = tmp_path / "target.yaml"
        src.write_text("the_long_season: 漫长的季节\n", encoding="utf-8")

        rc, out, err = run_migrate("--source", str(src), "--target", str(dst), "--dry-run")
        assert rc == 0
        assert not dst.exists()

        # stdout should contain valid YAML
        result = yaml.safe_load(out)
        assert result == {"the_long_season": {"title": "漫长的季节"}}


class TestEmptySource:
    """Empty source file"""

    def test_empty_dict(self, tmp_path):
        src = tmp_path / "source.yaml"
        dst = tmp_path / "target.yaml"
        src.write_text("{}\n", encoding="utf-8")

        rc, out, err = run_migrate("--source", str(src), "--target", str(dst))
        assert rc == 0
        assert not dst.exists()
        assert "empty" in out.lower()

    def test_empty_file(self, tmp_path):
        src = tmp_path / "source.yaml"
        dst = tmp_path / "target.yaml"
        src.write_text("", encoding="utf-8")

        rc, out, err = run_migrate("--source", str(src), "--target", str(dst))
        assert rc == 0
        assert not dst.exists()

    def test_whitespace_only_file(self, tmp_path):
        src = tmp_path / "source.yaml"
        dst = tmp_path / "target.yaml"
        src.write_text("  \n  \n", encoding="utf-8")

        rc, out, err = run_migrate("--source", str(src), "--target", str(dst))
        assert rc == 0
        assert not dst.exists()


class TestSourceNotFound:
    """Source file not found"""

    def test_nonexistent_source(self, tmp_path):
        src = tmp_path / "nonexistent.yaml"
        dst = tmp_path / "target.yaml"

        rc, out, err = run_migrate("--source", str(src), "--target", str(dst))
        assert rc != 0
        assert "not found" in err.lower()
