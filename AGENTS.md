# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## What this is

IronMail is a Windows-first bulk email sender. It ships as a Tkinter desktop app packaged into a single `.exe` with PyInstaller. A **separate** FastAPI license server (`server/`) gates every client launch: the desktop app refuses to send unless it can verify its license code online (with device binding). The codebase and all domain identifiers are Chinese — recipient columns, template markers, and config fields use terms like `邮箱`, `邮件主题`, `邮件正文`, `发件人`.

## Commands

The project targets the Windows `py` launcher (Python 3.10+). All commands assume the repo root unless noted.

```bat
:: Run the desktop app from source (also: scripts\run_source_windows.bat)
py -m pip install -r requirements.txt
py send_emails.py

:: Tests (pytest.ini sets pythonpath = src, server; testpaths = tests)
py -m pip install -r requirements-dev.txt
py -m pytest
py -m pytest tests/test_mailer.py::test_choose_sender_rotates_by_sent_count_not_row_index
```

```powershell
# Build the Windows exe -> dist\IronMail.exe (creates .venv, runs PyInstaller, copies config/ + Mails/)
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build_windows.ps1

# Re-sanitize an existing dist (overwrite dist\config\config.yaml from the example)
.\scripts\sanitize_dist.ps1
```

License server (deployed separately; importable as `ironmail_license` only from inside `server/`):

```bash
cd server
pip install -r requirements.txt
uvicorn ironmail_license.app:app --host 127.0.0.1 --port 18081
```

## Architecture

### Single GUI entry, shared helper module

- `send_emails.py` (root) → `ironmail.gui.run_app()` is the only entry point: the Tkinter GUI, and also what PyInstaller packages.
- `ironmail/main.py` contains **no UI**. It is a shared module of pure domain logic that `gui.py` imports: `scan_all_emails`, `validate_email_dataframe`, `get_app_dir`, `get_template_dir`, `format_send_error`, `write_crash_log`, `check_sensitive_words` (plus the `SENSITIVE_WORDS` list and the required-column constants).

**Entry-point invariant:** there is exactly one entry point — the GUI. There is no terminal/console/CLI mode (`cli.py` and `main.run_send_flow` were removed). Do not reintroduce one; `main.py` must stay UI-free.

### The send loop lives in the GUI worker

`gui.IronMailApp.send_worker` runs the whole send pipeline: read table → apply template → validate required columns → sensitive-word scan → resume/checkpoint prompt → per-row send with sender rotation and failover.

Per-row sending semantics (shared via `mailer`):
- `mailer.sender_candidates(senders, sent_count, emails_per_account)` rotates senders by **successful-send count**, not row index, and returns candidates starting at the current rotation slot so a failed sender fails over to the next.
- Each candidate retries `settings.max_retries` times before moving to the next sender.
- `send_progress` records each completed row to `logs/progress/<stem>-<hash>.json`. The checkpoint key combines the data file and template *identity* (path + size + mtime), so editing either file starts a fresh checkpoint. Resume/restart is offered (via a dialog) when prior progress exists.

### SMTP egress with proxy fallback

`mailer.open_smtp_connection` supports `auto` / `direct` / `proxy` modes. `auto` tries a direct connection, then falls back to a local HTTP CONNECT proxy, sweeping `candidate_ports`. The working route is cached per-process in `mailer._ROUTE_CACHE` so subsequent sends skip the probe. `license.py` mirrors this same direct→proxy fallback for the license check. `_HttpProxySMTP`/`_HttpProxySMTPSSL` subclass `smtplib` to tunnel through the proxy.

### Config is normalized centrally

`config_manager.normalize_config` is the single source of truth for config shape; `load_config`/`save_config` both run it, so older `config.yaml` files are upgraded on read. SMTP defaults are resolved per sender: a sender's own `smtp` block wins, else the global `smtp`. `smtp_defaults_for_email` auto-fills Gmail/GMX SMTP by domain. Senders without a password are filtered out of `active_senders`.

### Templates and recipient lists

- `Mails/收件名单/` holds recipient tables (`.xlsx/.xlsm/.xls/.csv`; CSV reading tries multiple encodings and delimiter sniffing). `Mails/邮件模板/` holds `.md` templates (`README.md` is excluded from selection).
- `templates.py` parses `发件人：` / `邮件主题：` / `邮件正文：` sections and substitutes `{{字段名}}` variables against table columns. `apply_template_to_dataframe` writes rendered values back into `发件人`/`邮件主题`/`邮件正文` columns, after which the send loop treats them like a legacy table.
- Required columns: with a template, only `邮箱`; without, `邮箱` + `邮件主题` + `邮件正文`.
- Legacy directory names are auto-migrated at runtime: `收件人名单`/`发件对象` → `收件名单`, and template dir `模板` → `邮件模板`.

### App directory & packaging

`main.get_app_dir()` is PyInstaller-aware: for a frozen exe it returns the executable's directory, otherwise the repo root. `config/`, `Mails/`, and `logs/` are resolved relative to it, and recipient paths are constrained to stay inside `Mails/`. **Security invariant** (enforced by `tests/test_build_scripts.py`): the build/sanitize scripts always overwrite `dist\config\config.yaml` from `config.example.yaml` — a real local `config.yaml` (which may hold app passwords) must never be packaged.

### License server (`server/ironmail_license/`)

FastAPI + SQLite + cookie-session admin UI. `POST /api/v1/licenses/verify` is the client endpoint; `/admin/*` manages codes. Codes are stored as a SHA-256 hash plus a short prefix (and a plaintext copy for admin display); a code binds to the first device that verifies it, after which other devices get `device_mismatch`. Config comes from env vars via `Settings.from_env` (`IRONMAIL_ADMIN_USERNAME/PASSWORD`, `IRONMAIL_SESSION_SECRET`, `IRONMAIL_DATA_DIR`, `IRONMAIL_DATABASE_PATH`). Production runs under systemd + nginx (`deploy/`), backend on `127.0.0.1:18081`, public at `https://tmpmail.oldiron.us`.

## Conventions

- **Testability via boundary monkeypatching**: tests stub the network and SMTP boundaries (`verify_license`, `mailer.send_email`, `mailer.test_smtp_login`, `mailer._open_direct_smtp`, `mailer._open_proxy_smtp`) instead of hitting the wire. GUI tests construct the app with `object.__new__(IronMailApp)` and drive its queue/callbacks without opening a real Tk window.
- **GUI threading**: background work runs on a worker thread; UI updates are marshaled back through `self.queue` and applied by `_drain_queue` (polled via `after`). Never touch Tk widgets directly from a worker — post a callback.
- **The PowerShell build scripts avoid literal Chinese** by constructing directory names from char-code arrays (e.g. `[char[]](0x6536,0x4ef6,0x540d,0x5355)`) to stay encoding-safe.
- A multilingual sensitive-word list in `main.SENSITIVE_WORDS` blocks sending if any subject/body matches.
