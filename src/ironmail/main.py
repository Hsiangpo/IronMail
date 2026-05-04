# -*- coding: utf-8 -*-
"""
批量邮件发送脚本
支持多个SMTP邮箱轮换发送
"""

from __future__ import annotations

import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from ironmail import cli, config_manager, mailer, recipient_lists, send_progress, templates
from ironmail.license import verify_license

# 设置SSL证书路径（修复Windows上的证书问题）
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
except ImportError:
    pass

# 多语言敏感词列表（欺诈、诈骗相关）
SENSITIVE_WORDS = {
    # 中文
    '欺诈', '诈骗', '骗局', '传销', '洗钱', '非法集资', '赌博', '色情',
    '钓鱼', '黑客', '病毒', '木马', '勒索', '假冒', '伪造', '走私',
    '贩毒', '恐怖', '暴力', '枪支', '军火', '假币', '信用卡盗刷',
    '账号盗取', '密码窃取', '身份盗用', '虚假中奖', '刷单返利',

    # 英文
    'fraud', 'scam', 'phishing', 'money laundering', 'pyramid scheme',
    'illegal', 'hack', 'virus', 'malware', 'ransomware', 'counterfeit',
    'smuggling', 'drug trafficking', 'terrorism', 'violence', 'gambling',
    'pornography', 'identity theft', 'credit card fraud', 'fake lottery',
    'get rich quick', 'nigerian prince', 'advance fee',

    # 日文
    '詐欺', '詐取', 'フィッシング', 'マネーロンダリング', 'ねずみ講',
    '違法', 'ハッキング', 'ウイルス', 'マルウェア', '偽造', '密輸',
    '麻薬', 'テロ', '暴力', 'ギャンブル', 'ポルノ', '身分詐称',
    '架空請求', 'ワンクリック詐欺', '振り込め詐欺',

    # 德文
    'betrug', 'betrügerisch', 'phishing', 'geldwäsche', 'schneeballsystem',
    'illegal', 'hacking', 'virus', 'malware', 'fälschung', 'schmuggel',
    'drogenhandel', 'terrorismus', 'gewalt', 'glücksspiel', 'pornografie',
    'identitätsdiebstahl', 'kreditkartenbetrug', 'vorschussbetrug',

    # 韩文
    '사기', '피싱', '자금세탁', '다단계', '불법', '해킹', '바이러스',
    '악성코드', '랜섬웨어', '위조', '밀수', '마약', '테러', '폭력',
    '도박', '포르노', '신분도용', '보이스피싱', '스미싱',
}


RECIPIENT_DIR_NAME = recipient_lists.RECIPIENT_DIR_NAME
TEMPLATE_DIR_NAME = "邮件模板"
LEGACY_TEMPLATE_DIR_NAME = "模板"
REQUIRED_WITH_TEMPLATE = ["邮箱"]
REQUIRED_WITHOUT_TEMPLATE = ["邮箱", "邮件主题", "邮件正文"]
AUTH_PANEL_WIDTH = 72
CHOICE_CANCEL = "__IRONMAIL_CANCEL__"


def log_message(log_file: str, message: str):
    """写入日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}\n"
    print(log_entry.strip())
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_entry)


def format_send_error(error: Exception) -> str:
    """把常见发信错误转成更容易判断的中文提示。"""
    raw = str(error)
    text = raw.lower()
    if "policy restrictions" in text and "postmaster.gmx.net" in text:
        ip = extract_gmx_policy_ip(raw)
        if ip:
            return f"GMX拒收本次发信：当前出网IP {ip} 被GMX策略限制。程序会尝试切换其他发件邮箱。"
        return "GMX拒收本次发信：服务商返回策略限制。程序会尝试切换其他发件邮箱。"
    return raw


def extract_gmx_policy_ip(message: str) -> str:
    """从GMX错误链接里提取被拦截的出网IP。"""
    match = re.search(r"[?&]v=([0-9a-fA-F:.]+)", message)
    return match.group(1) if match else ""


def check_sensitive_words(text: str) -> Tuple[bool, str]:
    """
    检查文本是否包含敏感词
    返回: (是否包含敏感词, 匹配到的敏感词)
    """
    text_lower = text.lower()
    for word in SENSITIVE_WORDS:
        if word.lower() in text_lower:
            return True, word
    return False, ""


def scan_all_emails(df: pd.DataFrame) -> List[int]:
    """
    扫描所有邮件内容，检查敏感词
    返回: [包含问题内容的行号, ...]
    """
    violations = []
    for index, row in df.iterrows():
        subject = str(row.get('邮件主题', '')).strip()
        body = str(row.get('邮件正文', '')).strip()

        # 检查主题和正文
        has_sensitive_subject, _ = check_sensitive_words(subject)
        has_sensitive_body, _ = check_sensitive_words(body)

        if has_sensitive_subject or has_sensitive_body:
            violations.append(index + 1)

    return violations


def get_app_dir() -> Path:
    """获取项目根目录，兼容源码运行和打包后的exe"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def list_data_files(data_dir: Path) -> list[Path]:
    """列出Mails文件夹里的表格文件"""
    data_dir = resolve_recipient_dir_from_mails(data_dir)
    return recipient_lists.list_recipient_files(data_dir)


