# -*- coding: utf-8 -*-

import pandas as pd

from ironmail.main import validate_email_dataframe


def test_validate_email_dataframe_requires_only_email_with_template():
    df = pd.DataFrame([{"邮箱": "a@example.com"}])

    assert validate_email_dataframe(df, use_template=True) == []


def test_validate_email_dataframe_requires_subject_and_body_without_template():
    df = pd.DataFrame([{"邮箱": "a@example.com"}])

    errors = validate_email_dataframe(df, use_template=False)

    assert "缺少必需字段: 邮件主题, 邮件正文" in errors
