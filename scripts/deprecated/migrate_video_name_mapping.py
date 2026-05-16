#!/usr/bin/env python3
"""
DEPRECATED: This script will be removed in a future release.
video_name_mapping.yaml is no longer used at runtime. Use media_mapping.yaml instead.

Migration script: convert video_name_mapping.yaml to media_mapping.yaml.

Usage:
    python scripts/deprecated/migrate_video_name_mapping.py [--source PATH] [--target PATH] [--overwrite] [--dry-run]

Each `key: value` entry in the source file is converted to `key: {title: value}`.
"""

import argparse
import os
import sys
import tempfile

import yaml


def migrate(source_path, target_path, overwrite=False, dry_run=False):
    # Source file must exist
    if not os.path.exists(source_path):
        print(f"Error: source file not found: {source_path}", file=sys.stderr)
        return 1

    with open(source_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    # Empty source: empty dict, None, or empty file
    if not raw:
        print(f"Source file is empty, nothing to migrate: {source_path}")
        return 0

    if not isinstance(raw, dict):
        print(f"Error: source file is not a YAML dict: {source_path}", file=sys.stderr)
        return 1

    # Convert key: value -> key: {title: value}
    migrated = {}
    for key, value in raw.items():
        migrated[key] = {"title": value}

    output_yaml = yaml.dump(migrated, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if dry_run:
        print(output_yaml, end="")
        return 0

    # Target file exists check
    if os.path.exists(target_path) and not overwrite:
        print(
            f"Error: target file already exists: {target_path}\n"
            f"Use --overwrite to replace it.",
            file=sys.stderr,
        )
        return 1

    # Atomic write: write to temp file then os.replace()
    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(output_yaml)
        os.replace(tmp_path, target_path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    print(f"Migrated {len(migrated)} entries: {source_path} -> {target_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Migrate video_name_mapping.yaml to media_mapping.yaml"
    )
    parser.add_argument(
        "--source",
        default="/config/video_name_mapping.yaml",
        help="Source video_name_mapping.yaml path (default: /config/video_name_mapping.yaml)",
    )
    parser.add_argument(
        "--target",
        default="/config/media_mapping.yaml",
        help="Target media_mapping.yaml path (default: /config/media_mapping.yaml)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite target file if it already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print migrated YAML to stdout without writing file",
    )
    args = parser.parse_args()
    sys.exit(migrate(args.source, args.target, overwrite=args.overwrite, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
