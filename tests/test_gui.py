# -*- coding: utf-8 -*-

import queue
from pathlib import Path

import pandas as pd

from ironmail import config_manager, gui, send_progress


class FakeVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


def test_gui_queue_callback_error_does_not_stop_future_callbacks(monkeypatch, tmp_path):
    app = object.__new__(gui.IronMailApp)
    app.queue = queue.Queue()
    scheduled = []
    calls = []

    def broken_callback():
        raise NameError("stale callback")

    monkeypatch.setattr(gui, "write_crash_log", lambda text: tmp_path / "crash.log")
    app.after = lambda delay, callback: scheduled.append((delay, callback))
    app.queue.put(broken_callback)
    app.queue.put(lambda: calls.append("next callback ran"))

    gui.IronMailApp._drain_queue(app)

    assert calls == ["next callback ran"]
    assert scheduled and scheduled[0][0] == 100


def test_smtp_test_failure_callback_keeps_error_text(monkeypatch):
    app = object.__new__(gui.IronMailApp)
    app.queue = queue.Queue()
    app.main_summary_var = FakeVar()
    app.load_config = lambda: config_manager.normalize_config(
        {
            "smtp": {"host": "mail.gmx.com", "port": 465, "use_ssl": True},
            "smtp_proxy": {"mode": "direct"},
        }
    )
    messages = []

    def fail_login(smtp, sender):
        raise RuntimeError("login failed")

    monkeypatch.setattr(gui.mailer, "test_smtp_login", fail_login)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, message: messages.append((title, message)))

    gui.IronMailApp._test_sender(app, {"email": "sender@gmx.com", "password": "secret"})
    while not app.queue.empty():
        app.queue.get_nowait()()

    assert messages[0][0] == "SMTP 测试失败"
    assert "login failed" in messages[0][1]
    assert app.main_summary_var.value == "sender@gmx.com SMTP 测试失败。"


def test_background_failure_callback_keeps_error_text(monkeypatch):
    app = object.__new__(gui.IronMailApp)
    app.queue = queue.Queue()
    app.worker = None
    messages = []

    def fail_task():
        raise RuntimeError("worker failed")

    monkeypatch.setattr(gui, "write_crash_log", lambda text: Path("logs/crash.log"))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, message: messages.append((title, message)))

    gui.IronMailApp.run_background(app, fail_task)
    app.worker.join(timeout=2)
    while not app.queue.empty():
        app.queue.get_nowait()()

    assert messages[0][0] == "任务失败"
    assert "worker failed" in messages[0][1]


def _seed_partial_progress(app_dir, data_path):
    data_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [{"邮箱": "a@example.com"}, {"邮箱": "b@example.com"}, {"邮箱": "c@example.com"}]
    ).to_excel(data_path, index=False)
    state = send_progress.load_progress(app_dir, data_path, None)
    send_progress.mark_row_completed(state, send_progress.row_key(0, "a@example.com"), "success")
    return state


def test_prepare_progress_state_resume_keeps_completed(monkeypatch, tmp_path):
    app = object.__new__(gui.IronMailApp)
    app.app_dir = tmp_path
    data_path = tmp_path / "Mails" / "收件名单" / "名单.xlsx"
    _seed_partial_progress(tmp_path, data_path)
    monkeypatch.setattr(gui.messagebox, "askyesnocancel", lambda *a, **k: True)

    state = gui.IronMailApp.prepare_progress_state(app, data_path, None, 3)

    assert state is not None
    assert len(state["completed_rows"]) == 1


def test_prepare_progress_state_restart_resets(monkeypatch, tmp_path):
    app = object.__new__(gui.IronMailApp)
    app.app_dir = tmp_path
    data_path = tmp_path / "Mails" / "收件名单" / "名单.xlsx"
    _seed_partial_progress(tmp_path, data_path)
    monkeypatch.setattr(gui.messagebox, "askyesnocancel", lambda *a, **k: False)

    state = gui.IronMailApp.prepare_progress_state(app, data_path, None, 3)

    assert state is not None
    assert state["completed_rows"] == {}


def test_prepare_progress_state_cancel_returns_none(monkeypatch, tmp_path):
    app = object.__new__(gui.IronMailApp)
    app.app_dir = tmp_path
    data_path = tmp_path / "Mails" / "收件名单" / "名单.xlsx"
    _seed_partial_progress(tmp_path, data_path)
    monkeypatch.setattr(gui.messagebox, "askyesnocancel", lambda *a, **k: None)

    state = gui.IronMailApp.prepare_progress_state(app, data_path, None, 3)

    assert state is None


