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


def test_sender_menu_adds_gmx_sender_with_provider_smtp(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = make_input([
        "2",
        "sender@gmx.com",
        "GMX销售",
        "smtp-password",
        "",
        "0",
    ])
    output = []
    tested = []

    def fake_test_smtp_login(smtp_config, sender):
        tested.append((smtp_config["host"], smtp_config["port"], sender["email"]))
        return True

    monkeypatch.setattr("ironmail.cli.mailer.test_smtp_login", fake_test_smtp_login)

    cli.manage_senders(config_path, inputs, output.append)

    sender = config_manager.load_config(config_path)["senders"][0]
    assert sender["email"] == "sender@gmx.com"
    assert sender["smtp"] == {"host": "mail.gmx.com", "port": 465, "use_ssl": True}
    assert tested == [("mail.gmx.com", 465, "sender@gmx.com")]
    joined = "\n".join(output)
    assert "步骤 1/4: 填写邮箱地址" in joined
    assert "提示：填写要用于发件的完整邮箱地址" in joined
    assert "步骤 2/4: 填写显示名称" in joined
    assert "提示：显示名称会出现在邮件发件人位置" in joined
    assert "步骤 3/4: 填写邮箱密码" in joined
    assert "提示：Gmail 填16位应用专用密码" in joined
    assert "步骤 4/4: SMTP设置" in joined
    assert "提示：一般直接回车即可" in joined


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


def test_read_smtp_fields_mentions_auto_provider_default():
    prompts = []
    output = []

    cli.read_smtp_fields(lambda prompt="": prompts.append(prompt) or "", output.append, email="sender@gmx.com")

    assert any("直接回车使用默认设置" in prompt for prompt in prompts)
    assert any("已识别为 GMX 邮箱" in line for line in output)


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


def test_sender_menu_tests_all_smtp_accounts_with_parallel_limit(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    config = config_manager.load_config(config_path)
    config["senders"] = [
        {"email": f"sender{index}@gmail.com", "password": "password", "name": str(index)}
        for index in range(70)
    ]
    config_manager.save_config(config_path, config)
    observed_workers = []

    class FakeExecutor:
        def __init__(self, max_workers):
            observed_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def map(self, func, items):
            return [func(item) for item in items]

    monkeypatch.setattr("ironmail.cli.ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr("ironmail.cli.mailer.test_smtp_login", lambda smtp, sender: True)
    output = []

    cli.test_all_senders_interactive(config, output.append)

    assert observed_workers == [64]
    assert any("64并发" in line for line in output)


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
    joined = "\n".join(output)
    assert "步骤 1/3: 设置轮换封数" in joined
    assert "提示：例如填1表示每发1封就切换下一个邮箱" in joined
    assert "步骤 2/3: 设置发送间隔" in joined
    assert "步骤 3/3: 设置失败重试次数" in joined


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
    assert "6. 配置" in joined
    assert "查看当前配置" not in joined


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

    clear_count = sum(1 for text, _ in output if text == cli.CLEAR_SCREEN_SEQUENCE)
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

    assert (cli.CLEAR_SCREEN_SEQUENCE, "") in output


def test_smtp_setup_guide_mentions_gmail_app_password():
    output = []

    cli.print_smtp_setup_guide(output.append)

    joined = "\n".join(output)
    assert "Gmail填写说明" in joined
    assert "GMX填写说明" in joined
    assert "https://myaccount.google.com/apppasswords" in joined
    assert "16位应用专用密码" in joined
    assert "系统会使用默认SMTP设置" in joined
    assert "；" not in joined
    assert "SSL" not in joined
    assert "STARTTLS" not in joined


def test_add_sender_smtp_guidance_stays_plain_and_compact(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = make_input([
        "sender@gmx.com",
        "GMX销售",
        "smtp-password",
        "",
    ])
    output = []
    monkeypatch.setattr("ironmail.cli.mailer.test_smtp_login", lambda smtp, sender: True)

    cli.add_sender_interactive(config_path, config_manager.load_config(config_path), inputs, output.append)

    joined = "\n".join(output)
    assert "步骤 4/4: SMTP设置" in joined
    assert "提示：一般直接回车即可" in joined
    assert "已识别为 GMX 邮箱" in joined
    assert "直接回车会使用默认SMTP设置" in joined
    assert "正在验证SMTP登录" in joined
    assert "；" not in joined
    assert "SSL" not in joined
    assert "STARTTLS" not in joined
    assert "发信服务" not in joined


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

    assert output == [(cli.CLEAR_SCREEN_SEQUENCE, "")]


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


def test_template_menu_creates_template_and_opens_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    opened = []
    output = []
    inputs = make_input(["2", "德国邀请", "0"])
    monkeypatch.setattr("ironmail.cli.open_template_file", lambda path: opened.append(path))

    cli.manage_templates(config_path, inputs, output.append)

    template_path = tmp_path / "Mails" / "邮件模板" / "德国邀请.md"
    assert template_path.exists()
    assert template_path.read_text(encoding="utf-8") == "邮件主题：\n\n邮件正文：\n"
    assert opened == [template_path]
    joined = "\n".join(output)
    assert "步骤 1/1: 填写模板名称" in joined
    assert "提示：系统会自动创建 .md 模板文件" in joined


def test_template_menu_deletes_template_after_confirmation(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    template_dir = tmp_path / "Mails" / "邮件模板"
    template_dir.mkdir(parents=True)
    template_path = template_dir / "旧模板.md"
    template_path.write_text("邮件主题：测试\n\n邮件正文：测试", encoding="utf-8")
    inputs = make_input(["4", "1", "DELETE", "0"])

    cli.manage_templates(config_path, inputs, lambda line: None)

    assert not template_path.exists()


def test_template_list_shows_full_template_content(tmp_path):
    template_dir = tmp_path / "Mails" / "邮件模板"
    template_dir.mkdir(parents=True)
    template_path = template_dir / "德国公司示例模板.md"
    template_path.write_text(
        "邮件主题：\n"
        "Bitte um Einrichtung einer WhatsApp-Gruppe für {{网页}}\n\n"
        "邮件正文：\n"
        "Sehr geehrte/r {{法人}},\n",
        encoding="utf-8",
    )
    output = []

    cli.list_templates(template_dir, output.append)

    joined = "\n".join(output)
    assert "德国公司示例模板.md" in joined
    assert "Bitte um Einrichtung einer WhatsApp-Gruppe" in joined
    assert "Sehr geehrte/r {{法人}}" in joined


def test_config_menu_updates_default_smtp(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    inputs = make_input(["3", "mail.gmx.com", "465", "", "0"])
    output = []

    cli.manage_config(config_path, inputs, output.append)

    config = config_manager.load_config(config_path)
    assert config["smtp"] == {"host": "mail.gmx.com", "port": 465, "use_ssl": True}
    assert any("默认SMTP已保存" in line for line in output)
    joined = "\n".join(output)
    assert "步骤 1/3: 填写SMTP服务器" in joined
    assert "提示：这是邮箱服务商给出的SMTP服务器地址" in joined
    assert "步骤 2/3: 填写SMTP端口" in joined
    assert "步骤 3/3: 选择安全连接" in joined


def test_config_menu_can_clear_license(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    write_config(config_path)
    config = config_manager.load_config(config_path)
    config["license"]["code"] = "IM-AAAAAA-BBBBBB-CCCCCC-DDDDDD"
    config_manager.save_config(config_path, config)
    inputs = make_input(["6", "DELETE", "0"])
    output = []

    cli.manage_config(config_path, inputs, output.append)

    assert config_manager.load_config(config_path)["license"]["code"] == ""
    assert any("授权码已清空" in line for line in output)