def find_data_file(data_dir: Path) -> Path:
    """自动查找Mails文件夹里的表格文件"""
    data_files = list_data_files(data_dir)
    if data_files:
        return data_files[0]
    raise FileNotFoundError(f"未找到表格文件，请将 .xlsx、.xlsm、.xls 或 .csv 放入 {data_dir}")


def get_mails_dir(app_dir: Path) -> Path:
    """获取邮件工作目录。"""
    return app_dir / 'Mails'


def get_recipient_dir(app_dir: Path) -> Path:
    """获取收件名单目录，兼容并迁移旧目录名。"""
    return recipient_lists.ensure_recipient_dir(app_dir)


def get_template_dir(app_dir: Path) -> Path:
    """获取邮件模板目录，兼容旧目录名。"""
    mails_dir = get_mails_dir(app_dir)
    preferred = mails_dir / TEMPLATE_DIR_NAME
    legacy = mails_dir / LEGACY_TEMPLATE_DIR_NAME
    if preferred.exists():
        return preferred
    if legacy.exists():
        return legacy
    return preferred


def resolve_recipient_dir_from_mails(data_dir: Path) -> Path:
    """传入Mails目录时自动转到收件名单子目录。"""
    return recipient_lists.resolve_recipient_dir_from_mails(data_dir)


def resolve_data_file(app_dir: Path, excel_file: str) -> Path:
    """解析表格路径，所有相对路径都固定从Mails文件夹读取"""
    mails_dir = get_mails_dir(app_dir)
    data_dir = get_recipient_dir(app_dir)
    if not excel_file:
        return find_data_file(data_dir)

    configured_path = Path(excel_file)
    if configured_path.is_absolute():
        data_path = configured_path
    elif configured_path.parts and configured_path.parts[0] == 'Mails':
        data_path = app_dir / configured_path
    else:
        data_path = data_dir / configured_path

    if not data_path.resolve().is_relative_to(mails_dir.resolve()):
        raise ValueError(f"表格文件必须放在Mails文件夹内: {data_path}")

    return data_path


def choose_data_file(app_dir: Path, excel_file: Optional[str] = None) -> Path | None:
    """选择本次发送要使用的表格"""
    data_dir = get_recipient_dir(app_dir)
    if excel_file:
        return resolve_data_file(app_dir, excel_file)

    data_files = list_data_files(data_dir)
    if not data_files:
        raise FileNotFoundError(f"未找到表格文件，请将 .xlsx、.xlsm、.xls 或 .csv 放入 {data_dir}")

    cli.clear_screen(input, print)
    print_selection_panel("选择收件人表格", ["0. 返回主菜单"] + format_file_choices(data_files))
    while True:
        raw_choice = input("请输入表格序号，输入0返回主菜单: ").strip()
        try:
            choice = int(raw_choice)
        except ValueError:
            print("请输入数字序号。")
            continue
        if choice == 0:
            print("已返回主菜单。")
            return None
        if 1 <= choice <= len(data_files):
            return data_files[choice - 1]
        print("序号超出范围，请重新输入。")


def read_data_file(file_path: Path) -> pd.DataFrame:
    """根据文件类型读取数据"""
    return recipient_lists.read_table(file_path)