def _make_send_app(tmp_path):
    """A bare IronMailApp with the Tk-touching hooks stubbed out for send_worker tests."""
    app = object.__new__(gui.IronMailApp)
    app.app_dir = tmp_path
    app._post = lambda fn: None          # skip progress bar / status var widget updates
    app.gui_log = lambda message: None   # skip Tk text widget + log-file writes
    return app


def _send_config(senders, **settings):
    base = {"delay_seconds": 0, "max_retries": 1, "emails_per_account": 1}
    base.update(settings)
    return config_manager.normalize_config({"senders": senders, "settings": base})


def test_send_worker_sends_each_row_and_marks_progress(monkeypatch, tmp_path):
    app = _make_send_app(tmp_path)
    sent = []
    monkeypatch.setattr(
        gui.mailer,
        "send_email",
        lambda smtp, sender, to, subject, body, sender_name=None: sent.append((sender["email"], to)) or True,
    )
    config = _send_config([{"email": "s@gmail.com", "password": "p"}])
    senders = config_manager.active_senders(config)
    df = pd.DataFrame(
        [
            {"邮箱": "a@example.com", "邮件主题": "主题", "邮件正文": "正文"},
            {"邮箱": "b@example.com", "邮件主题": "主题", "邮件正文": "正文"},
        ]
    )
    data_path = tmp_path / "名单.xlsx"
    df.to_excel(data_path, index=False)
    state = send_progress.load_progress(tmp_path, data_path, None)

    gui.IronMailApp.send_worker(app, config, senders, df, data_path, None, state)

    assert sent == [("s@gmail.com", "a@example.com"), ("s@gmail.com", "b@example.com")]
    assert send_progress.is_row_completed(state, send_progress.row_key(0, "a@example.com"))
    assert send_progress.is_row_completed(state, send_progress.row_key(1, "b@example.com"))


def test_send_worker_fails_over_to_next_sender(monkeypatch, tmp_path):
    app = _make_send_app(tmp_path)
    attempts = []

    def flaky(smtp, sender, to, subject, body, sender_name=None):
        attempts.append((sender["email"], to))
        if sender["email"] == "primary@gmail.com":
            raise OSError("rejected")
        return True

    monkeypatch.setattr(gui.mailer, "send_email", flaky)
    config = _send_config(
        [
            {"email": "primary@gmail.com", "password": "p"},
            {"email": "backup@gmail.com", "password": "p"},
        ]
    )
    senders = config_manager.active_senders(config)
    df = pd.DataFrame([{"邮箱": "a@example.com", "邮件主题": "x", "邮件正文": "y"}])
    data_path = tmp_path / "名单.xlsx"
    df.to_excel(data_path, index=False)
    state = send_progress.load_progress(tmp_path, data_path, None)

    gui.IronMailApp.send_worker(app, config, senders, df, data_path, None, state)

    assert attempts == [("primary@gmail.com", "a@example.com"), ("backup@gmail.com", "a@example.com")]
    assert send_progress.is_row_completed(state, send_progress.row_key(0, "a@example.com"))


def test_send_worker_skips_rows_already_in_progress(monkeypatch, tmp_path):
    app = _make_send_app(tmp_path)
    sent = []
    monkeypatch.setattr(
        gui.mailer,
        "send_email",
        lambda smtp, sender, to, subject, body, sender_name=None: sent.append(to) or True,
    )
    config = _send_config([{"email": "s@gmail.com", "password": "p"}])
    senders = config_manager.active_senders(config)
    df = pd.DataFrame(
        [
            {"邮箱": "done@example.com", "邮件主题": "x", "邮件正文": "y"},
            {"邮箱": "new@example.com", "邮件主题": "x", "邮件正文": "y"},
        ]
    )
    data_path = tmp_path / "名单.xlsx"
    df.to_excel(data_path, index=False)
    state = send_progress.load_progress(tmp_path, data_path, None)
    send_progress.mark_row_completed(state, send_progress.row_key(0, "done@example.com"), "success")

    gui.IronMailApp.send_worker(app, config, senders, df, data_path, None, state)

    assert sent == ["new@example.com"]
