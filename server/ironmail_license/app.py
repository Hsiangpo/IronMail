# -*- coding: utf-8 -*-
from __future__ import annotations

"""IronMail授权服务入口。"""

import json
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from ironmail_license import db
from ironmail_license.settings import Settings


settings = Settings.from_env()
db.init_db(settings.database_path)

app = FastAPI(title="IronMail License Server")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """健康检查。"""
    return {"status": "ok"}


@app.post("/api/v1/licenses/verify")
async def verify_license(request: Request) -> JSONResponse:
    """客户端授权码验证接口。"""
    try:
        payload = await request.json()
        code = str(payload.get("code") or "")
        device_id = str(payload.get("device_id") or "")
        app_version = str(payload.get("app_version") or "")
        if not device_id:
            return JSONResponse({"valid": False, "reason": "missing_device_id"})

        with db.connect(settings.database_path) as conn:
            result = db.verify_license(conn, code, device_id, app_version)
        return JSONResponse(result)
    except Exception:
        return JSONResponse({"valid": False, "reason": "server_error"}, status_code=500)


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    """根路径跳转到管理后台。"""
    return RedirectResponse("/admin/licenses", status_code=302)


@app.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    """登录页。"""
    if request.session.get("admin"):
        return RedirectResponse("/admin/licenses", status_code=302)
    return HTMLResponse(_page("管理员登录", _login_form("")))


@app.post("/admin/login")
async def login(request: Request) -> HTMLResponse:
    """处理登录。"""
    form = await request.form()
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    if username == settings.admin_username and password == settings.admin_password:
        request.session["admin"] = True
        return RedirectResponse("/admin/licenses", status_code=302)
    return HTMLResponse(_page("管理员登录", _login_form("账号或密码错误")), status_code=401)


@app.post("/admin/logout")
def logout(request: Request) -> RedirectResponse:
    """退出登录。"""
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)


@app.get("/admin/licenses", response_class=HTMLResponse)
def admin_licenses(request: Request) -> HTMLResponse:
    """授权码管理页。"""
    redirect = _require_admin(request)
    if redirect:
        return redirect
    with db.connect(settings.database_path) as conn:
        licenses = db.list_licenses(conn)
    body = _admin_body(licenses, request.query_params.get("created"))
    return HTMLResponse(_page("授权码管理", body))


@app.post("/admin/licenses/create")
async def create_license(request: Request) -> RedirectResponse:
    """创建授权码。"""
    redirect = _require_admin(request)
    if redirect:
        return redirect
    form = await request.form()
    note = str(form.get("note") or "")
    expires_at = str(form.get("expires_at") or "") or None
    with db.connect(settings.database_path) as conn:
        code = db.create_license(conn, note, expires_at)
    return RedirectResponse(f"/admin/licenses?created={code}", status_code=302)


@app.post("/admin/licenses/{license_id}/update")
async def update_license(license_id: int, request: Request) -> RedirectResponse:
    """更新授权码。"""
    redirect = _require_admin(request)
    if redirect:
        return redirect
    form = await request.form()
    note = str(form.get("note") or "")
    status = str(form.get("status") or "active")
    expires_at = str(form.get("expires_at") or "") or None
    with db.connect(settings.database_path) as conn:
        db.update_license(conn, license_id, note, status, expires_at)
    return RedirectResponse("/admin/licenses", status_code=302)


@app.post("/admin/licenses/{license_id}/unbind")
def unbind_license(license_id: int, request: Request) -> RedirectResponse:
    """解绑授权码设备。"""
    redirect = _require_admin(request)
    if redirect:
        return redirect
    with db.connect(settings.database_path) as conn:
        db.unbind_license(conn, license_id)
    return RedirectResponse("/admin/licenses", status_code=302)


@app.post("/admin/licenses/{license_id}/delete")
def delete_license(license_id: int, request: Request) -> RedirectResponse:
    """删除授权码。"""
    redirect = _require_admin(request)
    if redirect:
        return redirect
    with db.connect(settings.database_path) as conn:
        db.delete_license(conn, license_id)
    return RedirectResponse("/admin/licenses", status_code=302)


def _require_admin(request: Request) -> RedirectResponse | None:
    """检查管理员登录态。"""
    if request.session.get("admin"):
        return None
    return RedirectResponse("/admin/login", status_code=302)


