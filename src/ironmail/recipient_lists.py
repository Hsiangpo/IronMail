# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd


InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]
RECIPIENT_DIR_NAME = "收件名单"
LEGACY_RECIPIENT_DIR_NAMES = ("收件人名单", "发件对象")
SUPPORTED_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".csv")
EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls")
CSV_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "gb18030",
    "gbk",
    "cp936",
    "utf-16",
    "utf-16le",
    "utf-16be",
)


def ensure_recipient_dir(app_dir: Path) -> Path:
    """确保收件名单目录存在，并把旧目录迁移到新目录名。"""
    mails_dir = app_dir / "Mails"
    preferred = mails_dir / RECIPIENT_DIR_NAME
    if preferred.exists():
        return preferred
    for legacy_name in LEGACY_RECIPIENT_DIR_NAMES:
        legacy = mails_dir / legacy_name
        if legacy.exists():
            preferred.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(preferred)
            return preferred
    preferred.mkdir(parents=True, exist_ok=True)
    return preferred


def find_recipient_dir(app_dir: Path) -> Path:
    """读取收件名单目录，优先使用新目录名。"""
    mails_dir = app_dir / "Mails"
    preferred = mails_dir / RECIPIENT_DIR_NAME
    if preferred.exists():
        return preferred
    for legacy_name in LEGACY_RECIPIENT_DIR_NAMES:
        legacy = mails_dir / legacy_name
        if legacy.exists():
            return legacy
    return preferred


def resolve_recipient_dir_from_mails(data_dir: Path) -> Path:
    """传入Mails目录时，定位到收件名单目录。"""
    if data_dir.name in (RECIPIENT_DIR_NAME, *LEGACY_RECIPIENT_DIR_NAMES):
        return data_dir
    preferred = data_dir / RECIPIENT_DIR_NAME
    if preferred.exists():
        return preferred
    for legacy_name in LEGACY_RECIPIENT_DIR_NAMES:
        legacy = data_dir / legacy_name
        if legacy.exists():
            return legacy
    return data_dir


def list_recipient_files(recipient_dir: Path) -> list[Path]:
    """列出收件名单表格。"""
    if not recipient_dir.exists():
        raise FileNotFoundError(f"未找到收件名单文件夹: {recipient_dir}")
    files: list[Path] = []
    for suffix in SUPPORTED_SUFFIXES:
        files.extend(
            sorted(file for file in recipient_dir.glob(f"*{suffix}") if not file.name.startswith("~$"))
        )
    return files


def manage_recipient_lists(config_path: Path, input_func: InputFunc, print_func: PrintFunc) -> None:
    """运行收件名单管理菜单。"""
    from ironmail import cli

    app_dir = config_path.resolve().parent.parent
    while True:
        recipient_dir = ensure_recipient_dir(app_dir)
        cli.clear_screen(input_func, print_func)
        cli.print_header("收件名单管理", print_func)
        print_func(f"收件名单目录: {recipient_dir}")
        print_func("说明: 这里放 .xlsx、.xlsm、.xls 或 .csv 表格。表头就是模板变量，例如 网页、法人、邮箱。")
        cli.print_menu(
            [
                ("1", "新增收件名单"),
                ("2", "查看/打开收件名单"),
                ("3", "修改表头变量"),
                ("4", "删除收件名单"),
                ("0", "返回主菜单"),
            ],
            print_func,
        )
        choice = input_func("请选择功能: ").strip()
        if choice == "1":
            add_recipient_list_interactive(recipient_dir, print_func)
            cli.pause_after_action(input_func, print_func)
        elif choice == "2":
            open_recipient_list_interactive(recipient_dir, input_func, print_func)
            cli.pause_after_action(input_func, print_func)
        elif choice == "3":
            rename_header_interactive(recipient_dir, input_func, print_func)
            cli.pause_after_action(input_func, print_func)
        elif choice == "4":
            delete_recipient_list_interactive(recipient_dir, input_func, print_func)
            cli.pause_after_action(input_func, print_func)
        elif choice == "0":
            return
        else:
            print_func("请输入菜单里的数字。")


