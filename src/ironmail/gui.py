# -*- coding: utf-8 -*-

from __future__ import annotations

import queue
import shutil
import threading
import traceback
import webbrowser
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from tkinter import (
    BooleanVar,
    END,
    StringVar,
    Text,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
    simpledialog,
    ttk,
)
from typing import Any, Callable

import pandas as pd

from ironmail import config_manager, mailer, recipient_lists, send_progress, templates
from ironmail.license import verify_license
from ironmail.main import (
    check_sensitive_words,
    format_send_error,
    get_app_dir,
    get_template_dir,
    scan_all_emails,
    validate_email_dataframe,
    write_crash_log,
)


APP_TITLE = "IronMail"
FONT_FAMILY = "Microsoft YaHei UI"
COLORS = {
    "bg": "#f4f6f8",
    "surface": "#ffffff",
    "surface_alt": "#f8fafc",
    "info": "#f6f8fb",
    "border": "#d7dde5",
    "text": "#172033",
    "muted": "#667085",
    "primary": "#1f3a5f",
    "primary_hover": "#182f4f",
    "danger": "#9b2f2f",
    "select": "#e8eef7",
}

SMTP_REFERENCE_LINES = [
    "Gmail / Google Workspace：SMTP 服务器 smtp.gmail.com；SSL 用 465，STARTTLS 用 587；密码填写 Google 账号生成的 16 位应用专用密码，不是网页登录密码。",
    "Gmail 应用专用密码获取地址：https://myaccount.google.com/apppasswords",
    "GMX：SMTP 服务器 mail.gmx.com；SSL/TLS 用 465，STARTTLS 用 587；密码填写 GMX 可用于 SMTP 的密码或应用密码。",
    "其他邮箱：使用服务商后台提供的 SMTP 地址、端口和安全方式。465 通常勾选 SSL，587 通常关闭 SSL 走 STARTTLS。",
]
SMTP_REFERENCE_LINKS = [
    ("获取 Gmail 应用专用密码", "https://myaccount.google.com/apppasswords"),
    ("Gmail SMTP 官方说明", "https://support.google.com/a/answer/176600"),
    ("GMX SMTP 官方参数", "https://support.gmx.com/pop-imap/imap/server.html"),
]

SETTINGS_REFERENCE_LINES = [
    "默认 SMTP 只在发件邮箱未单独填写 SMTP 时使用；Gmail 默认是 smtp.gmail.com:465 SSL。",
    "出网模式 auto 会先直连，失败后尝试本机 HTTP 代理；direct 只直连；proxy 只走代理。",
    "发送间隔越大越稳但越慢；失败重试建议保持 1 到 3；每个邮箱连续发送数控制轮换频率。",
]


def run_app() -> int:
    try:
        app = IronMailApp()
        app.mainloop()
        return 0
    except Exception as error:
        traceback_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        log_path = write_crash_log(traceback_text)
        message = f"程序发生未处理错误。\n\n{error}"
        if log_path:
            message += f"\n\n错误日志: {log_path}"
        try:
            messagebox.showerror("IronMail 错误", message)
        except Exception:
            pass
        return 1


def friendly_smtp_hint(error: Exception) -> str:
    text = str(error).lower()
    if any(mark in text for mark in ["535", "authentication", "password", "username"]):
        return (
            "排查建议：登录失败通常是邮箱密码类型不对。Gmail/Workspace 请使用 16 位应用专用密码，"
            "并确认账号已开启两步验证；GMX 请确认 SMTP 密码可用。"
        )
    if any(mark in text for mark in ["timed out", "timeout", "10060", "network", "unreachable", "refused"]):
        return (
            "排查建议：网络到 SMTP 服务器不通或被拦截。可以检查代理设置，或确认当前网络能访问 "
            "smtp.gmail.com / mail.gmx.com。"
        )
    if any(mark in text for mark in ["ssl", "tls", "certificate", "wrong version"]):
        return "排查建议：安全连接配置不匹配。465 通常开启 SSL/TLS 直连，587 通常关闭 SSL 后走 STARTTLS。"
    return "排查建议：请确认邮箱地址、SMTP 密码、SMTP 服务器、端口和安全连接方式是否匹配。"