def _page(title: str, body: str) -> str:
    """渲染基础页面。"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - IronMail</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f7fb;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --line: #dbe4f0;
      --line-strong: #c9d6e6;
      --text: #111827;
      --muted: #64748b;
      --primary: #2563eb;
      --primary-dark: #1d4ed8;
      --danger: #dc2626;
      --danger-dark: #b91c1c;
      --success-bg: #ecfdf3;
      --success-text: #166534;
      --warning-bg: #fff7ed;
      --warning-text: #9a3412;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      background: #111827;
      color: #fff;
      padding: 18px 28px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }}
    header strong {{ font-size: 17px; letter-spacing: 0; }}
    header span {{ color: #cbd5e1; font-size: 13px; }}
    main.dashboard-shell {{ max-width: 1180px; margin: 28px auto 48px; padding: 0 20px; }}
    .page-title {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 18px; }}
    .page-title h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
    .page-title p {{ margin: 8px 0 0; color: var(--muted); }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.05);
    }}
    .panel-pad {{ padding: 22px; }}
    .stack {{ display: grid; gap: 18px; }}
    .stat-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .stat-card {{ padding: 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }}
    .stat-label {{ color: var(--muted); font-size: 13px; }}
    .stat-value {{ margin-top: 8px; font-size: 26px; font-weight: 700; }}
    .toolbar {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; }}
    .toolbar h2 {{ margin: 0; font-size: 20px; }}
    .create-form {{ display: grid; grid-template-columns: minmax(220px, 1fr) 190px auto; gap: 12px; align-items: end; }}
    label {{ display: grid; gap: 6px; color: #334155; font-weight: 600; font-size: 13px; }}
    input, select {{
      display: block;
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--line-strong);
      border-radius: 7px;
      background: #fff;
      color: var(--text);
      font: inherit;
      min-width: 0;
    }}
    input:focus, select:focus {{ outline: 2px solid rgba(37, 99, 235, 0.18); border-color: var(--primary); }}
    button {{
      padding: 10px 14px;
      border: 0;
      border-radius: 7px;
      background: var(--primary);
      color: #fff;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}
    button:hover {{ background: var(--primary-dark); }}
    .button-secondary {{ background: #475569; }}
    .button-secondary:hover {{ background: #334155; }}
    .danger {{ background: var(--danger); }}
    .danger:hover {{ background: var(--danger-dark); }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    .code {{
      background: var(--success-bg);
      border: 1px solid #bbf7d0;
      color: #14532d;
      padding: 14px 16px;
      border-radius: 7px;
      font-weight: 800;
      letter-spacing: 0.02em;
      overflow-x: auto;
    }}
    .error {{ background: #fef2f2; color: #991b1b; padding: 12px; border-radius: 7px; border: 1px solid #fecaca; }}
    .table-shell {{ overflow-x: auto; border-radius: 8px; border: 1px solid var(--line); background: var(--surface); }}
    table {{ width: 100%; border-collapse: separate; border-spacing: 0; min-width: 1080px; }}
    th, td {{ padding: 14px 12px; border-bottom: 1px solid #e8eef6; text-align: left; vertical-align: middle; }}
    th {{ background: #f1f5f9; color: #334155; font-size: 13px; font-weight: 800; }}
    tbody tr:hover {{ background: var(--surface-soft); }}
    tbody tr:last-child td {{ border-bottom: 0; }}
    .status-badge {{ display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 800; }}
    .status-active {{ background: var(--success-bg); color: var(--success-text); }}
    .status-disabled {{ background: var(--warning-bg); color: var(--warning-text); }}
    .status-badge + select {{ margin-top: 8px; }}
    .value-cell {{ display: grid; gap: 8px; min-width: 170px; }}
    .compact-value {{ color: #1e293b; font-weight: 800; word-break: break-all; }}
    .link-button {{
      width: fit-content;
      padding: 6px 10px;
      background: #eff6ff;
      color: #1d4ed8;
      border: 1px solid #bfdbfe;
      font-size: 12px;
    }}
    .link-button:hover {{ background: #dbeafe; }}
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: rgba(15, 23, 42, 0.5);
      z-index: 20;
    }}
    .modal-backdrop.open {{ display: flex; }}
    .modal-card {{
      width: min(720px, 100%);
      max-height: min(70vh, 620px);
      overflow: auto;
      background: #fff;
      border-radius: 8px;
      box-shadow: 0 24px 70px rgba(15, 23, 42, 0.25);
    }}
    .modal-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 20px;
      border-bottom: 1px solid var(--line);
    }}
    .modal-head h2 {{ margin: 0; font-size: 18px; }}
    .modal-body {{ padding: 20px; white-space: pre-wrap; word-break: break-all; line-height: 1.6; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .actions form {{ margin: 0; }}
    .empty-state {{ padding: 28px; color: var(--muted); text-align: center; }}
    .login-shell {{ max-width: 420px; margin: 70px auto; padding: 0 20px; }}
    .login-shell h1 {{ margin-top: 0; }}
    @media (max-width: 780px) {{
      header {{ padding: 16px 18px; }}
      main.dashboard-shell {{ margin-top: 20px; padding: 0 14px; }}
      .page-title, .toolbar {{ display: grid; }}
      .stat-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .create-form {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header><strong>IronMail 授权管理</strong><span>管理后台</span></header>
  {body}
  <div id="detail-modal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="detail-modal-title">
    <div class="modal-card">
      <div class="modal-head">
        <h2 id="detail-modal-title">详情</h2>
        <button class="button-secondary" type="button" onclick="closeDetailModal()">关闭</button>
      </div>
      <div id="detail-modal-body" class="modal-body"></div>
    </div>
  </div>
  <script>
    function openDetailModal(title, content) {{
      document.getElementById("detail-modal-title").textContent = title;
      document.getElementById("detail-modal-body").textContent = content;
      document.getElementById("detail-modal").classList.add("open");
    }}
    function closeDetailModal() {{
      document.getElementById("detail-modal").classList.remove("open");
    }}
    document.addEventListener("keydown", function(event) {{
      if (event.key === "Escape") closeDetailModal();
    }});
    document.getElementById("detail-modal").addEventListener("click", function(event) {{
      if (event.target.id === "detail-modal") closeDetailModal();
    }});
  </script>
</body>
</html>"""


