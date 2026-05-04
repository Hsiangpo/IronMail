# -*- coding: utf-8 -*-

import importlib
import sys

from fastapi.testclient import TestClient


def load_app(tmp_path, monkeypatch):
    monkeypatch.setenv("IRONMAIL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IRONMAIL_DATABASE_PATH", str(tmp_path / "licenses.sqlite3"))
    monkeypatch.setenv("IRONMAIL_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("IRONMAIL_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("IRONMAIL_SESSION_SECRET", "test-secret")
    sys.modules.pop("ironmail_license.app", None)
    return importlib.import_module("ironmail_license.app")


def test_verify_api_accepts_created_license(tmp_path, monkeypatch):
    app_module = load_app(tmp_path, monkeypatch)
    with app_module.db.connect(app_module.settings.database_path) as conn:
        code = app_module.db.create_license(conn, "接口测试", None)

    client = TestClient(app_module.app)
    response = client.post(
        "/api/v1/licenses/verify",
        json={"code": code, "device_id": "device-a", "app_version": "1.0.0"},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_admin_requires_login_and_can_create_license(tmp_path, monkeypatch):
    app_module = load_app(tmp_path, monkeypatch)
    client = TestClient(app_module.app)

    blocked = client.get("/admin/licenses", follow_redirects=False)
    assert blocked.status_code == 302
    assert blocked.headers["location"] == "/admin/login"

    login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "secret"},
        follow_redirects=False,
    )
    assert login.status_code == 302

    created = client.post(
        "/admin/licenses/create",
        data={"note": "后台测试", "expires_at": ""},
        follow_redirects=False,
    )
    assert created.status_code == 302
    assert "created=IM-" in created.headers["location"]


def test_admin_license_page_uses_polished_layout(tmp_path, monkeypatch):
    app_module = load_app(tmp_path, monkeypatch)
    with app_module.db.connect(app_module.settings.database_path) as conn:
        code = app_module.db.create_license(conn, "页面测试", None)
    client = TestClient(app_module.app)
    client.post("/admin/login", data={"username": "admin", "password": "secret"})

    response = client.get("/admin/licenses")

    assert response.status_code == 200
    html = response.text
    assert "dashboard-shell" in html
    assert "stat-grid" in html
    assert "table-shell" in html
    assert "状态总览" in html
    assert "页面测试" in html
    assert code in html
    assert "完整授权码" in html
