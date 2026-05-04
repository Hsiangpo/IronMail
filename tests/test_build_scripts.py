# -*- coding: utf-8 -*-

from pathlib import Path


def test_windows_build_writes_sanitized_dist_config():
    script = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")

    assert "Copy-Item config\\config.example.yaml $DistConfigPath -Force" in script
    assert "Keeping existing runtime config" not in script


def test_dist_sanitizer_writes_example_config():
    script = Path("scripts/sanitize_dist.ps1").read_text(encoding="utf-8")

    assert "Copy-Item config\\config.example.yaml dist\\config\\config.yaml -Force" in script
    assert "config\\config.yaml dist\\config\\config.yaml" not in script