def add_recipient_list_interactive(recipient_dir: Path, print_func: PrintFunc) -> None:
    """打开收件名单文件夹，让用户拖入表格。"""
    from ironmail import cli

    cli.print_step(
        1,
        1,
        "打开收件名单文件夹",
        "把 .xlsx、.xlsm、.xls 或 .csv 表格拖入这个文件夹。拖入后回到本程序查看列表。",
        print_func,
    )
    open_path(recipient_dir)
    print_func(f"已打开收件名单文件夹: {recipient_dir}")


def open_recipient_list_interactive(
    recipient_dir: Path,
    input_func: InputFunc,
    print_func: PrintFunc,
) -> None:
    """选择并打开一个收件名单。"""
    from ironmail import cli

    cli.print_step(1, 1, "选择要查看的表格", "输入表格序号后，系统会用默认程序打开。", print_func)
    table = pick_recipient_file(recipient_dir, input_func, print_func)
    if not table:
        return
    open_path(table)
    print_func(f"已打开收件名单: {table.name}")


def delete_recipient_list_interactive(
    recipient_dir: Path,
    input_func: InputFunc,
    print_func: PrintFunc,
) -> None:
    """选择并删除一个收件名单。"""
    from ironmail import cli

    cli.print_step(1, 2, "选择要删除的表格", "输入表格序号。输入0返回上一层。", print_func)
    table = pick_recipient_file(recipient_dir, input_func, print_func)
    if not table:
        return
    cli.print_step(2, 2, "确认删除", "删除后表格会从磁盘移除。需要输入 DELETE 才会真正删除。", print_func)
    confirm = input_func(f"确认删除 {table.name}？输入 DELETE 确认，输入0返回上一层: ").strip()
    if cli.is_back_command(confirm):
        cli.print_returned(print_func)
        return
    if confirm != "DELETE":
        print_func("已取消删除。")
        return
    table.unlink()
    print_func("已删除收件名单。")


def rename_header_interactive(
    recipient_dir: Path,
    input_func: InputFunc,
    print_func: PrintFunc,
) -> None:
    """交互式修改表头变量。"""
    from ironmail import cli

    cli.print_step(1, 3, "选择要修改的表格", "表头就是模板变量，例如 {{网页}}、{{法人}}、{{邮箱}}。", print_func)
    table = pick_recipient_file(recipient_dir, input_func, print_func)
    if not table:
        return
    headers = read_headers(table)
    print_headers(headers, print_func)
    cli.print_step(2, 3, "选择表头变量", "输入要修改的表头序号。输入0返回上一层。", print_func)
    raw_index = input_func("请输入表头序号，输入0返回上一层: ").strip()
    if cli.is_back_command(raw_index):
        cli.print_returned(print_func)
        return
    old_name = header_name_by_index(headers, raw_index, print_func)
    if not old_name:
        return
    cli.print_step(3, 3, "填写新的变量名", "变量名会用于邮件模板。不要和已有表头重复。", print_func)
    new_name = input_func(f"新的变量名 [{old_name}]: ").strip()
    if cli.is_back_command(new_name):
        cli.print_returned(print_func)
        return
    try:
        rename_header(table, old_name, new_name)
    except ValueError as error:
        print_func(f"修改失败: {error}")
        return
    print_func(f"已更新表头变量: {old_name} -> {new_name}")


def pick_recipient_file(recipient_dir: Path, input_func: InputFunc, print_func: PrintFunc) -> Path | None:
    """选择一个收件名单表格。"""
    from ironmail import cli

    try:
        files = list_recipient_files(recipient_dir)
    except FileNotFoundError:
        print_func("暂无收件名单文件夹，请先新增收件名单。")
        return None
    if not files:
        print_func("暂无收件名单。请先把 .xlsx、.xlsm、.xls 或 .csv 表格拖入收件名单文件夹。")
        return None
    print_recipient_files(files, print_func)
    raw_index = input_func("请输入表格序号，输入0返回上一层: ").strip()
    if cli.is_back_command(raw_index):
        cli.print_returned(print_func)
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