def _login_form(error: str) -> str:
    """渲染登录表单。"""
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return f"""
<main class="login-shell">
  <section class="panel panel-pad stack">
    <div>
      <h1>管理员登录</h1>
      <p class="muted">登录后可以创建、停用、解绑和删除授权码。</p>
    </div>
    {error_html}
    <form class="stack" method="post" action="/admin/login">
      <label>账号<input name="username" autocomplete="username"></label>
      <label>密码<input name="password" type="password" autocomplete="current-password"></label>
      <button type="submit">登录</button>
    </form>
  </section>
</main>"""


def _admin_body(licenses: list[dict[str, Any]], created_code: str | None) -> str:
    """渲染授权码管理页。"""
    created_html = ""
    if created_code:
        created_html = f"""
<section class="panel panel-pad">
  <h2>新授权码</h2>
  <p class="muted">授权码只显示这一次，请保存到客户配置里。</p>
  <div class="code">{escape(created_code)}</div>
</section>"""

    return f"""
<main class="dashboard-shell stack">
  <div class="page-title">
    <div>
      <h1>授权码管理</h1>
      <p>集中管理客户端授权码、设备绑定和到期状态。</p>
    </div>
    <form method="post" action="/admin/logout"><button class="button-secondary" type="submit">退出登录</button></form>
  </div>
  {created_html}
  {_license_stats(licenses)}
  <section class="panel panel-pad stack">
    <div class="toolbar">
      <div>
        <h2>新增授权码</h2>
        <p class="muted">新授权码只会显示一次，创建后请立即保存。</p>
      </div>
    </div>
    <form class="create-form" method="post" action="/admin/licenses/create">
      <label>备注<input name="note" placeholder="客户或用途"></label>
      <label>到期日<input name="expires_at" type="date"></label>
      <div><button type="submit">新增授权码</button></div>
    </form>
  </section>
  <section class="panel panel-pad stack">
    <div class="toolbar">
      <h2>授权列表</h2>
      <span class="muted">共 {len(licenses)} 条</span>
    </div>
    {_license_table(licenses)}
  </section>
</main>"""


