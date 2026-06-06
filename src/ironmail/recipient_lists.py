# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


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
