# -*- coding: utf-8 -*-

from pathlib import Path

import pandas as pd

from ironmail import send_progress
from ironmail.main import format_send_error, run_send_flow


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

    assert "GMX拒绝本次发信" in message
    assert "当前出网IP 112.46.217.48 触发风控" in message
    assert "postmaster.gmx.net" not in message


def test_progress_summary_counts_completed_rows(tmp_path):
    table = tmp_path / "名单.xlsx"
    table.write_text("table", encoding="utf-8")
    state = send_progress.load_progress(tmp_path, table, None)
    send_progress.mark_row_completed(state, "2|a@example.com", "success")
    send_progress.mark_row_completed(state, "3|b@example.com", "skipped_empty_email")

    assert send_progress.progress_summary(state, total_rows=3) == (2, 3)


def write_runtime_config(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        """
license:
  server_url: https://tmpmail.oldiron.us
  code:
smtp:
  host: smtp.gmail.com
  port: 465
  use_ssl: true
senders:
  - email: sender@gmail.com
    password: app-password
    name: Sender
settings:
  emails_per_account: 1
  delay_seconds: 0
  max_retries: 1
  log_file: logs/send_log.txt
""".lstrip(),
        encoding="utf-8",
    )


def write_runtime_files(app_dir: Path) -> tuple[Path, Path]:
    recipient_dir = app_dir / "Mails" / "收件名单"
    template_dir = app_dir / "Mails" / "邮件模板"
    recipient_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    data_path = recipient_dir / "名单.xlsx"
    template_path = template_dir / "默认模板.md"
    pd.DataFrame(
        [
            {"网页": "a.example", "法人": "张一", "邮箱": "a@example.com"},
            {"网页": "b.example", "法人": "张二", "邮箱": "b@example.com"},
        ]
    ).to_excel(data_path, index=False)
    template_path.write_text("邮件主题：关于 {{网页}}\n\n邮件正文：{{法人}}您好", encoding="utf-8")
    return data_path, template_path


def test_send_flow_resumes_failed_run_without_resending_success(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    write_runtime_config(config_path)
    write_runtime_files(tmp_path)
    monkeypatch.setattr("ironmail.main.time.sleep", lambda seconds: None)
    first_inputs = iter(["1", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(first_inputs))
    sent = []

    def flaky_send(smtp_config, sender, recipient_email, subject, body):
        sent.append(recipient_email)
        if recipient_email == "b@example.com":
            raise OSError("network down")
        return True

    monkeypatch.setattr("ironmail.mailer.send_email", flaky_send)

    run_send_flow(tmp_path, config_path)

    second_inputs = iter(["1", "1", "Y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(second_inputs))
    monkeypatch.setattr("ironmail.mailer.send_email", lambda *args: sent.append(args[2]) or True)

    run_send_flow(tmp_path, config_path)

    assert sent == ["a@example.com", "b@example.com", "b@example.com"]


def test_completed_run_can_be_cancelled_to_avoid_duplicate_send(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "config.yaml"
    write_runtime_config(config_path)
    write_runtime_files(tmp_path)
    monkeypatch.setattr("ironmail.main.time.sleep", lambda seconds: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    monkeypatch.setattr("ironmail.mailer.send_email", lambda *args: True)

    run_send_flow(tmp_path, config_path)

    sent = []
    inputs = iter(["1", "1", "N"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("ironmail.mailer.send_email", lambda *args: sent.append(args[2]) or True)

    run_send_flow(tmp_path, config_path)

    assert sent == []