def choose_template_file(app_dir: Path, allow_table_fields: bool) -> Path | str | None:
    """选择本次发送要使用的邮件模板。"""
    template_dir = get_template_dir(app_dir)
    try:
        template_files = templates.list_template_files(template_dir)
    except FileNotFoundError:
        if allow_table_fields:
            print("未找到邮件模板文件夹，将使用表格里的邮件主题和邮件正文。")
            return None
        raise
    if not template_files:
        if allow_table_fields:
            print("未找到.md邮件模板，将使用表格里的邮件主题和邮件正文。")
            return None
        raise FileNotFoundError(f"未找到.md邮件模板，请将模板放入 {template_dir}")

    cli.clear_screen(input, print)
    choices = ["0. 返回主菜单"]
    if allow_table_fields:
        choices.append("N. 不使用模板，使用表格里的邮件主题和邮件正文")
    choices.extend(format_file_choices(template_files))
    print_selection_panel("选择邮件模板", choices)

    while True:
        raw_choice = input("请输入模板序号，输入0返回主菜单: ").strip()
        if allow_table_fields and raw_choice.upper() == "N":
            return None
        try:
            choice = int(raw_choice)
        except ValueError:
            print("请输入数字序号。")
            continue
        if choice == 0:
            return CHOICE_CANCEL if allow_table_fields else None
        if 1 <= choice <= len(template_files):
            return template_files[choice - 1]
        print("序号超出范围，请重新输入。")


def print_selection_panel(title: str, lines: list[str]) -> None:
    """打印发送流程里的选择面板"""
    print("")
    cli.print_panel(title, lines, print)


def format_file_choices(files: list[Path]) -> list[str]:
    """格式化文件选择列表"""
    choices = []
    for index, file_path in enumerate(files, 1):
        stat = file_path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        size_kb = max(1, round(stat.st_size / 1024))
        choices.append(f"{index}. {file_path.name} | {size_kb} KB | 修改时间 {modified}")
    return choices


def validate_email_dataframe(df: pd.DataFrame, use_template: bool) -> list[str]:
    """检查发送所需字段是否齐全。"""
    required = REQUIRED_WITH_TEMPLATE if use_template else REQUIRED_WITHOUT_TEMPLATE
    missing = [column for column in required if column not in df.columns]
    if missing:
        return [f"缺少必需字段: {', '.join(missing)}"]
    return []


def apply_selected_template(app_dir: Path, df: pd.DataFrame) -> tuple[pd.DataFrame, Path | None] | None:
    """选择模板并渲染邮件主题和正文。"""
    has_table_content = {"邮件主题", "邮件正文"}.issubset(df.columns)
    template_path = choose_template_file(app_dir, allow_table_fields=has_table_content)
    if template_path == CHOICE_CANCEL or (template_path is None and not has_table_content):
        print("已返回主菜单。")
        return None
    if not template_path:
        return df, None

    try:
        email_template = templates.parse_template_file(template_path)
    except ValueError as error:
        print(f"模板格式错误: {error}")
        return None

    missing_columns = templates.find_missing_template_columns(email_template, df)
    if missing_columns:
        print("模板变量检查未通过。")
        print(f"模板使用了这些字段，但对象表里没有: {', '.join(missing_columns)}")
        return None
    return templates.apply_template_to_dataframe(df, email_template), template_path


def print_dataframe_errors(errors: list[str]) -> None:
    """打印表格检查错误。"""
    if not errors:
        return
    print("\n" + "=" * 60)
    print("表格检查未通过")
    print("=" * 60)


def prepare_send_progress(
    app_dir: Path,
    data_path: Path,
    template_path: Path | None,
    total_rows: int,
) -> dict | None:
    """读取断点续发状态，并让用户确认继续或重发。"""
    state = send_progress.load_progress(app_dir, data_path, template_path)
    completed, total = send_progress.progress_summary(state, total_rows)
    if completed == 0:
        return state

    print("\n" + "=" * 60)
    print("检测到断点续发记录")
    print("=" * 60)
    print(f"已完成: {completed}/{total}")
    print(f"进度文件: {state['path']}")
    if completed >= total:
        return handle_completed_progress(state)
    return handle_partial_progress(state)


def handle_completed_progress(state: dict) -> dict | None:
    """处理已经全部完成的发送记录。"""
    while True:
        choice = input("这组名单上次已全部发送完成。输入 Y 重新发送 / N 返回菜单: ").strip().upper()
        if choice == "Y":
            send_progress.reset_progress(state)
            return state
        if choice == "N":
            print("已取消发送，避免重复发送。")
            return None
        print("请输入 Y 或 N。")


def handle_partial_progress(state: dict) -> dict | None:
    """处理未完成的发送记录。"""
    while True:
        choice = input("输入 Y 继续未完成部分 / R 重新发送全部 / N 返回菜单: ").strip().upper()
        if choice == "Y":
            print("将跳过已成功发送的行，只继续未完成部分。")
            return state
        if choice == "R":
            send_progress.reset_progress(state)
            print("已清空旧进度，本次将重新发送全部。")
            return state
        if choice == "N":
            print("已取消发送。")
            return None
        print("请输入 Y、R 或 N。")
    for error in errors:
        print(error)
    print("=" * 60)


