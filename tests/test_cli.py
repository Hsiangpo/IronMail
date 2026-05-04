# -*- coding: utf-8 -*-

from pathlib import Path

from ironmail import cli, config_manager


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
senders: []
settings:
  emails_per_account: 1
  delay_seconds: 12
  max_retries: 3
  log_file: logs/send_log.txt
""".lstrip(),
        encoding="utf-8",
    )


def make_input(values):
    iterator = iter(values)
    return lambda prompt="": next(iterator)


def test_sender_menu_adds_gmail_default_sender(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = make_input([
        "2",
        "sales@oldiron.us",
        "销售",
        "app-password",
        "",
        "0",
    ])
    output = []

    cli.manage_senders(config_path, inputs, output.append)

    config = config_manager.load_config(config_path)
    assert config["senders"][0]["email"] == "sales@oldiron.us"
    assert "smtp" not in config["senders"][0]


def test_settings_menu_updates_rotation_without_yaml_editing(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = make_input(["3", "5", "2"])
    output = []

    cli.manage_send_settings(config_path, inputs, output.append)

    settings = config_manager.load_config(config_path)["settings"]
    assert settings["emails_per_account"] == 3
    assert settings["delay_seconds"] == 5
    assert settings["max_retries"] == 2


def test_license_menu_updates_code_without_yaml_editing(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = make_input(["IM-AAAAAA-BBBBBB-CCCCCC-DDDDDD"])
    output = []

    cli.manage_license(config_path, inputs, output.append)

    config = config_manager.load_config(config_path)
    assert config["license"]["code"] == "IM-AAAAAA-BBBBBB-CCCCCC-DDDDDD"


def test_main_menu_shows_runtime_verified_license():
    config = config_manager.normalize_config({"license": {"code": ""}})
    output = []

    cli.show_main_menu(config, output.append, license_verified=True)

    assert any("授权状态: 本次已验证" in line for line in output)


def test_smtp_setup_guide_mentions_gmail_app_password():
    output = []

    cli.print_smtp_setup_guide(output.append)

    joined = "\n".join(output)
    assert "https://myaccount.google.com/apppasswords" in joined
    assert "16位应用专用密码" in joined


def test_smtp_failure_hint_explains_app_password_and_network():
    hint = cli.smtp_failure_hint(Exception("Username and Password not accepted"))

    assert "应用专用密码" in hint
    assert "两步验证" in hint


def test_add_sender_rejects_empty_password(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = make_input([
        "sales@gmail.com",
        "销售",
        "",
        "",
    ])
    output = []

    cli.add_sender_interactive(config_path, config_manager.load_config(config_path), inputs, output.append)

    assert any("密码不能为空" in line for line in output)
    assert config_manager.load_config(config_path)["senders"] == []


def test_console_uses_single_screen_refresh_for_real_terminal(monkeypatch):
    output = []
    monkeypatch.setattr("builtins.print", lambda text="", end="\n": output.append((text, end)))
    monkeypatch.setattr("ironmail.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("ironmail.cli.sys.stdout.isatty", lambda: True)

    cli.clear_screen(input, print)

    assert output == [("\033[2J\033[H", "")]


def test_console_does_not_pause_when_stdin_is_piped(monkeypatch):
    monkeypatch.setattr("ironmail.cli.sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("ironmail.cli.sys.stdout.isatty", lambda: True)
    output = []

    cli.pause_after_action(input, output.append)

    assert output == []


def test_pause_after_action_is_skipped_for_test_input():
    inputs = make_input([])
    output = []

    cli.pause_after_action(inputs, output.append)

    assert output == []
