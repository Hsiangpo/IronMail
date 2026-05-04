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


def test_sender_menu_adds_gmail_default_sender_after_smtp_test(tmp_path, monkeypatch):
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
    tested = []

    def fake_test_smtp_login(smtp_config, sender):
        tested.append((smtp_config["host"], sender["email"]))
        return True

    monkeypatch.setattr("ironmail.cli.mailer.test_smtp_login", fake_test_smtp_login)

    cli.manage_senders(config_path, inputs, output.append)

    config = config_manager.load_config(config_path)
    assert config["senders"][0]["email"] == "sales@oldiron.us"
    assert "smtp" not in config["senders"][0]
    assert tested == [("smtp.gmail.com", "sales@oldiron.us")]
    assert any("SMTP登录测试通过" in line for line in output)


def test_sender_menu_does_not_save_when_smtp_test_fails(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = make_input([
        "2",
        "bad@gmail.com",
        "Bad",
        "wrong-password",
        "",
        "0",
    ])
    output = []

    def fake_test_smtp_login(smtp_config, sender):
        raise RuntimeError("Username and Password not accepted")

    monkeypatch.setattr("ironmail.cli.mailer.test_smtp_login", fake_test_smtp_login)

    cli.manage_senders(config_path, inputs, output.append)

    assert config_manager.load_config(config_path)["senders"] == []
    assert any("保存失败: SMTP登录测试未通过" in line for line in output)
    assert any("应用专用密码" in line for line in output)


def test_sender_menu_can_return_while_adding_sender(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = make_input([
        "2",
        "0",
        "0",
    ])
    output = []

    cli.manage_senders(config_path, inputs, output.append)

    assert config_manager.load_config(config_path)["senders"] == []
    assert any("已返回上一层" in line for line in output)


def test_sender_picker_can_return_to_previous_menu():
    config = config_manager.normalize_config({
        "senders": [{"email": "a@gmail.com", "password": "app-password"}]
    })
    output = []

    sender = cli.pick_sender(config, make_input(["0"]), output.append)

    assert sender is None
    assert any("已返回上一层" in line for line in output)


def test_read_smtp_fields_mentions_enter_default_gmail():
    prompts = []

    cli.read_smtp_fields(lambda prompt="": prompts.append(prompt) or "", lambda line: None)

    assert any("回车默认Gmail" in prompt for prompt in prompts)


def test_sender_menu_tests_all_smtp_accounts(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    config = config_manager.load_config(config_path)
    config["senders"] = [
        {"email": "a@gmail.com", "password": "a-password", "name": "A"},
        {"email": "b@gmail.com", "password": "b-password", "name": "B"},
    ]
    config_manager.save_config(config_path, config)
    tested = []

    def fake_test_smtp_login(smtp_config, sender):
        tested.append((sender["email"], smtp_config["host"]))
        if sender["email"] == "b@gmail.com":
            raise RuntimeError("Username and Password not accepted")
        return True

    monkeypatch.setattr("ironmail.cli.mailer.test_smtp_login", fake_test_smtp_login)
    output = []
    inputs = make_input(["6", "0"])

    cli.manage_senders(config_path, inputs, output.append)

    assert tested == [
        ("a@gmail.com", "smtp.gmail.com"),
        ("b@gmail.com", "smtp.gmail.com"),
    ]
    assert any("测试完成：成功 1 个，失败 1 个" in line for line in output)
    assert any("应用专用密码" in line for line in output)


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

    joined = "\n".join(output)
    assert "┌" in joined
    assert "│ IronMail 控制台" in joined
    assert "授权状态  本次已验证" in joined
    assert "1. 开始发送邮件" in joined


def test_console_clears_before_starting_send(monkeypatch, tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = iter(["1", "", "0"])
    output = []
    started = []
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("builtins.print", lambda text="", end="\n": output.append((text, end)))
    monkeypatch.setattr("ironmail.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("ironmail.cli.sys.stdout.isatty", lambda: True)

    cli.run_console(config_path, lambda: started.append(True), input, print, license_verified=True)

    clear_count = sum(1 for text, _ in output if text == "\033[2J\033[H")
    assert started == [True]
    assert clear_count >= 2


def test_console_forces_clear_for_builtin_terminal_even_when_isatty_false(monkeypatch, tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = iter(["0"])
    output = []
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("builtins.print", lambda text="", end="\n": output.append((text, end)))
    monkeypatch.setattr("ironmail.cli.sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("ironmail.cli.sys.stdout.isatty", lambda: False)

    cli.run_console(config_path, lambda: None, input, print, license_verified=True)

    assert ("\033[2J\033[H", "") in output


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
