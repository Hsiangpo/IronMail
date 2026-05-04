# -*- coding: utf-8 -*-

import queue
from pathlib import Path

from ironmail import config_manager, gui


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