def _license_stats(licenses: list[dict[str, Any]]) -> str:
    """渲染授权码概览。"""
    total = len(licenses)
    active = sum(1 for item in licenses if item.get("status") == "active")
    disabled = sum(1 for item in licenses if item.get("status") == "disabled")
    bound = sum(1 for item in licenses if item.get("bound_device_id"))
    return f"""
  <section class="stat-grid" aria-label="状态总览">
    <div class="stat-card"><div class="stat-label">全部授权</div><div class="stat-value">{total}</div></div>
    <div class="stat-card"><div class="stat-label">启用中</div><div class="stat-value">{active}</div></div>
    <div class="stat-card"><div class="stat-label">已禁用</div><div class="stat-value">{disabled}</div></div>
    <div class="stat-card"><div class="stat-label">已绑定设备</div><div class="stat-value">{bound}</div></div>
  </section>"""


def _license_table(licenses: list[dict[str, Any]]) -> str:
    """渲染授权码表格。"""
    rows = "\n".join(_license_row(item) for item in licenses)
    if not rows:
        rows = '<tr><td colspan="9" class="empty-state">暂无授权码，请先新增一个授权码。</td></tr>'
    return f"""
<div class="table-shell">
  <table>
    <thead>
      <tr>
        <th>ID</th><th>完整授权码</th><th>备注</th><th>状态</th><th>到期日</th>
        <th>绑定设备</th><th>最后验证</th><th>版本</th><th>操作</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


def _license_row(item: dict[str, Any]) -> str:
    """渲染单行授权码。"""
    license_id = int(item["id"])
    expires_at = item.get("expires_at") or ""
    bound_device = item.get("bound_device_id") or "未绑定"
    last_seen = item.get("last_seen_at") or "-"
    app_version = item.get("last_app_version") or "-"
    status = item.get("status") or "active"
    status_options = _status_options(status)
    update_form_id = f"license-update-{license_id}"
    code_plain = item.get("code_plain") or "历史授权码未保存明文"
    return f"""
<tr>
  <td>{license_id}</td>
  <td>{_detail_value("完整授权码", code_plain, 20)}</td>
  <td>
    <form id="{update_form_id}" method="post" action="/admin/licenses/{license_id}/update"></form>
    <input form="{update_form_id}" name="note" value="{escape(item.get("note") or "")}">
  </td>
  <td>
    {_status_badge(status)}
    <select form="{update_form_id}" name="status">{status_options}</select>
  </td>
  <td><input form="{update_form_id}" name="expires_at" type="date" value="{escape(expires_at)}"></td>
  <td>{_detail_value("绑定设备", bound_device, 26)}</td>
  <td>{_detail_value("最后验证", last_seen, 20)}</td>
  <td>{escape(app_version)}</td>
  <td class="actions">
    <button form="{update_form_id}" type="submit">保存</button>
    <form method="post" action="/admin/licenses/{license_id}/unbind"><button class="button-secondary" type="submit">解绑</button></form>
    <form method="post" action="/admin/licenses/{license_id}/delete"><button class="danger" type="submit">删除</button></form>
  </td>
</tr>"""


def _status_badge(status: str) -> str:
    """渲染状态标签。"""
    if status == "disabled":
        return '<span class="status-badge status-disabled">禁用</span>'
    return '<span class="status-badge status-active">启用</span>'


def _detail_value(title: str, value: str, limit: int) -> str:
    """渲染可弹窗查看的长内容。"""
    safe_title = escape(json.dumps(title, ensure_ascii=False))
    safe_value = escape(json.dumps(value or "-", ensure_ascii=False))
    preview = _short_text(value or "-", limit)
    return f"""
    <div class="value-cell">
      <span class="compact-value">{escape(preview)}</span>
      <button class="link-button" type="button" onclick="openDetailModal({safe_title}, {safe_value})">查看{escape(title)}</button>
    </div>"""


def _short_text(value: str, limit: int) -> str:
    """生成长内容摘要。"""
    if len(value) <= limit:
        return value
    head = max(4, limit // 2)
    tail = max(4, limit - head - 3)
    return f"{value[:head]}...{value[-tail:]}"


def _status_options(current: str) -> str:
    """渲染状态选项。"""
    options = []
    for value, label in [("active", "启用"), ("disabled", "禁用")]:
        selected = " selected" if value == current else ""
        options.append(f'<option value="{value}"{selected}>{label}</option>')
    return "".join(options)
