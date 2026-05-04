# -*- coding: utf-8 -*-

from __future__ import annotations

import builtins
import getpass
import os
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from ironmail import config_manager, mailer, templates


InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]
BACK_COMMAND = "0"
PANEL_WIDTH = 72
CLEAR_SCREEN_SEQUENCE = "\033[2J\033[3J\033[H"


def run_console(
    config_path: Path,
    start_send: Callable[[], None],
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
    license_verified: bool = False,
) -> None:
    """运行终端主菜单"""
    while True:
        config = config_manager.load_config(config_path)
        clear_screen(input_func, print_func, force=True)
        show_main_menu(config, print_func, license_verified)
        choice = input_func("请选择功能: ").strip()
        if choice == "1":
            clear_screen(input_func, print_func, force=True)
            start_send()
            pause_after_action(input_func, print_func)
        elif choice == "2":
            manage_senders(config_path, input_func, print_func)
        elif choice == "3":
            clear_screen(input_func, print_func)
            manage_send_settings(config_path, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "4":
            clear_screen(input_func, print_func)
            manage_license(config_path, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "5":
            manage_templates(config_path, input_func, print_func)
        elif choice == "6":
            manage_config(config_path, input_func, print_func)
        elif choice == "0":
            print_func("已退出。")
            return
        else:
            print_func("请输入菜单里的数字。")


def show_main_menu(
    config: dict[str, Any],
    print_func: PrintFunc,
    license_verified: bool = False,
) -> None:
    """展示主菜单"""
    sender_count = len(config_manager.active_senders(config))
    settings = config.get("settings", {})
    license_code = config.get("license", {}).get("code")
    if license_verified:
        license_status = "本次已验证"
    else:
        license_status = "已填写授权码" if license_code else "未填写授权码"
    panel_lines = [
        f"授权状态  {license_status}",
        f"发件邮箱  {sender_count} 个可用",
        (
            f"发送策略  每个邮箱连续 {settings.get('emails_per_account', 1)} 封后切换，"
            f"间隔 {settings.get('delay_seconds', 12)} 秒"
        ),
        "",
    ]
    if sender_count == 0:
        panel_lines.append("下一步  进入 2 管理发件邮箱，添加 Gmail、GMX 或其他SMTP邮箱。")
        panel_lines.append("")
    panel_lines.extend(
        [
            "1. 开始发送邮件",
            "2. 管理发件邮箱",
            "3. 调整发送设置",
            "4. 设置授权码",
            "5. 管理邮件模板",
            "6. 配置",
            "0. 退出",
        ]
    )
    print_panel("IronMail 控制台", panel_lines, print_func)


def manage_senders(config_path: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """运行发件邮箱管理菜单"""
    while True:
        config = config_manager.load_config(config_path)
        clear_screen(input_func, print_func)
        print_header("发件邮箱管理", print_func)
        print_func("说明: 支持 Gmail、GMX、Google Workspace 和其他标准 SMTP 邮箱。")
        print_func("提示: Gmail 需要应用专用密码；GMX 请使用邮箱的SMTP密码或应用密码。")
        print_menu(
            [
                ("1", "查看发件邮箱"),
                ("2", "新增发件邮箱"),
                ("3", "修改发件邮箱"),
                ("4", "删除发件邮箱"),
                ("5", "测试单个SMTP登录"),
                ("6", "测试全部SMTP登录"),
                ("0", "返回主菜单"),
            ],
            print_func,
        )
        choice = input_func("请选择功能: ").strip()
        if choice == "1":
            clear_screen(input_func, print_func)
            print_header("查看发件邮箱", print_func)
            list_senders(config, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "2":
            clear_screen(input_func, print_func)
            add_sender_interactive(config_path, config, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "3":
            clear_screen(input_func, print_func)
            edit_sender_interactive(config_path, config, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "4":
            clear_screen(input_func, print_func)
            delete_sender_interactive(config_path, config, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "5":
            clear_screen(input_func, print_func)
            test_sender_interactive(config, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "6":
            clear_screen(input_func, print_func)
            test_all_senders_interactive(config, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "0":
            return
        else:
            print_func("请输入菜单里的数字。")


def list_senders(config: dict[str, Any], print_func: PrintFunc) -> None:
    """展示已配置发件邮箱"""
    senders = config.get("senders", [])
    if not senders:
        print_func("暂无发件邮箱。")
        return
    print_func("序号  邮箱地址                         显示名称        SMTP")
    print_func("-" * 78)
    for index, sender in enumerate(senders, 1):
        masked = config_manager.mask_sender(sender)
        smtp = config_manager.resolve_sender_smtp(config, sender)
        print_func(
            f"{index:<4}  {masked['email']:<30}  {masked.get('name') or '-':<12}  "
            f"{smtp['host']}:{smtp['port']}"
        )
        print_func(f"      密码: {masked.get('password') or '-'}")


def add_sender_interactive(
    config_path: Path,
    config: dict[str, Any],
    input_func: InputFunc,
    print_func: PrintFunc,
) -> None:
    """交互式新增发件邮箱"""
    print_header("新增发件邮箱", print_func)
    print_smtp_setup_guide(print_func)
    email = input_func("邮箱地址，输入0返回上一层: ").strip()
    if is_back_command(email):
        print_returned(print_func)
        return
    name = input_func("显示名称，直接回车则使用邮箱地址，输入0返回上一层: ").strip()
    if is_back_command(name):
        print_returned(print_func)
        return
    password = read_password("应用专用密码/SMTP密码，输入0返回上一层: ", input_func)
    if is_back_command(password):
        print_returned(print_func)
        return
    if not password:
        print_func("保存失败: 密码不能为空。Gmail 请填写16位应用专用密码，不是网页登录密码。")
        return
    smtp_fields = read_smtp_fields(input_func, print_func, email=email)
    if smtp_fields is None:
        return
    smtp_host, smtp_port, smtp_use_ssl = smtp_fields
    try:
        sender = config_manager.build_sender(
            email=email,
            password=password,
            name=name,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_use_ssl=smtp_use_ssl,
        )
        if not validate_sender_login_before_save(config, sender, print_func):
            return
        config_manager.add_sender(config, sender)
        config_manager.save_config(config_path, config)
        print_func("已保存发件邮箱。")
    except ValueError as error:
        print_func(f"保存失败: {error}")


def edit_sender_interactive(
    config_path: Path,
    config: dict[str, Any],
    input_func: InputFunc,
    print_func: PrintFunc,
) -> None:
    """交互式修改发件邮箱"""
    sender = pick_sender(config, input_func, print_func)
    if not sender:
        return
    print_smtp_setup_guide(print_func)
    print_func("直接回车表示保留原值，输入0返回上一层。")
    name = input_func(f"显示名称 [{sender.get('name') or '-'}]: ").strip()
    if is_back_command(name):
        print_returned(print_func)
        return
    password = read_password("新密码，直接回车保留原密码，输入0返回上一层: ", input_func)
    if is_back_command(password):
        print_returned(print_func)
        return
    smtp_fields = read_smtp_fields(input_func, print_func, sender, sender.get("email", ""))
    if smtp_fields is None:
        return
    smtp_host, smtp_port, smtp_use_ssl = smtp_fields
    updates: dict[str, Any] = {}
    if name:
        updates["name"] = name
    if password:
        updates["password"] = password
    if smtp_host:
        updates["smtp"] = {"host": smtp_host, "port": smtp_port, "use_ssl": smtp_use_ssl}
    try:
        config_manager.update_sender(config, sender["email"], updates)
        config_manager.save_config(config_path, config)
        print_func("已更新发件邮箱。")
    except ValueError as error:
        print_func(f"更新失败: {error}")


def delete_sender_interactive(
    config_path: Path,
    config: dict[str, Any],
    input_func: InputFunc,
    print_func: PrintFunc,
) -> None:
    """交互式删除发件邮箱"""
    sender = pick_sender(config, input_func, print_func)
    if not sender:
        return
    confirm = input_func(f"确认删除 {sender['email']}？输入 DELETE 确认，输入0返回上一层: ").strip()
    if is_back_command(confirm):
        print_returned(print_func)
        return
    if confirm != "DELETE":
        print_func("已取消删除。")
        return
    config_manager.delete_sender(config, sender["email"])
    config_manager.save_config(config_path, config)
    print_func("已删除发件邮箱。")


def test_sender_interactive(config: dict[str, Any], input_func: InputFunc, print_func: PrintFunc) -> None:
    """交互式测试SMTP账号"""
    sender = pick_sender(config, input_func, print_func)
    if not sender:
        return
    test_one_sender(config, sender, print_func)


def test_all_senders_interactive(config: dict[str, Any], print_func: PrintFunc) -> None:
    """测试全部可用SMTP账号"""
    senders = config_manager.active_senders(config)
    if not senders:
        print_func("暂无可测试发件邮箱。请先新增邮箱并填写密码。")
        return
    success_count = 0
    fail_count = 0
    workers = min(64, len(senders))
    print_header("测试全部SMTP登录", print_func)
    print_func(f"并发测试: {workers}并发")
    jobs = [(index, len(senders), sender) for index, sender in enumerate(senders, 1)]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(lambda job: smtp_test_result(config, job), jobs))
    for index, total, sender, smtp, ok, error in results:
        print_func(f"[{index}/{total}] {sender['email']}")
        print_func(f"正在测试 {sender['email']} -> {smtp['host']}:{smtp['port']} ...")
        if ok:
            print_func("SMTP登录成功。")
            success_count += 1
        else:
            fail_count += 1
            print_func(f"SMTP登录失败: {error}")
            print_func(smtp_failure_hint(error))
    print_func(f"测试完成：成功 {success_count} 个，失败 {fail_count} 个")


def smtp_test_result(config: dict[str, Any], job: tuple[int, int, dict[str, Any]]):
    """执行单个SMTP登录测试并返回结果。"""
    index, total, sender = job
    smtp = config_manager.resolve_sender_smtp(config, sender)
    smtp["proxy"] = config.get("smtp_proxy", {})
    try:
        mailer.test_smtp_login(smtp, sender)
        return index, total, sender, smtp, True, None
    except Exception as error:
        return index, total, sender, smtp, False, error


def test_one_sender(config: dict[str, Any], sender: dict[str, Any], print_func: PrintFunc) -> bool:
    """测试单个SMTP账号"""
    smtp = config_manager.resolve_sender_smtp(config, sender)
    smtp["proxy"] = config.get("smtp_proxy", {})
    print_func(f"正在测试 {sender['email']} -> {smtp['host']}:{smtp['port']} ...")
    try:
        mailer.test_smtp_login(smtp, sender)
        print_func("SMTP登录成功。")
        return True
    except Exception as error:
        print_func(f"SMTP登录失败: {error}")
        print_func(smtp_failure_hint(error))
        return False


def manage_templates(config_path: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """运行邮件模板管理菜单。"""
    template_dir = template_dir_from_config(config_path)
    while True:
        clear_screen(input_func, print_func)
        print_header("邮件模板管理", print_func)
        print_func(f"模板目录: {template_dir}")
        print_menu(
            [
                ("1", "查看模板"),
                ("2", "新增模板"),
                ("3", "打开/修改模板"),
                ("4", "删除模板"),
                ("0", "返回主菜单"),
            ],
            print_func,
        )
        choice = input_func("请选择功能: ").strip()
        if choice == "1":
            list_templates(template_dir, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "2":
            create_template_interactive(template_dir, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "3":
            open_template_interactive(template_dir, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "4":
            delete_template_interactive(template_dir, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "0":
            return
        else:
            print_func("请输入菜单里的数字。")


def template_dir_from_config(config_path: Path) -> Path:
    """按配置文件位置推导邮件模板目录。"""
    return config_path.resolve().parent.parent / "Mails" / "邮件模板"


def list_templates(template_dir: Path, print_func: PrintFunc) -> list[Path]:
    """展示邮件模板列表和完整内容。"""
    try:
        files = templates.list_template_files(template_dir)
    except FileNotFoundError:
        print_func("暂无模板目录，新增模板时会自动创建。")
        return []
    if not files:
        print_func("暂无邮件模板。")
        return []
    print_func("序号  模板文件")
    print_func("-" * 72)
    for index, file_path in enumerate(files, 1):
        print_func(f"{index:<4}  {file_path.name}")
        print_func("-" * 72)
        print_func(file_path.read_text(encoding="utf-8-sig").rstrip())
        print_func("-" * 72)
    return files


def create_template_interactive(template_dir: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """交互式新增邮件模板。"""
    name = input_func("模板名称，输入0返回上一层: ").strip()
    if is_back_command(name):
        print_returned(print_func)
        return
    try:
        template_path = templates.create_template_file(template_dir, name)
    except (ValueError, FileExistsError) as error:
        print_func(f"创建失败: {error}")
        return
    print_func(f"已创建模板: {template_path.name}")
    print_func("已写入“邮件主题：”和“邮件正文：”，打开后直接填写内容。")
    open_template_file(template_path)


def open_template_interactive(template_dir: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """选择并打开邮件模板。"""
    template_path = pick_template(template_dir, input_func, print_func)
    if not template_path:
        return
    open_template_file(template_path)
    print_func(f"已打开模板: {template_path.name}")


def delete_template_interactive(template_dir: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """选择并删除邮件模板。"""
    template_path = pick_template(template_dir, input_func, print_func)
    if not template_path:
        return
    confirm = input_func(f"确认删除 {template_path.name}？输入 DELETE 确认，输入0返回上一层: ").strip()
    if is_back_command(confirm):
        print_returned(print_func)
        return
    if confirm != "DELETE":
        print_func("已取消删除。")
        return
    template_path.unlink()
    print_func("已删除模板。")


def pick_template(template_dir: Path, input_func: InputFunc, print_func: PrintFunc) -> Path | None:
    """让用户选择一个模板文件。"""
    files = list_templates(template_dir, print_func)
    if not files:
        return None
    raw_index = input_func("请输入模板序号，输入0返回上一层: ").strip()
    if is_back_command(raw_index):
        print_returned(print_func)
        return None
    try:
        index = int(raw_index)
    except ValueError:
        print_func("序号必须是数字。")
        return None
    if index < 1 or index > len(files):
        print_func("序号超出范围。")
        return None
    return files[index - 1]


def open_template_file(template_path: Path) -> None:
    """用系统默认编辑器打开模板文件。"""
    if sys.platform.startswith("win"):
        os.startfile(template_path)  # type: ignore[attr-defined]
        return
    command = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([command, str(template_path)])


def validate_sender_login_before_save(
    config: dict[str, Any],
    sender: dict[str, Any],
    print_func: PrintFunc,
) -> bool:
    """保存发件邮箱前强制验证SMTP登录"""
    print_func("正在验证SMTP登录，测试通过后才会保存...")
    if test_one_sender(config, sender, print_func):
        print_func("SMTP登录测试通过，正在保存发件邮箱。")
        return True
    print_func("保存失败: SMTP登录测试未通过，请检查邮箱、应用专用密码和SMTP配置。")
    return False


def pick_sender(
    config: dict[str, Any],
    input_func: InputFunc,
    print_func: PrintFunc,
) -> dict[str, Any] | None:
    """让用户选择一个发件邮箱"""
    senders = config.get("senders", [])
    if not senders:
        print_func("暂无发件邮箱。")
        return None
    list_senders(config, print_func)
    raw_index = input_func("请输入邮箱序号，输入0返回上一层: ").strip()
    if is_back_command(raw_index):
        print_returned(print_func)
        return None
    try:
        index = int(raw_index)
    except ValueError:
        print_func("序号必须是数字。")
        return None
    if index < 1 or index > len(senders):
        print_func("序号超出范围。")
        return None
    return senders[index - 1]


def read_smtp_fields(
    input_func: InputFunc,
    print_func: PrintFunc,
    sender: dict[str, Any] | None = None,
    email: str = "",
) -> tuple[str, int, bool] | None:
    """读取SMTP配置，按邮箱域名给出常用默认值。"""
    current_smtp = sender.get("smtp", {}) if sender else {}
    provider_smtp = config_manager.smtp_defaults_for_email(email or str(sender.get("email", "") if sender else ""))
    default_host = current_smtp.get("host") or provider_smtp["host"]
    default_port = int(current_smtp.get("port") or provider_smtp["port"])
    default_ssl = bool(current_smtp.get("use_ssl", provider_smtp["use_ssl"]))
    print_func(f"SMTP配置: 直接回车自动识别为 {default_host}:{default_port} SSL={'开启' if default_ssl else '关闭'}")
    print_func("Gmail、GMX 等常见邮箱会自动带出SMTP；其他邮箱请按服务商后台手动填写。")
    host = input_func(f"SMTP服务器 [{current_smtp.get('host') or '回车自动识别'}]，输入0返回上一层: ").strip()
    if is_back_command(host):
        print_returned(print_func)
        return None
    if not host:
        if provider_smtp == config_manager.DEFAULT_SMTP:
            return "", default_port, default_ssl
        return default_host, default_port, default_ssl
    port_raw = input_func(f"SMTP端口 [{default_port}]: ").strip()
    try:
        port = int(port_raw or default_port)
    except ValueError:
        print_func("SMTP端口必须是数字，本次使用默认端口 465。")
        port = 465
    default_ssl_label = "Y" if default_ssl else "N"
    ssl_raw = input_func(f"是否使用SSL？Y/N [{default_ssl_label}]: ").strip().upper()
    use_ssl = default_ssl if not ssl_raw else ssl_raw != "N"
    return host, port, use_ssl


def read_password(prompt: str, input_func: InputFunc) -> str:
    """读取密码，真实终端下隐藏输入，测试场景可注入input"""
    if input_func is input:
        return getpass.getpass(prompt)
    return input_func(prompt)


def manage_config(config_path: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """运行配置管理菜单。"""
    while True:
        config = config_manager.load_config(config_path)
        clear_screen(input_func, print_func)
        print_header("配置", print_func)
        print_menu(
            [
                ("1", "查看当前配置"),
                ("2", "修改发送设置"),
                ("3", "修改默认SMTP"),
                ("4", "修改SMTP出网"),
                ("5", "设置/新增授权码"),
                ("6", "删除授权码"),
                ("0", "返回主菜单"),
            ],
            print_func,
        )
        choice = input_func("请选择功能: ").strip()
        if choice == "1":
            show_config_summary(config, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "2":
            manage_send_settings(config_path, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "3":
            manage_default_smtp(config_path, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "4":
            manage_smtp_proxy(config_path, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "5":
            manage_license(config_path, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "6":
            clear_license_interactive(config_path, input_func, print_func)
            pause_after_action(input_func, print_func)
        elif choice == "0":
            return
        else:
            print_func("请输入菜单里的数字。")


def manage_default_smtp(config_path: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """修改全局默认SMTP配置。"""
    config = config_manager.load_config(config_path)
    smtp = config.get("smtp", {})
    print_header("修改默认SMTP", print_func)
    print_func("直接回车表示保留原值，输入0返回上一层。")
    host = input_func(f"SMTP服务器 [{smtp.get('host') or 'smtp.gmail.com'}]: ").strip()
    if is_back_command(host):
        print_returned(print_func)
        return
    port_raw = input_func(f"SMTP端口 [{smtp.get('port') or 465}]: ").strip()
    if is_back_command(port_raw):
        print_returned(print_func)
        return
    ssl_raw = input_func(f"是否使用SSL？Y/N [{'Y' if smtp.get('use_ssl', True) else 'N'}]: ").strip().upper()
    if is_back_command(ssl_raw):
        print_returned(print_func)
        return
    updated = dict(smtp)
    if host:
        updated["host"] = host
    if port_raw:
        updated["port"] = int(port_raw)
    if ssl_raw:
        updated["use_ssl"] = ssl_raw != "N"
    config["smtp"] = config_manager.normalize_smtp(updated)
    config_manager.save_config(config_path, config)
    print_func("默认SMTP已保存。")


def manage_smtp_proxy(config_path: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """修改SMTP出网配置。"""
    config = config_manager.load_config(config_path)
    proxy = config.get("smtp_proxy", {})
    print_header("修改SMTP出网", print_func)
    print_func("模式说明: auto=先直连失败再试代理，direct=只直连，proxy=只走代理。")
    mode = input_func(f"出网模式 auto/direct/proxy [{proxy.get('mode') or 'auto'}]: ").strip().lower()
    if is_back_command(mode):
        print_returned(print_func)
        return
    host = input_func(f"代理地址 [{proxy.get('host') or '127.0.0.1'}]: ").strip()
    if is_back_command(host):
        print_returned(print_func)
        return
    port_raw = input_func(f"主代理端口 [{proxy.get('port') or 7897}]: ").strip()
    if is_back_command(port_raw):
        print_returned(print_func)
        return
    updated = dict(proxy)
    if mode:
        updated["mode"] = mode
    if host:
        updated["host"] = host
    if port_raw:
        updated["port"] = int(port_raw)
    config["smtp_proxy"] = config_manager.normalize_smtp_proxy(updated)
    config_manager.save_config(config_path, config)
    print_func("SMTP出网配置已保存。")


def clear_license_interactive(config_path: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """清空本地授权码。"""
    config = config_manager.load_config(config_path)
    current = config.get("license", {}).get("code") or "未填写"
    print_header("删除授权码", print_func)
    print_func(f"当前授权码: {current}")
    confirm = input_func("确认清空授权码？输入 DELETE 确认，输入0返回上一层: ").strip()
    if is_back_command(confirm):
        print_returned(print_func)
        return
    if confirm != "DELETE":
        print_func("已取消删除。")
        return
    config.setdefault("license", {})["code"] = ""
    config_manager.save_config(config_path, config)
    print_func("授权码已清空。")


def manage_send_settings(config_path: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """调整发送参数"""
    config = config_manager.load_config(config_path)
    settings = config["settings"]
    print_header("调整发送设置", print_func)
    print_func("直接回车表示保留原值，输入0返回上一层。")
    emails_per_account = input_func(
        f"每个邮箱连续发送几封后切换 [{settings.get('emails_per_account', 1)}]: "
    ).strip()
    if is_back_command(emails_per_account):
        print_returned(print_func)
        return
    delay_seconds = input_func(f"每封邮件间隔秒数 [{settings.get('delay_seconds', 12)}]: ").strip()
    if is_back_command(delay_seconds):
        print_returned(print_func)
        return
    max_retries = input_func(f"失败重试次数 [{settings.get('max_retries', 3)}]: ").strip()
    if is_back_command(max_retries):
        print_returned(print_func)
        return
    if emails_per_account:
        settings["emails_per_account"] = max(1, int(emails_per_account))
    if delay_seconds:
        settings["delay_seconds"] = max(0, int(delay_seconds))
    if max_retries:
        settings["max_retries"] = max(1, int(max_retries))
    config_manager.save_config(config_path, config)
    print_func("发送设置已保存。")


def manage_license(config_path: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """设置客户端授权码"""
    config = config_manager.load_config(config_path)
    current = config.get("license", {}).get("code") or "未填写"
    print_header("设置授权码", print_func)
    print_func(f"当前授权码: {current}")
    code = input_func("请输入新的授权码，直接回车则不修改，输入0返回上一层: ").strip()
    if is_back_command(code):
        print_returned(print_func)
        return
    if code:
        config.setdefault("license", {})["code"] = code
        config_manager.save_config(config_path, config)
        print_func("授权码已保存。")


def show_config_summary(config: dict[str, Any], print_func: PrintFunc) -> None:
    """展示当前关键配置"""
    smtp = config.get("smtp", {})
    settings = config.get("settings", {})
    license_code = config.get("license", {}).get("code") or "未填写"
    print_header("当前配置", print_func)
    print_func(f"默认SMTP: {smtp.get('host')}:{smtp.get('port')} SSL={'开启' if smtp.get('use_ssl') else '关闭'}")
    print_func(f"授权码: {license_code}")
    print_func(f"每个邮箱发送封数: {settings.get('emails_per_account')}")
    print_func(f"发送间隔: {settings.get('delay_seconds')} 秒")
    print_func(f"失败重试: {settings.get('max_retries')} 次")
    list_senders(config, print_func)


def print_header(title: str, print_func: PrintFunc) -> None:
    """打印统一页头"""
    print_func("\n" + "=" * 72)
    print_func(title)
    print_func("=" * 72)


def print_menu(items: list[tuple[str, str]], print_func: PrintFunc) -> None:
    """打印统一菜单"""
    print_func("")
    for key, label in items:
        print_func(f"  {key}. {label}")


def print_panel(title: str, lines: list[str], print_func: PrintFunc) -> None:
    """打印统一控制面板"""
    inner_width = PANEL_WIDTH - 4
    print_func("┌" + "─" * (PANEL_WIDTH - 2) + "┐")
    print_func(panel_line(title, inner_width))
    print_func("├" + "─" * (PANEL_WIDTH - 2) + "┤")
    for line in lines:
        print_func(panel_line(line, inner_width))
    print_func("└" + "─" * (PANEL_WIDTH - 2) + "┘")


def panel_line(text: str, inner_width: int) -> str:
    """格式化面板单行文本"""
    visible_width = display_width(text)
    padding = max(0, inner_width - visible_width)
    return f"│ {text}{' ' * padding} │"


def display_width(text: str) -> int:
    """计算终端里的可见宽度"""
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def print_smtp_setup_guide(print_func: PrintFunc) -> None:
    """打印发件邮箱配置指引。"""
    print_func("Gmail填写说明:")
    print_func("- 邮箱地址: 填 Gmail 邮箱，例如 yourname@gmail.com")
    print_func("- 密码: 填 Google 生成的16位应用专用密码，不是网页登录密码")
    print_func("- 准备步骤: 先开启 Google 两步验证，再访问 https://myaccount.google.com/apppasswords 生成应用专用密码")
    print_func("- SMTP服务器: 直接回车，系统会自动使用 smtp.gmail.com:465 SSL")
    print_func("")
    print_func("GMX填写说明:")
    print_func("- 邮箱地址: 填 GMX 邮箱，例如 yourname@gmx.com")
    print_func("- 密码: 填 GMX 可用于SMTP的密码或应用密码")
    print_func("- SMTP服务器: 直接回车，系统会自动使用 mail.gmx.com:465 SSL")
    print_func("- 端口说明: 465 是 SSL；587 是 STARTTLS，默认先用 465")
    print_func("")


def is_back_command(value: str) -> bool:
    """判断用户是否选择返回上一层。"""
    return value.strip() == BACK_COMMAND


def print_returned(print_func: PrintFunc) -> None:
    """统一提示已返回上一层。"""
    print_func("已返回上一层。")


def smtp_failure_hint(error: Exception) -> str:
    """根据SMTP错误给出面向用户的排查提示。"""
    text = str(error).lower()
    if "username and password" in text or "authentication" in text or "535" in text:
        return (
            "排查建议: 登录失败通常是密码填错、没有开启SMTP/应用密码，"
            "或填了网页登录密码。Gmail 请先开启两步验证并使用16位应用专用密码，"
            "GMX 请确认SMTP密码可用。"
        )
    if (
        "timed out" in text
        or "timeout" in text
        or "network" in text
        or "connection refused" in text
        or "代理端口" in text
    ):
        return (
            "排查建议: 当前网络到SMTP服务器不稳定。程序会自动尝试本机代理端口，"
            "仍失败时请确认网络能访问对应SMTP服务器，例如 smtp.gmail.com 或 mail.gmx.com。"
        )
    if "certificate" in text or "ssl" in text:
        return "排查建议: SSL连接失败，请确认SMTP端口为465且SSL开启。"
    return (
        "排查建议: 请先确认邮箱地址、SMTP密码、SMTP服务器和端口是否正确；"
        "Gmail默认是 smtp.gmail.com:465 SSL，GMX默认是 mail.gmx.com:465 SSL。"
    )


def clear_screen(input_func: InputFunc, print_func: PrintFunc, force: bool = False) -> None:
    """真实终端下清屏，测试注入输入时不输出控制字符。"""
    if force and is_builtin_console(input_func, print_func):
        emit_clear_sequence(print_func)
        return
    if not is_real_terminal(input_func, print_func):
        return
    emit_clear_sequence(print_func)


def emit_clear_sequence(print_func: PrintFunc) -> None:
    """输出清屏并清除滚动历史的控制符。"""
    print_func(CLEAR_SCREEN_SEQUENCE, end="")
    sys.stdout.flush()


def pause_after_action(input_func: InputFunc, print_func: PrintFunc) -> None:
    """真实终端下停留结果页，避免用户看不清结果。"""
    if not is_real_terminal(input_func, print_func):
        return
    input_func("\n按回车返回菜单...")


def is_real_terminal(input_func: InputFunc, print_func: PrintFunc) -> bool:
    """判断是否是正常命令行交互，不影响测试注入。"""
    return is_builtin_console(input_func, print_func) and sys.stdin.isatty() and sys.stdout.isatty()


def is_builtin_console(input_func: InputFunc, print_func: PrintFunc) -> bool:
    """判断是否使用系统默认输入输出函数。"""
    return input_func is builtins.input and print_func is builtins.print