def print_recipient_files(files: list[Path], print_func: PrintFunc) -> None:
    """打印收件名单表格列表。"""
    print_func("序号  表格文件")
    print_func("-" * 72)
    for index, file_path in enumerate(files, 1):
        stat = file_path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        size_kb = max(1, round(stat.st_size / 1024))
        print_func(f"{index:<4}  {file_path.name} | {size_kb} KB | 修改时间 {modified}")


def read_table(file_path: Path) -> pd.DataFrame:
    """读取收件名单表格。"""
    suffix = file_path.suffix.lower()
    if suffix in EXCEL_SUFFIXES:
        return read_excel_table(file_path)
    if suffix == ".csv":
        return read_csv_with_fallback(file_path)
    raise ValueError(f"不支持的文件格式: {file_path.suffix}")


def read_excel_table(file_path: Path) -> pd.DataFrame:
    """读取Excel表格，兼容xlsx/xlsm/xls。"""
    suffix = file_path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(file_path, engine="openpyxl")
    if suffix == ".xls":
        return pd.read_excel(file_path, engine="xlrd")
    raise ValueError(f"不支持的Excel格式: {file_path.suffix}")


def read_csv_with_fallback(file_path: Path) -> pd.DataFrame:
    """读取CSV，兼容常见编码和逗号/分号/Tab分隔。"""
    last_error: UnicodeDecodeError | None = None
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(file_path, encoding=encoding, sep=None, engine="python")
        except (UnicodeDecodeError, UnicodeError) as error:
            last_error = error
    raise ValueError(f"CSV文件编码不支持，请另存为UTF-8、GBK或UTF-16后重试: {file_path}") from last_error


def save_table(file_path: Path, df: pd.DataFrame) -> None:
    """保存收件名单表格。"""
    suffix = file_path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        df.to_excel(file_path, index=False)
        return
    if suffix == ".csv":
        df.to_csv(file_path, index=False, encoding="utf-8")
        return
    if suffix == ".xls":
        raise ValueError("旧版 .xls 文件只能读取；如需修改表头，请先另存为 .xlsx。")
    raise ValueError(f"不支持的文件格式: {file_path.suffix}")


def read_headers(file_path: Path) -> list[str]:
    """读取表头变量。"""
    return [str(column) for column in read_table(file_path).columns]


def print_headers(headers: list[str], print_func: PrintFunc) -> None:
    """打印表头变量。"""
    print_func("当前表头变量")
    print_func("-" * 72)
    for index, header in enumerate(headers, 1):
        print_func(f"{index}. {header}")


def header_name_by_index(headers: list[str], raw_index: str, print_func: PrintFunc) -> str:
    """按序号读取表头名称。"""
    try:
        index = int(raw_index)
    except ValueError:
        print_func("序号必须是数字。")
        return ""
    if index < 1 or index > len(headers):
        print_func("序号超出范围。")
        return ""
    return headers[index - 1]


def rename_header(file_path: Path, old_name: str, new_name: str) -> None:
    """修改表头变量名。"""
    clean_name = new_name.strip()
    if not clean_name:
        raise ValueError("新的变量名不能为空。")
    df = read_table(file_path)
    if old_name not in df.columns:
        raise ValueError(f"未找到表头变量: {old_name}")
    if clean_name != old_name and clean_name in df.columns:
        raise ValueError(f"表头变量已存在: {clean_name}")
    df = df.rename(columns={old_name: clean_name})
    save_table(file_path, df)


def open_path(path: Path) -> None:
    """用系统默认程序打开文件或文件夹。"""
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
        return
    command = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([command, str(path)])
