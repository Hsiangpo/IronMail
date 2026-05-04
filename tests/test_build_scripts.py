# -*- coding: utf-8 -*-

from pathlib import Path


def test_windows_build_writes_sanitized_dist_config():
    script = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")

    assert "Copy-Item config\\config.example.yaml $DistConfigPath -Force" in script
    assert "Keeping existing runtime config" not in script
