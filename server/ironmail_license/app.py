# -*- coding: utf-8 -*-
from __future__ import annotations

"""IronMail授权服务入口。"""

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
    body {{ margin: 0; font-family: Arial, sans-serif; background: #f5f7fb; color: #172033; }}
    header {{ background: #172033; color: #fff; padding: 16px 24px; display: flex; justify-content: space-between; }}
    main {{ max-width: 1120px; margin: 24px auto; padding: 0 16px; }}
    section, table {{ background: #fff; border: 1px solid #d9e1ee; border-radius: 8px; }}
    section {{ padding: 18px; margin-bottom: 18px; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #e8edf5; text-align: left; vertical-align: top; }}
    th {{ background: #eef3fa; }}
    input, select {{ padding: 8px; border: 1px solid #c8d2e1; border-radius: 6px; min-width: 160px; }}
    button {{ padding: 8px 12px; border: 0; border-radius: 6px; background: #1f6feb; color: #fff; cursor: pointer; }}
    .danger {{ background: #c62828; }}
    .muted {{ color: #627084; font-size: 13px; }}
    .code {{ background: #eaf7ed; border: 1px solid #abd7b5; padding: 12px; border-radius: 6px; font-weight: bold; }}
    .error {{ background: #ffecec; color: #9f1d1d; padding: 10px; border-radius: 6px; }}
    .actions form {{ display: inline-block; margin: 2px; }}
  </style>
</head>
<body>
  <header><strong>IronMail 授权管理</strong><span>tmpmail.oldiron.us</span></header>
  <main>{body}</main>
</body>
</html>"""


def _login_form(error: str) -> str:
    """渲染登录表单。"""
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return f"""
<section>
  <h1>管理员登录</h1>
  {error_html}
  <form method="post" action="/admin/login">
    <p><label>账号<br><input name="username" autocomplete="username"></label></p>
    <p><label>密码<br><input name="password" type="password" autocomplete="current-password"></label></p>
    <button type="submit">登录</button>
  </form>
</section>"""


def _admin_body(licenses: list[dict[str, Any]], created_code: str | None) -> str:
    """渲染授权码管理页。"""
    created_html = ""
    if created_code:
        created_html = f"""
<section>
  <h2>新授权码</h2>
  <p class="muted">授权码只显示这一次，请保存到客户配置里。</p>
  <div class="code">{escape(created_code)}</div>
</section>"""

    return f"""
{created_html}
<section>
  <form method="post" action="/admin/logout" style="float:right"><button type="submit">退出登录</button></form>
  <h1>授权码管理</h1>
  <form method="post" action="/admin/licenses/create">
    <label>备注 <input name="note" placeholder="客户或用途"></label>
    <label>到期日 <input name="expires_at" type="date"></label>
    <button type="submit">新增授权码</button>
  </form>
</section>
{_license_table(licenses)}"""


def _license_table(licenses: list[dict[str, Any]]) -> str:
    """渲染授权码表格。"""
    rows = "\n".join(_license_row(item) for item in licenses)
    if not rows:
        rows = '<tr><td colspan="9" class="muted">暂无授权码</td></tr>'
    return f"""
<table>
  <thead>
    <tr>
      <th>ID</th><th>授权码前缀</th><th>备注</th><th>状态</th><th>到期日</th>
      <th>绑定设备</th><th>最后验证</th><th>版本</th><th>操作</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""


def _license_row(item: dict[str, Any]) -> str:
    """渲染单行授权码。"""
    license_id = int(item["id"])
    expires_at = item.get("expires_at") or ""
    bound_device = item.get("bound_device_id") or "未绑定"
    last_seen = item.get("last_seen_at") or "-"
    app_version = item.get("last_app_version") or "-"
    status = item.get("status") or "active"
    status_options = _status_options(status)
    return f"""
<tr>
  <td>{license_id}</td>
  <td>{escape(item.get("code_prefix") or "")}</td>
  <td><form method="post" action="/admin/licenses/{license_id}/update">
    <input name="note" value="{escape(item.get("note") or "")}">
  </td>
  <td><select name="status">{status_options}</select></td>
  <td><input name="expires_at" type="date" value="{escape(expires_at)}"></td>
  <td><span class="muted">{escape(bound_device[:18])}</span></td>
  <td>{escape(last_seen)}</td>
  <td>{escape(app_version)}</td>
  <td class="actions">
      <button type="submit">保存</button>
    </form>
    <form method="post" action="/admin/licenses/{license_id}/unbind"><button type="submit">解绑</button></form>
    <form method="post" action="/admin/licenses/{license_id}/delete"><button class="danger" type="submit">删除</button></form>
  </td>
</tr>"""


def _status_options(current: str) -> str:
    """渲染状态选项。"""
    options = []
    for value, label in [("active", "启用"), ("disabled", "禁用")]:
        selected = " selected" if value == current else ""
        options.append(f'<option value="{value}"{selected}>{label}</option>')
    return "".join(options)
