# -*- coding: utf-8 -*-

import pandas as pd

from ironmail import templates


def test_parse_template_supports_subject_and_body_markers(tmp_path):
    path = tmp_path / "合作邀约.md"
    path.write_text(
        "邮件主题：关于 {{公司名}} 的合作沟通\n\n"
        "邮件正文：\n"
        "{{联系人}}您好，\n"
        "我看到贵司网站是 {{网页}}。\n",
        encoding="utf-8",
    )

    template = templates.parse_template_file(path)

    assert template.subject == "关于 {{公司名}} 的合作沟通"
    assert "我看到贵司网站是 {{网页}}" in template.body


def test_render_template_replaces_row_variables():
    template = templates.EmailTemplate(
        subject="关于 {{公司名}} 的合作沟通",
        body="{{联系人}}您好，网站是 {{网页}}。",
        path=None,
    )
    row = pd.Series({"公司名": "OldIron", "联系人": "张先生", "网页": "oldiron.us"})

    rendered = templates.render_template(template, row)

    assert rendered == ("关于 OldIron 的合作沟通", "张先生您好，网站是 oldiron.us。")


def test_missing_template_columns_are_reported():
    template = templates.EmailTemplate(
        subject="关于 {{公司名}} 的合作沟通",
        body="网站是 {{网页}}。",
        path=None,
    )
    df = pd.DataFrame([{"邮箱": "a@example.com", "公司名": "OldIron"}])

    assert templates.find_missing_template_columns(template, df) == ["网页"]


def test_apply_template_to_dataframe_adds_subject_and_body():
    template = templates.EmailTemplate(
        subject="关于 {{公司名}}",
        body="{{联系人}}您好",
        path=None,
    )
    df = pd.DataFrame([{"邮箱": "a@example.com", "公司名": "OldIron", "联系人": "张先生"}])

    rendered = templates.apply_template_to_dataframe(df, template)

    assert rendered.loc[0, "邮件主题"] == "关于 OldIron"
    assert rendered.loc[0, "邮件正文"] == "张先生您好"


def test_list_template_files_skips_readme_and_non_markdown(tmp_path):
    (tmp_path / "README.md").write_text("说明", encoding="utf-8")
    (tmp_path / "默认模板.txt").write_text("旧文件", encoding="utf-8")
    (tmp_path / "合作邀约.md").write_text("邮件主题：测试\n\n邮件正文：测试", encoding="utf-8")

    files = templates.list_template_files(tmp_path)

    assert [file.name for file in files] == ["合作邀约.md"]
