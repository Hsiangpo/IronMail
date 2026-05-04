# -*- coding: utf-8 -*-

from pathlib import Path

from ironmail import config_manager


def write_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
license:
  server_url: https://tmpmail.oldiron.us
  code:
smtp:
  host: smtp.gmail.com
  port: 465
  use_ssl: true
smtp_proxy:
  mode: auto
  type: http
  host: 127.0.0.1
  port: 7897
  candidate_ports:
    - 7897
    - 7890
  connect_timeout_seconds: 8
senders:
  - email: old@example.com
    password: old-pass
    name: 老账号
settings:
  emails_per_account: 2
  delay_seconds: 12
  max_retries: 3
  log_file: logs/send_log.txt
""".lstrip(),
        encoding="utf-8",
    )


def test_add_update_delete_sender_roundtrip(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)

    config = config_manager.load_config(config_path)
    sender = config_manager.build_sender(
        email="sales@oldiron.us",
        password="app-pass",
        name="销售一号",
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_use_ssl=True,
    )
    config_manager.add_sender(config, sender)
    config_manager.save_config(config_path, config)

    loaded = config_manager.load_config(config_path)
    assert [item["email"] for item in loaded["senders"]] == [
        "old@example.com",
        "sales@oldiron.us",
    ]

    config_manager.update_sender(
        loaded,
        "sales@oldiron.us",
        {"name": "销售二号", "smtp": {"host": "smtp.gmail.com", "port": 587, "use_ssl": False}},
    )
    config_manager.delete_sender(loaded, "old@example.com")
    config_manager.save_config(config_path, loaded)

    final_config = config_manager.load_config(config_path)
    assert len(final_config["senders"]) == 1
    assert final_config["senders"][0]["name"] == "销售二号"
    assert final_config["senders"][0]["smtp"]["port"] == 587
    assert final_config["senders"][0]["smtp"]["use_ssl"] is False


def test_resolve_sender_smtp_uses_sender_override_then_default(tmp_path):
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = config_manager.load_config(config_path)
    default_sender = config["senders"][0]
    custom_sender = config_manager.build_sender(
        email="custom@example.com",
        password="secret",
        name="自定义",
        smtp_host="mail.example.com",
        smtp_port=2525,
        smtp_use_ssl=False,
    )

    assert config_manager.resolve_sender_smtp(config, default_sender) == {
        "host": "smtp.gmail.com",
        "port": 465,
        "use_ssl": True,
    }
    assert config_manager.resolve_sender_smtp(config, custom_sender) == {
        "host": "mail.example.com",
        "port": 2525,
        "use_ssl": False,
    }


def test_normalize_config_keeps_smtp_proxy_settings(tmp_path):
    config_path = tmp_path / "config.yaml"
    write_config(config_path)

    config = config_manager.load_config(config_path)

    assert config["smtp_proxy"] == {
        "mode": "auto",
        "type": "http",
        "host": "127.0.0.1",
        "port": 7897,
        "candidate_ports": [7897, 7890],
        "connect_timeout_seconds": 8,
    }


def test_legacy_smtp_proxy_enabled_maps_to_proxy_mode():
    config = config_manager.normalize_config(
        {
            "smtp_proxy": {
                "enabled": True,
                "type": "http",
                "host": "127.0.0.1",
                "port": 7897,
            }
        }
    )

    assert config["smtp_proxy"]["mode"] == "proxy"


def test_candidate_ports_include_primary_port_first():
    config = config_manager.normalize_config(
        {"smtp_proxy": {"port": 7890, "candidate_ports": [7897, "7890", 1080]}}
    )

    assert config["smtp_proxy"]["candidate_ports"] == [7890, 7897, 1080]


def test_mask_sender_hides_password_and_keeps_email():
    sender = config_manager.build_sender(
        email="sales@oldiron.us",
        password="abcdefghijklmnop",
        name="销售",
    )

    masked = config_manager.mask_sender(sender)

    assert masked["email"] == "sales@oldiron.us"
    assert masked["password"] == "abcd********mnop"