def run_send_flow(app_dir: Path, config_path: Path):
    """执行完整发信流程"""
    cli.clear_screen(input, print)
    print("正在加载配置...")
    config = config_manager.load_config(config_path)

    print("\n" + "=" * 60)

    senders = config_manager.active_senders(config)
    settings = config['settings']
    emails_per_account = settings.get('emails_per_account', 10)

    if not senders:
        print("错误: 未配置有效的发件邮箱，请先在主菜单里管理发件邮箱。")
        return

    # 日志文件路径
    log_file = app_dir / settings['log_file']

    # 选择本次发送使用的表格，统一从Mails文件夹读取
    excel_file = config.get('excel_file')
    data_path = choose_data_file(app_dir, excel_file)
    if data_path is None:
        return

    print(f"正在读取数据文件: {data_path}")
    df = read_data_file(data_path)
    prepared = apply_selected_template(app_dir, df)
    if prepared is None:
        return
    df, template_path = prepared

    errors = validate_email_dataframe(df, use_template=template_path is not None)
    if errors:
        print_dataframe_errors(errors)
        return

    # 敏感词检测
    print("正在进行敏感词检测...")
    violations = scan_all_emails(df)

    if violations:
        print("\n" + "=" * 60)
        print("内容审核未通过")
        print("=" * 60)
        print(f"以下行的邮件内容需要修改: 第 {', '.join(map(str, violations))} 行")
        print("=" * 60)
        print("请检查并修改相关内容后重新运行。")
        return

    print("敏感词检测通过。")

    total = len(df)
    success_count = 0
    fail_count = 0
    resume_skip_count = 0
    send_attempt_count = 0
    progress_state = prepare_send_progress(app_dir, data_path, template_path, total)
    if progress_state is None:
        return

    log_message(log_file, f"========== 开始发送邮件 ==========")
    log_message(log_file, f"共 {total} 封邮件待发送, 使用 {len(senders)} 个邮箱轮换")
    log_message(log_file, f"断点文件: {progress_state['path']}")

    for index, row in df.iterrows():
        recipient_email = str(row['邮箱']).strip()
        subject = str(row['邮件主题']).strip()
        body = str(row['邮件正文']).strip()
        row_key = send_progress.row_key(index, recipient_email)

        if send_progress.is_row_completed(progress_state, row_key):
            resume_skip_count += 1
            log_message(log_file, f"[{index+1}/{total}] 跳过 - 断点记录已完成 -> {recipient_email}")
            continue

        # 跳过空邮箱
        if not recipient_email or recipient_email == 'nan':
            log_message(log_file, f"[{index+1}/{total}] 跳过 - 邮箱为空")
            send_progress.mark_row_completed(progress_state, row_key, "skipped_empty_email")
            continue

        sent = False
        max_retries = int(settings['max_retries'])
        candidates = mailer.sender_candidates(senders, send_attempt_count, emails_per_account)
        for sender_offset, current_sender in enumerate(candidates):
            smtp_config = config_manager.resolve_sender_smtp(config, current_sender)
            smtp_config["proxy"] = config.get("smtp_proxy", {})
            if sender_offset:
                log_message(log_file, f"[{index+1}/{total}] 切换发件邮箱重试 -> {current_sender['email']}")

            # 发送邮件，支持重试；当前邮箱最终失败后再切换下一个邮箱。
            for attempt in range(max_retries):
                try:
                    mailer.send_email(smtp_config, current_sender, recipient_email,
                                      subject, body)
                    success_count += 1
                    send_attempt_count += 1
                    sent = True
                    send_progress.mark_row_completed(progress_state, row_key, "success")
                    log_message(log_file, f"[{index+1}/{total}] 成功 -> {recipient_email} (发件人: {current_sender['email']})")
                    break
                except Exception as e:
                    error_text = format_send_error(e)
                    if attempt < max_retries - 1:
                        log_message(log_file, f"[{index+1}/{total}] 重试 {attempt+1} -> {recipient_email}: {error_text}")
                        time.sleep(2)
                    elif sender_offset < len(candidates) - 1:
                        log_message(log_file, f"[{index+1}/{total}] 发件邮箱 {current_sender['email']} 不可用，准备切换: {error_text}")
                    else:
                        fail_count += 1
                        log_message(log_file, f"[{index+1}/{total}] 失败 -> {recipient_email}: {error_text}")
            if sent:
                break

        # 发送间隔
        if index < total - 1:
            time.sleep(settings['delay_seconds'])

    # 统计结果
    log_message(log_file, f"========== 发送完成 ==========")
    log_message(log_file, f"成功: {success_count}, 失败: {fail_count}, 断点跳过: {resume_skip_count}, 总计: {total}")


