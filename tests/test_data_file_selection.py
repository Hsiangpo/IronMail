# -*- coding: utf-8 -*-

import pandas as pd

from ironmail.main import (
    choose_data_file,
    choose_template_file,
    list_data_files,
    validate_email_dataframe,
)


def test_list_data_files_orders_xlsx_before_csv_and_skips_excel_lock(tmp_path):
    mails_dir = tmp_path / "Mails"
    mails_dir.mkdir()
    (mails_dir / "b.csv").write_text("x", encoding="utf-8")
    (mails_dir / "a.xlsx").write_text("x", encoding="utf-8")
    (mails_dir / "~$lock.xlsx").write_text("x", encoding="utf-8")

    files = list_data_files(mails_dir)

    assert [file.name for file in files] == ["a.xlsx", "b.csv"]


def test_choose_data_file_prompts_even_when_single_file(tmp_path, monkeypatch, capsys):
    mails_dir = tmp_path / "Mails"
    mails_dir.mkdir()
    target = mails_dir / "only.csv"
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")

    assert choose_data_file(tmp_path).name == "only.csv"
    output = capsys.readouterr().out
    assert "选择收件人表格" in output
    assert "only.csv" in output


def test_choose_data_file_uses_explicit_config_without_prompt(tmp_path, monkeypatch):
    mails_dir = tmp_path / "Mails"
    mails_dir.mkdir()
    target = mails_dir / "fixed.csv"
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("不应要求输入")))

    assert choose_data_file(tmp_path, "fixed.csv").name == "fixed.csv"


def test_choose_data_file_prompts_when_multiple_files(tmp_path, monkeypatch):
    mails_dir = tmp_path / "Mails"
    mails_dir.mkdir()
    (mails_dir / "first.xlsx").write_text("x", encoding="utf-8")
    (mails_dir / "second.csv").write_text("x", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")

    assert choose_data_file(tmp_path).name == "second.csv"


def test_choose_data_file_can_return_to_main_menu(tmp_path, monkeypatch, capsys):
    mails_dir = tmp_path / "Mails"
    mails_dir.mkdir()
    (mails_dir / "first.xlsx").write_text("x", encoding="utf-8")
    (mails_dir / "second.csv").write_text("x", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "0")

    assert choose_data_file(tmp_path) is None
    output = capsys.readouterr().out
    assert "选择收件人表格" in output
    assert "0. 返回主菜单" in output


def test_choose_data_file_reads_from_recipient_list_folder(tmp_path, monkeypatch):
    recipient_dir = tmp_path / "Mails" / "收件人名单"
    recipient_dir.mkdir(parents=True)
    (recipient_dir / "名单.xlsx").write_text("x", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")

    assert choose_data_file(tmp_path).name == "名单.xlsx"


def test_validate_email_dataframe_requires_only_email_with_template():
    df = pd.DataFrame([{"邮箱": "a@example.com"}])

    assert validate_email_dataframe(df, use_template=True) == []


def test_validate_email_dataframe_requires_subject_and_body_without_template():
    df = pd.DataFrame([{"邮箱": "a@example.com"}])

    errors = validate_email_dataframe(df, use_template=False)

    assert "缺少必需字段: 邮件主题, 邮件正文" in errors


def test_choose_template_file_can_use_old_table_fields_when_folder_missing(tmp_path):
    mails_dir = tmp_path / "Mails"
    mails_dir.mkdir()

    assert choose_template_file(tmp_path, allow_table_fields=True) is None


def test_choose_template_file_prompts_for_markdown_template(tmp_path, monkeypatch):
    template_dir = tmp_path / "Mails" / "邮件模板"
    template_dir.mkdir(parents=True)
    (template_dir / "README.md").write_text("说明", encoding="utf-8")
    (template_dir / "合作.md").write_text("邮件主题：测试\n\n邮件正文：测试", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")

    assert choose_template_file(tmp_path, allow_table_fields=False).name == "合作.md"


def test_choose_template_file_can_return_to_main_menu(tmp_path, monkeypatch, capsys):
    template_dir = tmp_path / "Mails" / "邮件模板"
    template_dir.mkdir(parents=True)
    (template_dir / "合作.md").write_text("邮件主题：测试\n\n邮件正文：测试", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "0")

    assert choose_template_file(tmp_path, allow_table_fields=False) is None
    assert "0. 返回主菜单" in capsys.readouterr().out
