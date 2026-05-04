# -*- coding: utf-8 -*-

from pathlib import Path

from ironmail import config_manager
from ironmail.main import ensure_license_code, run_send_flow


def test_ensure_license_code_prompts_when_missing(monkeypatch):
    config = config_manager.normalize_config({"license": {"server_url": "https://tmpmail.oldiron.us"}})
    monkeypatch.setattr("builtins.input", lambda prompt="": "IM-AAAAAA-BBBBBB-CCCCCC-DDDDDD")

    ensure_license_code(config)

    assert config["license"]["code"] == "IM-AAAAAA-BBBBBB-CCCCCC-DDDDDD"


def test_ensure_license_code_keeps_existing_code(monkeypatch):
    config = config_manager.normalize_config({"license": {"code": "IM-EXISTING"}})
    monkeypatch.setattr("builtins.input", lambda prompt="": "IM-NEW")

    ensure_license_code(config)

    assert config["license"]["code"] == "IM-EXISTING"


def test_run_send_flow_does_not_verify_license_again(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
license:
  server_url: https://tmpmail.oldiron.us
  code:
smtp:
  host: smtp.gmail.com
  port: 465
  use_ssl: true
senders: []
settings:
  emails_per_account: 1
  delay_seconds: 12
  max_retries: 3
  log_file: logs/send_log.txt
""".lstrip(),
        encoding="utf-8",
    )
    verify_calls = []
    monkeypatch.setattr("ironmail.main.verify_license", lambda config: verify_calls.append(config) or True)

    run_send_flow(tmp_path, config_path)

    assert verify_calls == []


def test_run_send_flow_does_not_show_disclaimer(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
license:
  server_url: https://tmpmail.oldiron.us
  code:
smtp:
  host: smtp.gmail.com
  port: 465
  use_ssl: true
senders: []
settings:
  emails_per_account: 1
  delay_seconds: 12
  max_retries: 3
  log_file: logs/send_log.txt
""".lstrip(),
        encoding="utf-8",
    )

    assert not hasattr(__import__("ironmail.main").main, "show_disclaimer")