def verify_before_console(config_path: Path) -> bool:
    """进入控制台前完成授权验证"""
    config = config_manager.load_config(config_path)
    ensure_license_code(config)
    if not str(config.get("license", {}).get("code") or "").strip():
        print("未输入授权码，程序退出。")
        return False
    while True:
        print("正在连接授权服务器，请稍候...")
        if verify_license(config):
            config_manager.save_config(config_path, config)
            return True
        retry = clean_terminal_input(input("授权验证未通过。输入 Y 重新输入授权码，或直接回车退出: ")).upper()
        if retry != "Y":
            return False
        config["license"]["code"] = ""
        ensure_license_code(config)
        if not str(config.get("license", {}).get("code") or "").strip():
            return False


def ensure_license_code(config: dict) -> None:
    """没有授权码时先要求输入，仅用于本次运行"""
    license_config = config.setdefault("license", {})
    code = str(license_config.get("code") or "").strip()
    if code:
        return
    cli.clear_screen(input, print, force=True)
    print_license_entry_panel(config)
    code = clean_terminal_input(input("授权码（输入0退出）: "))
    if code == "0":
        return
    if code:
        license_config["code"] = code


def clean_terminal_input(value: str) -> str:
    """清理管道输入里可能出现的BOM和NUL字符。"""
    cleaned = value.replace("\x00", "").replace("\ufeff", "").replace("ï»¿", "")
    return "".join(
        char for char in cleaned.strip()
        if char.isascii() and (char.isalnum() or char in "-_")
    )


def print_license_entry_panel(config: dict) -> None:
    """打印启动授权输入页"""
    lines = [
        ("产品", "IronMail 邮件发送控制台"),
        ("授权状态", "等待输入授权码"),
        ("授权码格式", "IM-XXXXXX-XXXXXX-XXXXXX-XXXXXX"),
    ]
    print("")
    print("=" * AUTH_PANEL_WIDTH)
    print(center_text("IronMail 授权验证", AUTH_PANEL_WIDTH))
    print("=" * AUTH_PANEL_WIDTH)
    for label, value in lines:
        print(f"{label:<10} {value}")
    print("-" * AUTH_PANEL_WIDTH)
    print("请输入管理员提供的授权码。输入 0 可退出程序。")
    print("=" * AUTH_PANEL_WIDTH)


def center_text(text: str, width: int) -> str:
    """按终端宽度简单居中文本。"""
    padding = max(0, width - len(text)) // 2
    return f"{' ' * padding}{text}"


def main():
    cli.configure_terminal_encoding()
    # 获取程序所在目录
    app_dir = get_app_dir()
    config_path = app_dir / 'config' / 'config.yaml'
    if not verify_before_console(config_path):
        print("授权未通过，程序退出。")
        return
    cli.run_console(config_path, lambda: run_send_flow(app_dir, config_path), license_verified=True)


def run_app() -> int:
    """运行程序，并把未捕获异常留在屏幕和日志里。"""
    try:
        main()
        return 0
    except Exception as error:
        report_unhandled_exception(error)
        return 1


def report_unhandled_exception(error: Exception) -> Path | None:
    """打印并记录未捕获异常，避免双击运行时窗口直接消失。"""
    traceback_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    print("")
    print("=" * 72)
    print("程序发生未处理错误，已停止。")
    print("=" * 72)
    print(traceback_text.rstrip())
    log_path = write_crash_log(traceback_text)
    if log_path:
        print(f"错误日志: {log_path}")
    if cli.is_real_terminal(input, print):
        input("\n按回车退出...")
    return log_path


def write_crash_log(traceback_text: str) -> Path | None:
    """写入崩溃日志。"""
    try:
        log_path = get_app_dir() / "logs" / "crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as file:
            file.write("\n" + "=" * 72 + "\n")
            file.write(datetime.now().strftime("[%Y-%m-%d %H:%M:%S] 未处理错误\n"))
            file.write(traceback_text)
            if not traceback_text.endswith("\n"):
                file.write("\n")
        return log_path
    except Exception:
        return None


if __name__ == '__main__':
    raise SystemExit(run_app())
