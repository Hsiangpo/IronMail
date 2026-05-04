# -*- coding: utf-8 -*-

from pathlib import Path

import pandas as pd

from ironmail import recipient_lists


def make_input(values):
    iterator = iter(values)
    return lambda prompt="": next(iterator)


def test_recipient_dir_uses_new_folder_name(tmp_path):
    recipient_dir = recipient_lists.ensure_recipient_dir(tmp_path)

    assert recipient_dir == tmp_path / "Mails" / "收件名单"
    assert recipient_dir.exists()


def test_recipient_dir_migrates_old_folder_name(tmp_path):
    old_dir = tmp_path / "Mails" / "收件人名单"
    old_dir.mkdir(parents=True)
    (old_dir / "名单.xlsx").write_text("x", encoding="utf-8")

    recipient_dir = recipient_lists.ensure_recipient_dir(tmp_path)

    assert recipient_dir == tmp_path / "Mails" / "收件名单"
    assert (recipient_dir / "名单.xlsx").exists()
    assert not old_dir.exists()


def test_manage_recipient_lists_opens_folder_when_adding(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    opened = []
    output = []
    monkeypatch.setattr("ironmail.recipient_lists.open_path", lambda path: opened.append(path))

    recipient_lists.manage_recipient_lists(config_path, make_input(["1", "0"]), output.append)

    assert opened == [tmp_path / "Mails" / "收件名单"]
    joined = "\n".join(output)
    assert "收件名单目录" in joined
    assert "把 .xlsx 或 .csv 表格拖入这个文件夹" in joined


def test_manage_recipient_lists_opens_selected_table(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    recipient_dir = tmp_path / "Mails" / "收件名单"
    recipient_dir.mkdir(parents=True)
    table = recipient_dir / "客户.xlsx"
    pd.DataFrame([{"邮箱": "a@example.com"}]).to_excel(table, index=False)
    opened = []
    monkeypatch.setattr("ironmail.recipient_lists.open_path", lambda path: opened.append(path))

    recipient_lists.manage_recipient_lists(config_path, make_input(["2", "1", "0"]), lambda line: None)

    assert opened == [table]


def test_manage_recipient_lists_renames_header_variable(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    recipient_dir = tmp_path / "Mails" / "收件名单"
    recipient_dir.mkdir(parents=True)
    table = recipient_dir / "客户.xlsx"
    pd.DataFrame([{"网站": "a.example", "邮箱": "a@example.com"}]).to_excel(table, index=False)
    output = []

    recipient_lists.manage_recipient_lists(config_path, make_input(["3", "1", "1", "网页", "0"]), output.append)

    updated = pd.read_excel(table)
    assert list(updated.columns) == ["网页", "邮箱"]
    joined = "\n".join(output)
    assert "当前表头变量" in joined
    assert "已更新表头变量" in joined


def test_manage_recipient_lists_deletes_selected_table(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    recipient_dir = tmp_path / "Mails" / "收件名单"
    recipient_dir.mkdir(parents=True)
    table = recipient_dir / "客户.csv"
    table.write_text("邮箱\na@example.com\n", encoding="utf-8")

    recipient_lists.manage_recipient_lists(config_path, make_input(["4", "1", "DELETE", "0"]), lambda line: None)

    assert not table.exists()
