# -*- coding: utf-8 -*-

from ironmail import send_progress
from ironmail.main import format_send_error


def test_progress_file_depends_on_table_and_template(tmp_path):
    table = tmp_path / "名单.xlsx"
    template = tmp_path / "模板.md"
    table.write_text("table", encoding="utf-8")
    template.write_text("template", encoding="utf-8")

    first = send_progress.progress_file_for(tmp_path, table, template)
    second = send_progress.progress_file_for(tmp_path, table, None)

    assert first != second
    assert first.parent == tmp_path / "logs" / "progress"


def test_mark_completed_and_reload(tmp_path):
    table = tmp_path / "名单.xlsx"
    template = tmp_path / "模板.md"
    table.write_text("table", encoding="utf-8")
    template.write_text("template", encoding="utf-8")
    state = send_progress.load_progress(tmp_path, table, template)

    send_progress.mark_row_completed(state, row_key="2|buyer@example.com", status="success")
    loaded = send_progress.load_progress(tmp_path, table, template)

    assert send_progress.is_row_completed(loaded, "2|buyer@example.com") is True
    assert loaded["completed_rows"]["2|buyer@example.com"]["status"] == "success"


def test_row_key_uses_excel_row_number_and_email():
    assert send_progress.row_key(0, "buyer@example.com") == "2|buyer@example.com"


def test_format_send_error_explains_gmx_ip_policy_block():
    error = Exception(
        "(554, b'Transaction failed\\nReject due to policy restrictions.\\n"
        "For explanation visit https://postmaster.gmx.net/en/case?c=hi&i=ip&v=112.46.217.48&r=abc')"
    )

    message = format_send_error(error)

    assert "GMX拒收本次发信" in message
    assert "当前出网IP 112.46.217.48 被GMX策略限制" in message
    assert "切换其他发件邮箱" in message
    assert "postmaster.gmx.net" not in message


def test_progress_summary_counts_completed_rows(tmp_path):
    table = tmp_path / "名单.xlsx"
    table.write_text("table", encoding="utf-8")
    state = send_progress.load_progress(tmp_path, table, None)
    send_progress.mark_row_completed(state, "2|a@example.com", "success")
    send_progress.mark_row_completed(state, "3|b@example.com", "skipped_empty_email")

    assert send_progress.progress_summary(state, total_rows=3) == (2, 3)


def test_reset_progress_clears_completed_rows(tmp_path):
    table = tmp_path / "名单.xlsx"
    table.write_text("table", encoding="utf-8")
    state = send_progress.load_progress(tmp_path, table, None)
    send_progress.mark_row_completed(state, "2|a@example.com", "success")
    assert send_progress.progress_summary(state, total_rows=3) == (1, 3)

    send_progress.reset_progress(state)

    assert state["completed_rows"] == {}
    reloaded = send_progress.load_progress(tmp_path, table, None)
    assert reloaded["completed_rows"] == {}
