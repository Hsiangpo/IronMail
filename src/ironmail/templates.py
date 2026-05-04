# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


VARIABLE_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
SENDER_PREFIXES = ("发件人：", "发件人:", "发送人：", "发送人:")
SUBJECT_PREFIXES = ("邮件主题：", "邮件主题:", "主题：", "主题:")
BODY_PREFIXES = ("邮件正文：", "邮件正文:", "正文：", "正文:")
TEMPLATE_SCAFFOLD = "发件人：\n\n邮件主题：\n\n邮件正文：\n"


@dataclass(frozen=True)
class EmailTemplate:
    subject: str
    body: str
    path: Path | None
    sender: str = ""


def list_template_files(template_dir: Path) -> list[Path]:
    """列出可用邮件模板文件。"""
    if not template_dir.exists():
        raise FileNotFoundError(f"未找到邮件模板文件夹: {template_dir}")
    return sorted(
        file for file in template_dir.glob("*.md")
        if not file.name.startswith(".") and file.name.lower() != "readme.md"
    )


def parse_template_file(template_path: Path) -> EmailTemplate:
    """读取并解析邮件模板。"""
    text = template_path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines:
        raise ValueError("模板为空，请填写邮件主题和邮件正文。")

    sender, subject, body = _read_template_sections(lines)
    if subject is None:
        raise ValueError("模板必须包含“邮件主题：”或“主题：”。")
    if not subject.strip():
        raise ValueError("模板邮件主题不能为空。")
    if not body.strip():
        raise ValueError("模板邮件正文不能为空。")
    return EmailTemplate(subject=subject.strip(), body=body, path=template_path, sender=sender.strip())


def create_template_file(template_dir: Path, name: str) -> Path:
    """创建可编辑的邮件模板文件。"""
    template_dir.mkdir(parents=True, exist_ok=True)
    filename = _template_filename(name)
    template_path = template_dir / filename
    if template_path.exists():
        raise FileExistsError(f"模板已存在: {template_path.name}")
    template_path.write_text(TEMPLATE_SCAFFOLD, encoding="utf-8")
    return template_path


def render_template(template: EmailTemplate, row: pd.Series) -> tuple[str, str]:
    """用表格当前行数据替换模板变量。"""
    _, subject, body = render_template_fields(template, row)
    return subject, body


def render_template_fields(template: EmailTemplate, row: pd.Series) -> tuple[str, str, str]:
    """用表格当前行数据替换发件人、主题和正文变量。"""
    values = {str(key): _cell_to_text(value) for key, value in row.items()}
    sender = _replace_variables(template.sender, values).strip()
    subject = _replace_variables(template.subject, values).strip()
    body = _replace_variables(template.body, values).strip()
    return sender, subject, body


def apply_template_to_dataframe(df: pd.DataFrame, template: EmailTemplate) -> pd.DataFrame:
    """把模板渲染结果写回发件人、邮件主题和邮件正文列。"""
    rendered = df.copy()
    senders = []
    subjects = []
    bodies = []
    for _, row in rendered.iterrows():
        sender, subject, body = render_template_fields(template, row)
        senders.append(sender)
        subjects.append(subject)
        bodies.append(body)
    if template.sender.strip():
        rendered["发件人"] = senders
    rendered["邮件主题"] = subjects
    rendered["邮件正文"] = bodies
    return rendered


def find_missing_template_columns(template: EmailTemplate, df: pd.DataFrame) -> list[str]:
    """找出模板里使用了但表格没有提供的变量。"""
    available = {str(column) for column in df.columns}
    variables = extract_variables(template)
    return sorted(variable for variable in variables if variable not in available)


def extract_variables(template: EmailTemplate) -> set[str]:
    """提取模板里的变量名。"""
    text = f"{template.sender}\n{template.subject}\n{template.body}"
    return {match.group(1).strip() for match in VARIABLE_PATTERN.finditer(text)}


def _read_prefixed_value(line: str, prefixes: tuple[str, ...]) -> str | None:
    """读取指定前缀后的内容。"""
    stripped = line.strip()
    for prefix in prefixes:
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix)
    return None


def _read_template_sections(lines: list[str]) -> tuple[str, str | None, str]:
    """读取发件人、主题和正文，兼容旧模板和分块模板。"""
    subject_index = _find_prefixed_line(lines, SUBJECT_PREFIXES)
    if subject_index is None:
        return "", None, ""

    sender = ""
    sender_index = _find_prefixed_line(lines[:subject_index], SENDER_PREFIXES)
    if sender_index is not None:
        sender = _read_section_value(lines, sender_index, subject_index, SENDER_PREFIXES)

    body_index = _find_prefixed_line(lines[subject_index + 1:], BODY_PREFIXES)
    if body_index is None:
        subject = _read_section_value(lines, subject_index, len(lines), SUBJECT_PREFIXES)
        return sender, subject, ""
    body_index += subject_index + 1
    subject = _read_section_value(lines, subject_index, body_index, SUBJECT_PREFIXES)
    return sender, subject, _read_body(lines[body_index:])


def _find_prefixed_line(lines: list[str], prefixes: tuple[str, ...]) -> int | None:
    """查找带指定前缀的行。"""
    for index, line in enumerate(lines):
        if _read_prefixed_value(line, prefixes) is not None:
            return index
    return None


def _read_section_value(
    lines: list[str],
    marker_index: int,
    end_index: int,
    prefixes: tuple[str, ...],
) -> str:
    """读取发件人或主题段，兼容同一行和下一行内容。"""
    inline_value = _read_prefixed_value(lines[marker_index], prefixes) or ""
    if inline_value.strip():
        return inline_value.strip()
    section_lines = [line for line in lines[marker_index + 1:end_index] if line.strip()]
    return "\n".join(section_lines).strip()


def _read_body(lines: list[str]) -> str:
    """读取正文，兼容带“邮件正文：”标记和直接写正文两种格式。"""
    for index, line in enumerate(lines):
        inline_body = _read_prefixed_value(line, BODY_PREFIXES)
        if inline_body is None:
            continue
        body_lines = []
        if inline_body.strip():
            body_lines.append(inline_body)
        body_lines.extend(lines[index + 1:])
        return "\n".join(body_lines).strip()
    return "\n".join(lines).strip()


def _template_filename(name: str) -> str:
    """生成安全的模板文件名。"""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "-", name.strip()).strip(". ")
    if not cleaned:
        raise ValueError("模板名称不能为空")
    if not cleaned.lower().endswith(".md"):
        cleaned = f"{cleaned}.md"
    return cleaned


def _replace_variables(text: str, values: dict[str, str]) -> str:
    """替换模板变量。"""
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return values.get(key, "")

    return VARIABLE_PATTERN.sub(replace, text)


def _cell_to_text(value: Any) -> str:
    """把表格单元格值转成邮件里的文本。"""
    if pd.isna(value):
        return ""
    return str(value).strip()
