# -*- coding: utf-8 -*-

import pandas as pd

from ironmail import recipient_lists


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


def test_rename_header_updates_excel_column(tmp_path):
    table = tmp_path / "客户.xlsx"
    pd.DataFrame([{"网站": "a.example", "邮箱": "a@example.com"}]).to_excel(table, index=False)

    recipient_lists.rename_header(table, "网站", "网页")

    updated = pd.read_excel(table)
    assert list(updated.columns) == ["网页", "邮箱"]


def test_read_headers_returns_columns(tmp_path):
    table = tmp_path / "客户.xlsx"
    pd.DataFrame([{"网页": "a.example", "邮箱": "a@example.com"}]).to_excel(table, index=False)

    assert recipient_lists.read_headers(table) == ["网页", "邮箱"]


def test_read_table_supports_gbk_csv(tmp_path):
    table = tmp_path / "客户.csv"
    table.write_bytes("网页,法人,邮箱\nexample.com,张三,a@example.com\n".encode("gb18030"))

    df = recipient_lists.read_table(table)

    assert list(df.columns) == ["网页", "法人", "邮箱"]
    assert df.loc[0, "法人"] == "张三"


def test_read_table_supports_gbk_semicolon_csv(tmp_path):
    table = tmp_path / "客户.csv"
    table.write_bytes("网页;法人;邮箱\nexample.com;张三;a@example.com\n".encode("gb18030"))

    df = recipient_lists.read_table(table)

    assert list(df.columns) == ["网页", "法人", "邮箱"]
    assert df.loc[0, "邮箱"] == "a@example.com"


def test_read_table_supports_xlsm(tmp_path):
    table = tmp_path / "客户.xlsm"
    pd.DataFrame([{"邮箱": "a@example.com"}]).to_excel(table, index=False)

    df = recipient_lists.read_table(table)

    assert df.loc[0, "邮箱"] == "a@example.com"