class IronMailApp(Tk):
    def __init__(self):
        super().__init__()
        self.app_dir = get_app_dir()
        self.config_path = self.app_dir / "config" / "config.yaml"
        self.queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.config: dict[str, Any] = {}
        self.sender_rows: list[dict[str, Any]] = []
        self.recipient_files: list[Path] = []
        self.template_files: list[Path] = []
        self.selected_data_file: Path | None = None
        self.selected_template_file: Path | None = None
        self.current_send_lines: list[str] = []
        self.current_send_log_path: Path | None = None

        self.title(APP_TITLE)
        self.geometry("1120x760")
        self.minsize(980, 680)
        self.configure(background=COLORS["bg"])
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._configure_style()
        self._ensure_runtime_files()
        self.config = config_manager.load_config(self.config_path)
        self._build_shell()
        self.after(100, self._drain_queue)
        self.show_auth_view()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        self.option_add("*Font", (FONT_FAMILY, 10))
        style.configure(".", font=(FONT_FAMILY, 10), background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("App.TFrame", background=COLORS["bg"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Toolbar.TFrame", background=COLORS["surface"])
        style.configure("Info.TFrame", background=COLORS["info"])
        style.configure("TLabel", background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("Header.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=(FONT_FAMILY, 18, "bold"))
        style.configure("Subheader.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=(FONT_FAMILY, 10))
        style.configure("SurfaceTitle.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=(FONT_FAMILY, 12, "bold"))
        style.configure("Muted.TLabel", background=COLORS["surface"], foreground=COLORS["muted"])
        style.configure("InfoTitle.TLabel", background=COLORS["info"], foreground=COLORS["text"], font=(FONT_FAMILY, 10, "bold"))
        style.configure("InfoText.TLabel", background=COLORS["info"], foreground=COLORS["muted"], font=(FONT_FAMILY, 9))
        style.configure("InfoLink.TLabel", background=COLORS["info"], foreground=COLORS["primary"], font=(FONT_FAMILY, 9))
        style.configure("TButton", padding=(11, 6), background=COLORS["surface_alt"], foreground=COLORS["text"], borderwidth=1)
        style.map("TButton", background=[("active", "#eef2f7")])
        style.configure("Primary.TButton", padding=(14, 7), background=COLORS["primary"], foreground="#ffffff", borderwidth=0)
        style.map("Primary.TButton", background=[("active", COLORS["primary_hover"]), ("pressed", COLORS["primary_hover"])], foreground=[("disabled", "#d7dde5"), ("!disabled", "#ffffff")])
        style.configure("Danger.TButton", padding=(11, 6), foreground=COLORS["danger"])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 9), background=COLORS["surface_alt"], foreground=COLORS["muted"])
        style.map("TNotebook.Tab", background=[("selected", COLORS["surface"])], foreground=[("selected", COLORS["text"])])
        style.configure(
            "Treeview",
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            rowheight=28,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["surface_alt"],
            foreground=COLORS["muted"],
            relief="flat",
            font=(FONT_FAMILY, 9, "bold"),
        )
        style.map("Treeview", background=[("selected", COLORS["select"])], foreground=[("selected", COLORS["text"])])
        style.configure(
            "Panel.TLabelframe",
            background=COLORS["surface"],
            bordercolor=COLORS["border"],
            relief="solid",
        )
        style.configure(
            "Panel.TLabelframe.Label",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=(FONT_FAMILY, 10, "bold"),
        )
        style.configure("Horizontal.TProgressbar", troughcolor=COLORS["surface_alt"], background=COLORS["primary"])

    def _ensure_runtime_files(self) -> None:
        config_dir = self.app_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            source = self.app_dir / "config" / "config.example.yaml"
            if source.exists():
                shutil.copyfile(source, self.config_path)
            else:
                config_manager.save_config(self.config_path, config_manager.normalize_config({}))
        (self.app_dir / "Mails").mkdir(parents=True, exist_ok=True)
        recipient_lists.ensure_recipient_dir(self.app_dir)
        get_template_dir(self.app_dir).mkdir(parents=True, exist_ok=True)
        (self.app_dir / "logs").mkdir(parents=True, exist_ok=True)

    def _build_shell(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.container = ttk.Frame(self, padding=18, style="App.TFrame")
        self.container.grid(row=0, column=0, sticky="nsew")
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(1, weight=1)

    def _clear_container(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def _post(self, func: Callable[[], None]) -> None:
        self.queue.put(func)

    def _drain_queue(self) -> None:
        try:
            while True:
                callback = self.queue.get_nowait()
                try:
                    callback()
                except Exception as error:
                    traceback_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                    write_crash_log(traceback_text)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._drain_queue)

    def run_background(self, target: Callable[[], None]) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("任务进行中", "当前还有任务正在执行，请稍后。")
            return

        def guarded() -> None:
            try:
                target()
            except Exception as error:
                traceback_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                log_path = write_crash_log(traceback_text)
                message = f"{error}\n\n错误日志: {log_path or '写入失败'}"
                self._post(lambda message=message: messagebox.showerror("任务失败", message))

        self.worker = threading.Thread(target=guarded, daemon=True)
        self.worker.start()

    def load_config(self) -> dict[str, Any]:
        self.config = config_manager.load_config(self.config_path)
        return self.config

    def save_config(self) -> None:
        config_manager.save_config(self.config_path, self.config)

    # Auth
    def show_auth_view(self) -> None:
        self._clear_container()
        self.container.rowconfigure(1, weight=0)
        ttk.Label(self.container, text="IronMail", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self.container, text="完成授权后进入邮件发送工作台", style="Subheader.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 18)
        )
        panel = ttk.Frame(self.container, padding=24, style="Surface.TFrame", relief="solid", borderwidth=1)
        panel.grid(row=2, column=0, sticky="ew")
        panel.columnconfigure(1, weight=1)

        license_config = self.config.setdefault("license", {})
        self.auth_code_var = StringVar(value=str(license_config.get("code") or ""))
        self.auth_status_var = StringVar(value="请输入授权码并验证。")
        ttk.Label(panel, text="授权验证", style="SurfaceTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        ttk.Label(panel, text="授权码").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Entry(panel, textvariable=self.auth_code_var, width=46).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Label(panel, textvariable=self.auth_status_var, style="Muted.TLabel").grid(row=2, column=1, sticky="w", pady=6)
        ttk.Button(panel, text="验证并进入", style="Primary.TButton", command=self.verify_auth_from_view).grid(
            row=3, column=1, sticky="w", pady=12
        )

        if self.auth_code_var.get().strip():
            self.auth_status_var.set("检测到已保存授权码，可直接验证。")

    def verify_auth_from_view(self) -> None:
        code = self.auth_code_var.get().strip()
        if not code:
            messagebox.showwarning("缺少授权码", "请先填写授权码。")
            return
        self.config.setdefault("license", {})["code"] = code
        self.save_config()
        self.auth_status_var.set("正在连接授权服务器...")

        def task() -> None:
            output = StringIO()
            with redirect_stdout(output):
                ok = verify_license(self.config)
            if ok:
                config_manager.save_config(self.config_path, self.config)
                self._post(self.show_main_view)
            else:
                message = output.getvalue().strip() or "授权验证未通过，请检查授权码或网络。"
                status = message.splitlines()[-1]
                self._post(lambda status=status: self.auth_status_var.set(status))

        self.run_background(task)

    # Main shell
    def show_main_view(self) -> None:
        self._clear_container()
        self.container.rowconfigure(1, weight=1)
        header = ttk.Frame(self.container, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="IronMail 邮件发送工作台", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        self.main_summary_var = StringVar(value="正在读取配置...")
        ttk.Label(header, textvariable=self.main_summary_var, style="Subheader.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Button(header, text="刷新", command=self.refresh_all).grid(row=0, column=1, rowspan=2, padx=(8, 0), sticky="e")

        self.tabs = ttk.Notebook(self.container)
        self.tabs.grid(row=1, column=0, sticky="nsew")
        self.send_tab = ttk.Frame(self.tabs, padding=16, style="Surface.TFrame")
        self.senders_tab = ttk.Frame(self.tabs, padding=16, style="Surface.TFrame")
        self.recipients_tab = ttk.Frame(self.tabs, padding=16, style="Surface.TFrame")
        self.templates_tab = ttk.Frame(self.tabs, padding=16, style="Surface.TFrame")
        self.settings_tab = ttk.Frame(self.tabs, padding=16, style="Surface.TFrame")
        self.logs_tab = ttk.Frame(self.tabs, padding=16, style="Surface.TFrame")

        for tab, title in [
            (self.send_tab, "发送邮件"),
            (self.senders_tab, "发件邮箱"),
            (self.recipients_tab, "收件名单"),
            (self.templates_tab, "邮件模板"),
            (self.settings_tab, "配置"),
            (self.logs_tab, "日志"),
        ]:
            self.tabs.add(tab, text=title)

        self._build_send_tab()
        self._build_senders_tab()
        self._build_recipients_tab()
        self._build_templates_tab()
        self._build_settings_tab()
        self._build_logs_tab()
        self.refresh_all()

    def refresh_all(self) -> None:
        self.load_config()
        self.refresh_send_tab()
        self.refresh_senders()
        self.refresh_recipients()
        self.refresh_templates()
        self.refresh_settings()
        self.refresh_logs()
        self.update_main_summary()

    def update_main_summary(self) -> None:
        if not hasattr(self, "main_summary_var"):
            return
        active_count = len(config_manager.active_senders(self.config))
        self.main_summary_var.set(
            f"{active_count} 个可用发件邮箱 · {len(self.recipient_files)} 个收件名单 · {len(self.template_files)} 个模板"
        )

    # Send tab
    def _build_send_tab(self) -> None:
        self.send_tab.columnconfigure(0, weight=1)
        self.send_tab.columnconfigure(1, weight=1)
        self.send_tab.rowconfigure(3, weight=1)

        left = ttk.LabelFrame(self.send_tab, text="选择收件名单", padding=10, style="Panel.TLabelframe")
        right = ttk.LabelFrame(self.send_tab, text="选择邮件模板", padding=10, style="Panel.TLabelframe")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        left.columnconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.data_tree = ttk.Treeview(left, columns=("size", "modified"), show="tree headings", height=6)
        self.data_tree.heading("#0", text="文件")
        self.data_tree.heading("size", text="大小")
        self.data_tree.heading("modified", text="修改时间")
        self.data_tree.grid(row=0, column=0, sticky="nsew")
        self.data_tree.bind("<<TreeviewSelect>>", lambda event: self.on_data_selected())

        self.template_tree = ttk.Treeview(right, columns=("modified",), show="tree headings", height=6)
        self.template_tree.heading("#0", text="模板")
        self.template_tree.heading("modified", text="修改时间")
        self.template_tree.grid(row=0, column=0, sticky="nsew")
        self.template_tree.bind("<<TreeviewSelect>>", lambda event: self.on_template_selected())

        controls = ttk.Frame(self.send_tab, style="Toolbar.TFrame")
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)
        controls.columnconfigure(3, weight=1)
        ttk.Button(controls, text="预览数据", command=self.preview_selected_data).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(controls, text="预览模板", command=self.preview_selected_template).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(controls, text="开始发送", style="Primary.TButton", command=self.start_send).grid(row=0, column=2)
        self.send_status_var = StringVar(value="待发送")
        ttk.Label(controls, textvariable=self.send_status_var, style="Muted.TLabel").grid(row=0, column=3, sticky="e")

        self.progress = ttk.Progressbar(self.send_tab, mode="determinate")
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.send_log = Text(self.send_tab, height=16, wrap="word")
        self.configure_text_widget(self.send_log, monospace=True)
        self.send_log.grid(row=3, column=0, columnspan=2, sticky="nsew")

    def refresh_send_tab(self) -> None:
        for item in self.data_tree.get_children():
            self.data_tree.delete(item)
        data_dir = recipient_lists.ensure_recipient_dir(self.app_dir)
        try:
            self.recipient_files = recipient_lists.list_recipient_files(data_dir)
        except FileNotFoundError:
            self.recipient_files = []
        for index, file_path in enumerate(self.recipient_files):
            stat = file_path.stat()
            self.data_tree.insert(
                "",
                END,
                iid=str(index),
                text=file_path.name,
                values=(f"{max(1, round(stat.st_size / 1024))} KB", self._mtime(stat.st_mtime)),
            )

        for item in self.template_tree.get_children():
            self.template_tree.delete(item)
        template_dir = get_template_dir(self.app_dir)
        try:
            self.template_files = templates.list_template_files(template_dir)
        except FileNotFoundError:
            self.template_files = []
        for index, file_path in enumerate(self.template_files):
            self.template_tree.insert("", END, iid=str(index), text=file_path.name, values=(self._mtime(file_path.stat().st_mtime),))

    def on_data_selected(self) -> None:
        selection = self.data_tree.selection()
        self.selected_data_file = self.recipient_files[int(selection[0])] if selection else None

    def on_template_selected(self) -> None:
        selection = self.template_tree.selection()
        self.selected_template_file = self.template_files[int(selection[0])] if selection else None

    def preview_selected_data(self) -> None:
        if not self.selected_data_file:
            messagebox.showinfo("请选择名单", "请先选择一个收件名单。")
            return
        try:
            df = recipient_lists.read_table(self.selected_data_file)
        except Exception as error:
            messagebox.showerror("读取失败", str(error))
            return
        self.show_text_window(f"预览 - {self.selected_data_file.name}", df.head(20).to_string(index=False))

    def preview_selected_template(self) -> None:
        if not self.selected_template_file:
            messagebox.showinfo("请选择模板", "请先选择一个邮件模板。")
            return
        self.show_text_window(
            f"预览 - {self.selected_template_file.name}",
            self.selected_template_file.read_text(encoding="utf-8-sig"),
        )

    def start_send(self) -> None:
        if not self.selected_data_file:
            messagebox.showwarning("缺少名单", "请选择收件名单。")
            return
        if not self.selected_template_file:
            if not messagebox.askyesno("未选择模板", "未选择模板。只有名单里包含“邮件主题”和“邮件正文”列时才能发送，继续吗？"):
                return
        config = self.load_config()
        senders = config_manager.active_senders(config)
        if not senders:
            messagebox.showwarning("缺少发件邮箱", "请先在“发件邮箱”里添加可用邮箱。")
            return
        try:
            df = recipient_lists.read_table(self.selected_data_file)
            template_path = self.selected_template_file
            if template_path:
                email_template = templates.parse_template_file(template_path)
                missing_columns = templates.find_missing_template_columns(email_template, df)
                if missing_columns:
                    messagebox.showerror("模板变量缺失", f"名单缺少字段: {', '.join(missing_columns)}")
                    return
                df = templates.apply_template_to_dataframe(df, email_template)
            errors = validate_email_dataframe(df, use_template=template_path is not None)
            if errors:
                messagebox.showerror("表格检查未通过", "\n".join(errors))
                return
            violations = scan_all_emails(df)
            if violations:
                messagebox.showerror("内容审核未通过", f"以下行需要修改: {', '.join(map(str, violations))}")
                return
            progress_state = self.prepare_progress_state(self.selected_data_file, template_path, len(df))
            if progress_state is None:
                return
        except Exception as error:
            messagebox.showerror("发送准备失败", str(error))
            return

        self.current_send_lines = []
        self.send_log.delete("1.0", END)
        self.progress["maximum"] = len(df)
        self.progress["value"] = 0
        self.send_status_var.set("发送中...")
        self.run_background(lambda: self.send_worker(config, senders, df, self.selected_data_file, template_path, progress_state))

    def prepare_progress_state(self, data_path: Path, template_path: Path | None, total_rows: int) -> dict[str, Any] | None:
        state = send_progress.load_progress(self.app_dir, data_path, template_path)
        completed, total = send_progress.progress_summary(state, total_rows)
        if completed == 0:
            return state
        if completed >= total:
            if messagebox.askyesno("检测到已完成记录", f"这组名单上次已全部发送完成，是否重新发送？\n已完成: {completed}/{total}"):
                send_progress.reset_progress(state)
                return state
            return None
        choice = messagebox.askyesnocancel(
            "检测到断点记录",
            f"已完成: {completed}/{total}\n\n是: 继续未完成部分\n否: 重新发送全部\n取消: 返回",
        )
        if choice is None:
            return None
        if choice is False:
            send_progress.reset_progress(state)
        return state

    def send_worker(
        self,
        config: dict[str, Any],
        senders: list[dict[str, Any]],
        df: pd.DataFrame,
        data_path: Path,
        template_path: Path | None,
        progress_state: dict[str, Any],
    ) -> None:
        settings = config["settings"]
        emails_per_account = settings.get("emails_per_account", 1)
        success_count = 0
        fail_count = 0
        skipped_count = 0
        send_attempt_count = 0
        log_file = self.app_dir / settings.get("log_file", "logs/send_log.txt")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        self.current_send_log_path = log_file
        try:
            self.gui_log(f"开始发送: {data_path.name} | 模板: {template_path.name if template_path else '表格内容'}")
            self.gui_log(f"共 {len(df)} 封邮件，发件邮箱 {len(senders)} 个。")

            for index, row in df.iterrows():
                recipient_email = str(row["邮箱"]).strip()
                row_key = send_progress.row_key(index, recipient_email)
                self._post(lambda value=index: self.progress.configure(value=value))
                if send_progress.is_row_completed(progress_state, row_key):
                    skipped_count += 1
                    self.gui_log(f"[{index + 1}/{len(df)}] 跳过断点记录 -> {recipient_email}")
                    continue
                if not recipient_email or recipient_email == "nan":
                    skipped_count += 1
                    send_progress.mark_row_completed(progress_state, row_key, "skipped_empty_email")
                    self.gui_log(f"[{index + 1}/{len(df)}] 跳过空邮箱")
                    continue
                subject = str(row["邮件主题"]).strip()
                body = str(row["邮件正文"]).strip()
                sent = False
                max_retries = int(settings.get("max_retries", 3))
                candidates = mailer.sender_candidates(senders, send_attempt_count, emails_per_account)
                for sender_offset, current_sender in enumerate(candidates):
                    smtp_config = config_manager.resolve_sender_smtp(config, current_sender)
                    smtp_config["proxy"] = config.get("smtp_proxy", {})
                    if sender_offset:
                        self.gui_log(f"[{index + 1}/{len(df)}] 切换发件邮箱重试 -> {current_sender['email']}")
                    for attempt in range(max_retries):
                        try:
                            mailer.send_email(smtp_config, current_sender, recipient_email, subject, body)
                            success_count += 1
                            send_attempt_count += 1
                            sent = True
                            send_progress.mark_row_completed(progress_state, row_key, "success")
                            self.gui_log(
                                f"[{index + 1}/{len(df)}] 成功 -> {recipient_email} (发件人: {current_sender['email']})"
                            )
                            break
                        except Exception as error:
                            error_text = format_send_error(error)
                            if attempt < max_retries - 1:
                                self.gui_log(f"[{index + 1}/{len(df)}] 重试 {attempt + 1} -> {recipient_email}: {error_text}")
                            elif sender_offset < len(candidates) - 1:
                                self.gui_log(
                                    f"[{index + 1}/{len(df)}] 发件邮箱 {current_sender['email']} 不可用，准备切换: {error_text}"
                                )
                            else:
                                fail_count += 1
                                self.gui_log(f"[{index + 1}/{len(df)}] 失败 -> {recipient_email}: {error_text}")
                    if sent:
                        break
                if not sent:
                    continue
                delay = int(settings.get("delay_seconds", 12))
                if index < len(df) - 1 and delay > 0:
                    threading.Event().wait(delay)

            self._post(lambda: self.progress.configure(value=len(df)))
            self.gui_log(f"发送完成。成功 {success_count}，失败 {fail_count}，跳过 {skipped_count}。")
            summary = f"完成：成功 {success_count}，失败 {fail_count}，跳过 {skipped_count}"
            self._post(lambda summary=summary: self.send_status_var.set(summary))
        finally:
            self.current_send_log_path = None

    def gui_log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n"
        self.current_send_lines.append(line)
        if self.current_send_log_path:
            with self.current_send_log_path.open("a", encoding="utf-8") as file:
                file.write(line)
        self._post(lambda line=line: (self.send_log.insert(END, line), self.send_log.see(END)))

    # Senders tab
    def _build_senders_tab(self) -> None:
        self.senders_tab.columnconfigure(0, weight=1)
        self.senders_tab.rowconfigure(1, weight=1)
        self.add_info_panel(self.senders_tab, "SMTP 配置参考", SMTP_REFERENCE_LINES, row=0, links=SMTP_REFERENCE_LINKS)
        self.sender_tree = ttk.Treeview(
            self.senders_tab,
            columns=("name", "smtp"),
            show="tree headings",
            height=14,
        )
        self.sender_tree.heading("#0", text="邮箱")
        self.sender_tree.heading("name", text="显示名称")
        self.sender_tree.heading("smtp", text="SMTP")
        self.sender_tree.grid(row=1, column=0, sticky="nsew")
        buttons = ttk.Frame(self.senders_tab, style="Toolbar.TFrame")
        buttons.grid(row=2, column=0, sticky="ew", pady=10)
        ttk.Button(buttons, text="新增", command=lambda: self.open_sender_dialog()).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="修改", command=self.edit_selected_sender).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(buttons, text="删除", command=self.delete_selected_sender).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(buttons, text="测试选中", command=self.test_selected_sender).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(buttons, text="测试全部", command=self.test_all_senders).grid(row=0, column=4, padx=(0, 8))

    def refresh_senders(self) -> None:
        for item in self.sender_tree.get_children():
            self.sender_tree.delete(item)
        self.sender_rows = self.config.get("senders", [])
        for index, sender in enumerate(self.sender_rows):
            smtp = config_manager.resolve_sender_smtp(self.config, sender)
            self.sender_tree.insert(
                "",
                END,
                iid=str(index),
                text=sender.get("email", ""),
                values=(sender.get("name") or "-", f"{smtp['host']}:{smtp['port']}"),
            )

    def selected_sender(self) -> dict[str, Any] | None:
        selection = self.sender_tree.selection()
        return self.sender_rows[int(selection[0])] if selection else None

    def open_sender_dialog(self, sender: dict[str, Any] | None = None) -> None:
        SenderDialog(self, sender)

    def edit_selected_sender(self) -> None:
        sender = self.selected_sender()
        if not sender:
            messagebox.showinfo("请选择邮箱", "请先选择一个发件邮箱。")
            return
        self.open_sender_dialog(sender)

    def delete_selected_sender(self) -> None:
        sender = self.selected_sender()
        if not sender:
            return
        if not messagebox.askyesno("确认删除", f"删除发件邮箱 {sender['email']}？"):
            return
        config_manager.delete_sender(self.config, sender["email"])
        self.save_config()
        self.refresh_senders()

    def test_selected_sender(self) -> None:
        sender = self.selected_sender()
        if not sender:
            messagebox.showinfo("请选择邮箱", "请先选择一个发件邮箱。")
            return
        if hasattr(self, "main_summary_var"):
            self.main_summary_var.set(f"正在测试 {sender['email']} ...")
        self.run_background(lambda: self._test_sender(sender))

    def test_all_senders(self) -> None:
        senders = config_manager.active_senders(self.load_config())
        if not senders:
            messagebox.showinfo("暂无邮箱", "没有可测试的发件邮箱。")
            return
        self.run_background(lambda: [self._test_sender(sender, quiet=False) for sender in senders])

    def _test_sender(self, sender: dict[str, Any], quiet: bool = False) -> None:
        config = self.load_config()
        smtp = config_manager.resolve_sender_smtp(config, sender)
        smtp["proxy"] = config.get("smtp_proxy", {})
        email = sender["email"]
        try:
            mailer.test_smtp_login(smtp, sender)
            self._post(lambda email=email: messagebox.showinfo("SMTP 测试成功", f"{email} 登录成功。"))
            self._post(lambda email=email: self.main_summary_var.set(f"{email} SMTP 测试成功。"))
        except Exception as error:
            hint = friendly_smtp_hint(error)
            error_text = str(error)
            self._post(
                lambda email=email, error_text=error_text, hint=hint: messagebox.showerror(
                    "SMTP 测试失败",
                    f"{email}\n\n{error_text}\n\n{hint}",
                )
            )
            self._post(lambda email=email: self.main_summary_var.set(f"{email} SMTP 测试失败。"))

    # Recipients tab
    def _build_recipients_tab(self) -> None:
        self.recipients_tab.columnconfigure(0, weight=1)
        self.recipients_tab.rowconfigure(0, weight=1)
        self.recipient_tree = ttk.Treeview(self.recipients_tab, columns=("size", "modified"), show="tree headings")
        self.recipient_tree.heading("#0", text="文件")
        self.recipient_tree.heading("size", text="大小")
        self.recipient_tree.heading("modified", text="修改时间")
        self.recipient_tree.grid(row=0, column=0, sticky="nsew")
        buttons = ttk.Frame(self.recipients_tab, style="Toolbar.TFrame")
        buttons.grid(row=1, column=0, sticky="ew", pady=10)
        ttk.Button(buttons, text="打开文件夹", command=lambda: recipient_lists.open_path(recipient_lists.ensure_recipient_dir(self.app_dir))).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="导入文件", command=self.import_recipient_file).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(buttons, text="打开选中", command=self.open_selected_recipient).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(buttons, text="修改表头", command=self.rename_selected_header).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(buttons, text="删除", command=self.delete_selected_recipient).grid(row=0, column=4, padx=(0, 8))

    def refresh_recipients(self) -> None:
        for item in self.recipient_tree.get_children():
            self.recipient_tree.delete(item)
        data_dir = recipient_lists.ensure_recipient_dir(self.app_dir)
        self.recipient_files = recipient_lists.list_recipient_files(data_dir)
        for index, file_path in enumerate(self.recipient_files):
            stat = file_path.stat()
            self.recipient_tree.insert("", END, iid=str(index), text=file_path.name, values=(f"{stat.st_size} B", self._mtime(stat.st_mtime)))

    def selected_recipient_file(self) -> Path | None:
        selection = self.recipient_tree.selection()
        return self.recipient_files[int(selection[0])] if selection else None

    def import_recipient_file(self) -> None:
        source = filedialog.askopenfilename(filetypes=[("表格文件", "*.xlsx *.xlsm *.xls *.csv"), ("全部文件", "*.*")])
        if not source:
            return
        target = recipient_lists.ensure_recipient_dir(self.app_dir) / Path(source).name
        shutil.copyfile(source, target)
        self.refresh_all()

    def open_selected_recipient(self) -> None:
        file_path = self.selected_recipient_file()
        if file_path:
            recipient_lists.open_path(file_path)

    def rename_selected_header(self) -> None:
        file_path = self.selected_recipient_file()
        if not file_path:
            return
        try:
            headers = recipient_lists.read_headers(file_path)
        except Exception as error:
            messagebox.showerror("读取失败", str(error))
            return
        old_name = simpledialog.askstring("当前表头", "输入要修改的表头名称:\n" + "\n".join(headers), parent=self)
        if not old_name:
            return
        new_name = simpledialog.askstring("新的表头", f"{old_name} 改为:", parent=self)
        if not new_name:
            return
        try:
            recipient_lists.rename_header(file_path, old_name, new_name)
            self.refresh_all()
        except Exception as error:
            messagebox.showerror("修改失败", str(error))

    def delete_selected_recipient(self) -> None:
        file_path = self.selected_recipient_file()
        if file_path and messagebox.askyesno("确认删除", f"删除 {file_path.name}？"):
            file_path.unlink()
            self.refresh_all()

    # Templates tab
    def _build_templates_tab(self) -> None:
        self.templates_tab.columnconfigure(0, weight=1)
        self.templates_tab.columnconfigure(1, weight=1)
        self.templates_tab.rowconfigure(0, weight=1)
        self.template_manage_tree = ttk.Treeview(self.templates_tab, columns=("modified",), show="tree headings")
        self.template_manage_tree.heading("#0", text="模板")
        self.template_manage_tree.heading("modified", text="修改时间")
        self.template_manage_tree.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.template_text = Text(self.templates_tab, wrap="word")
        self.template_text.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.template_manage_tree.bind("<<TreeviewSelect>>", lambda event: self.show_selected_template_content())
        self.configure_text_widget(self.template_text)
        buttons = ttk.Frame(self.templates_tab, style="Toolbar.TFrame")
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Button(buttons, text="新增", command=self.create_template).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="保存内容", command=self.save_selected_template_content).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(buttons, text="打开选中", command=self.open_selected_template).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(buttons, text="删除", command=self.delete_selected_template).grid(row=0, column=3, padx=(0, 8))

    def refresh_templates(self) -> None:
        for item in self.template_manage_tree.get_children():
            self.template_manage_tree.delete(item)
        template_dir = get_template_dir(self.app_dir)
        try:
            self.template_files = templates.list_template_files(template_dir)
        except FileNotFoundError:
            self.template_files = []
        for index, file_path in enumerate(self.template_files):
            self.template_manage_tree.insert("", END, iid=str(index), text=file_path.name, values=(self._mtime(file_path.stat().st_mtime),))

    def selected_template_manage_file(self) -> Path | None:
        selection = self.template_manage_tree.selection()
        return self.template_files[int(selection[0])] if selection else None

    def show_selected_template_content(self) -> None:
        file_path = self.selected_template_manage_file()
        self.template_text.delete("1.0", END)
        if file_path:
            self.template_text.insert("1.0", file_path.read_text(encoding="utf-8-sig"))

    def create_template(self) -> None:
        name = simpledialog.askstring("新增模板", "模板名称:", parent=self)
        if not name:
            return
        try:
            path = templates.create_template_file(get_template_dir(self.app_dir), name)
            recipient_lists.open_path(path)
            self.refresh_all()
        except Exception as error:
            messagebox.showerror("创建失败", str(error))

    def save_selected_template_content(self) -> None:
        file_path = self.selected_template_manage_file()
        if not file_path:
            return
        file_path.write_text(self.template_text.get("1.0", END).rstrip() + "\n", encoding="utf-8")
        self.refresh_all()

    def open_selected_template(self) -> None:
        file_path = self.selected_template_manage_file()
        if file_path:
            recipient_lists.open_path(file_path)

    def delete_selected_template(self) -> None:
        file_path = self.selected_template_manage_file()
        if file_path and messagebox.askyesno("确认删除", f"删除模板 {file_path.name}？"):
            file_path.unlink()
            self.refresh_all()

    # Settings tab
    def _build_settings_tab(self) -> None:
        self.settings_tab.columnconfigure(1, weight=1)
        self.add_info_panel(self.settings_tab, "配置说明", SETTINGS_REFERENCE_LINES, row=0, columnspan=2)
        labels = [
            ("授权码", "license_code"),
            ("默认SMTP服务器", "smtp_host"),
            ("默认SMTP端口", "smtp_port"),
            ("发送间隔秒数", "delay_seconds"),
            ("失败重试次数", "max_retries"),
            ("每个邮箱连续发送数", "emails_per_account"),
            ("出网模式 auto/direct/proxy", "proxy_mode"),
            ("代理地址", "proxy_host"),
            ("代理端口", "proxy_port"),
        ]
        self.setting_vars: dict[str, StringVar] = {}
        for row, (label, key) in enumerate(labels):
            form_row = row + 1
            ttk.Label(self.settings_tab, text=label).grid(row=form_row, column=0, sticky="w", pady=5, padx=(0, 10))
            var = StringVar()
            self.setting_vars[key] = var
            ttk.Entry(self.settings_tab, textvariable=var).grid(row=form_row, column=1, sticky="ew", pady=5)
        self.smtp_ssl_var = BooleanVar(value=True)
        ttk.Checkbutton(
            self.settings_tab,
            text="默认 SMTP 使用 SSL/TLS 直连（465 常用；关闭后使用 STARTTLS，587 常用）",
            variable=self.smtp_ssl_var,
        ).grid(row=len(labels) + 1, column=1, sticky="w", pady=5)
        ttk.Button(self.settings_tab, text="保存配置", style="Primary.TButton", command=self.save_settings_from_form).grid(
            row=len(labels) + 2, column=1, sticky="w", pady=12
        )

    def refresh_settings(self) -> None:
        config = self.config
        license_config = config.get("license", {})
        smtp = config.get("smtp", {})
        proxy = config.get("smtp_proxy", {})
        settings = config.get("settings", {})
        values = {
            "license_code": license_config.get("code") or "",
            "smtp_host": smtp.get("host") or "",
            "smtp_port": str(smtp.get("port") or ""),
            "delay_seconds": str(settings.get("delay_seconds") or ""),
            "max_retries": str(settings.get("max_retries") or ""),
            "emails_per_account": str(settings.get("emails_per_account") or ""),
            "proxy_mode": proxy.get("mode") or "auto",
            "proxy_host": proxy.get("host") or "127.0.0.1",
            "proxy_port": str(proxy.get("port") or ""),
        }
        for key, value in values.items():
            self.setting_vars[key].set(value)
        self.smtp_ssl_var.set(bool(smtp.get("use_ssl", True)))

    def save_settings_from_form(self) -> None:
        config = self.load_config()
        config.setdefault("license", {})["code"] = self.setting_vars["license_code"].get().strip()
        config["smtp"] = config_manager.normalize_smtp(
            {
                "host": self.setting_vars["smtp_host"].get().strip(),
                "port": int(self.setting_vars["smtp_port"].get() or 465),
                "use_ssl": self.smtp_ssl_var.get(),
            }
        )
        settings = config.setdefault("settings", {})
        settings["delay_seconds"] = max(0, int(self.setting_vars["delay_seconds"].get() or 12))
        settings["max_retries"] = max(1, int(self.setting_vars["max_retries"].get() or 3))
        settings["emails_per_account"] = max(1, int(self.setting_vars["emails_per_account"].get() or 1))
        proxy = config.setdefault("smtp_proxy", {})
        proxy.update(
            {
                "mode": self.setting_vars["proxy_mode"].get().strip() or "auto",
                "host": self.setting_vars["proxy_host"].get().strip() or "127.0.0.1",
                "port": int(self.setting_vars["proxy_port"].get() or 7897),
            }
        )
        config["smtp_proxy"] = config_manager.normalize_smtp_proxy(proxy)
        self.config = config
        self.save_config()
        messagebox.showinfo("已保存", "配置已保存。")
        self.refresh_all()

    # Logs tab
    def _build_logs_tab(self) -> None:
        self.logs_tab.columnconfigure(0, weight=1)
        self.logs_tab.rowconfigure(1, weight=1)
        buttons = ttk.Frame(self.logs_tab, style="Toolbar.TFrame")
        buttons.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(buttons, text="刷新日志", command=self.refresh_logs).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="打开日志文件夹", command=lambda: recipient_lists.open_path(self.app_dir / "logs")).grid(row=0, column=1)
        self.logs_text = Text(self.logs_tab, wrap="word")
        self.configure_text_widget(self.logs_text, monospace=True)
        self.logs_text.grid(row=1, column=0, sticky="nsew")

    def refresh_logs(self) -> None:
        if not hasattr(self, "logs_text"):
            return
        self.logs_text.delete("1.0", END)
        for path in [self.app_dir / "logs" / "send_log.txt", self.app_dir / "logs" / "crash.log"]:
            self.logs_text.insert(END, f"===== {path.name} =====\n")
            if path.exists():
                self.logs_text.insert(END, path.read_text(encoding="utf-8", errors="replace")[-8000:])
            else:
                self.logs_text.insert(END, "暂无日志\n")
            self.logs_text.insert(END, "\n")

    def show_text_window(self, title: str, content: str) -> None:
        window = Toplevel(self)
        window.title(title)
        window.geometry("820x520")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        text = Text(window, wrap="none")
        self.configure_text_widget(text, monospace=True)
        text.grid(row=0, column=0, sticky="nsew")
        text.insert("1.0", content)

    def add_info_panel(
        self,
        parent: ttk.Frame,
        title: str,
        lines: list[str],
        row: int,
        column: int = 0,
        columnspan: int = 1,
        wraplength: int = 960,
        pady: tuple[int, int] = (0, 12),
        links: list[tuple[str, str]] | None = None,
    ) -> ttk.Frame:
        panel = ttk.Frame(parent, padding=(12, 10), style="Info.TFrame", relief="solid", borderwidth=1)
        panel.grid(row=row, column=column, columnspan=columnspan, sticky="ew", pady=pady)
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text=title, style="InfoTitle.TLabel").grid(row=0, column=0, sticky="w")
        for index, line in enumerate(lines, start=1):
            ttk.Label(
                panel,
                text=line,
                style="InfoText.TLabel",
                wraplength=wraplength,
                justify="left",
            ).grid(row=index, column=0, sticky="w", pady=(4 if index == 1 else 2, 0))
        if links:
            link_frame = ttk.Frame(panel, style="Info.TFrame")
            link_frame.grid(row=len(lines) + 1, column=0, sticky="w", pady=(8, 0))
            for index, (label, url) in enumerate(links):
                link = ttk.Label(link_frame, text=label, style="InfoLink.TLabel", cursor="hand2")
                link.grid(row=0, column=index, sticky="w", padx=(0, 16))
                link.bind("<Button-1>", lambda _event, target=url: self.open_url(target))
        return panel

    def open_url(self, url: str) -> None:
        try:
            webbrowser.open_new_tab(url)
        except Exception as error:
            messagebox.showerror("打开链接失败", str(error))

    def configure_text_widget(self, widget: Text, monospace: bool = False) -> None:
        font = ("Consolas", 10) if monospace else (FONT_FAMILY, 10)
        widget.configure(
            background=COLORS["surface"],
            foreground=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["primary"],
            padx=10,
            pady=8,
            font=font,
        )

    @staticmethod
    def _mtime(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


class SenderDialog(Toplevel):
    def __init__(self, app: IronMailApp, sender: dict[str, Any] | None = None):
        super().__init__(app)
        self.app = app
        self.sender = sender
        self.title("发件邮箱")
        self.resizable(False, False)
        self.configure(background=COLORS["surface"])
        self.email_var = StringVar(value=sender.get("email", "") if sender else "")
        self.name_var = StringVar(value=sender.get("name", "") if sender else "")
        self.password_var = StringVar(value=sender.get("password", "") if sender else "")
        smtp = sender.get("smtp", {}) if sender else {}
        self.smtp_host_var = StringVar(value=smtp.get("host", "") if smtp else "")
        self.smtp_port_var = StringVar(value=str(smtp.get("port", 465) if smtp else 465))
        self.smtp_ssl_var = BooleanVar(value=bool(smtp.get("use_ssl", True)) if smtp else True)
        self._build()
        self.grab_set()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=16, style="Surface.TFrame")
        frame.grid(row=0, column=0, sticky="nsew")
        fields = [
            ("邮箱地址", self.email_var),
            ("显示名称", self.name_var),
            ("SMTP密码/应用密码", self.password_var),
            ("SMTP服务器（可留空自动识别）", self.smtp_host_var),
            ("SMTP端口", self.smtp_port_var),
        ]
        for row, (label, var) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
            show = "*" if "密码" in label else None
            ttk.Entry(frame, textvariable=var, show=show, width=56).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Checkbutton(
            frame,
            text="使用 SSL/TLS 直连（465 常用；关闭后使用 STARTTLS，587 常用）",
            variable=self.smtp_ssl_var,
        ).grid(row=len(fields), column=1, sticky="w", pady=5)
        self.app.add_info_panel(
            frame,
            "常用服务商参数",
            SMTP_REFERENCE_LINES,
            row=len(fields) + 1,
            column=0,
            columnspan=2,
            wraplength=660,
            pady=(10, 4),
            links=SMTP_REFERENCE_LINKS,
        )
        buttons = ttk.Frame(frame, style="Toolbar.TFrame")
        buttons.grid(row=len(fields) + 2, column=1, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="保存", command=self.save).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="取消", command=self.destroy).grid(row=0, column=1)

    def save(self) -> None:
        email = self.email_var.get().strip()
        password = self.password_var.get()
        if not email or not password:
            messagebox.showwarning("缺少信息", "邮箱和密码不能为空。", parent=self)
            return
        smtp_host = self.smtp_host_var.get().strip()
        sender = config_manager.build_sender(
            email=email,
            password=password,
            name=self.name_var.get().strip(),
            smtp_host=smtp_host,
            smtp_port=int(self.smtp_port_var.get() or 465),
            smtp_use_ssl=self.smtp_ssl_var.get(),
        )
        if not smtp_host:
            defaults = config_manager.smtp_defaults_for_email(email)
            if defaults != config_manager.DEFAULT_SMTP:
                sender["smtp"] = defaults
        config = self.app.load_config()
        try:
            if self.sender:
                updates = dict(sender)
                config_manager.update_sender(config, self.sender["email"], updates)
            else:
                config_manager.add_sender(config, sender)
            self.app.config = config
            self.app.save_config()
            self.app.refresh_all()
            self.destroy()
        except Exception as error:
            messagebox.showerror("保存失败", str(error), parent=self)
