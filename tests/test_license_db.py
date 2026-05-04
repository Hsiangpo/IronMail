# -*- coding: utf-8 -*-

from datetime import date, timedelta

from ironmail_license import db


def test_license_first_bind_and_same_device_pass(tmp_path):
    database_path = tmp_path / "licenses.sqlite3"
    db.init_db(database_path)

    with db.connect(database_path) as conn:
        code = db.create_license(conn, "测试客户", None)
        first = db.verify_license(conn, code, "device-a", "1.0.0")
        second = db.verify_license(conn, code, "device-a", "1.0.1")

    assert first["valid"] is True
    assert second["valid"] is True


def test_license_rejects_other_device_after_binding(tmp_path):
    database_path = tmp_path / "licenses.sqlite3"
    db.init_db(database_path)

    with db.connect(database_path) as conn:
        code = db.create_license(conn, "测试客户", None)
        db.verify_license(conn, code, "device-a", "1.0.0")
        result = db.verify_license(conn, code, "device-b", "1.0.0")

    assert result == {
        "valid": False,
        "reason": "device_mismatch",
        "expires_at": None,
        "device_bound": False,
    }


def test_license_unbind_allows_new_device(tmp_path):
    database_path = tmp_path / "licenses.sqlite3"
    db.init_db(database_path)

    with db.connect(database_path) as conn:
        code = db.create_license(conn, "测试客户", None)
        db.verify_license(conn, code, "device-a", "1.0.0")
        license_id = db.list_licenses(conn)[0]["id"]
        db.unbind_license(conn, license_id)
        result = db.verify_license(conn, code, "device-b", "1.0.0")

    assert result["valid"] is True


def test_license_rejects_disabled_and_expired(tmp_path):
    database_path = tmp_path / "licenses.sqlite3"
    db.init_db(database_path)
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    with db.connect(database_path) as conn:
        disabled_code = db.create_license(conn, "禁用客户", None)
        expired_code = db.create_license(conn, "过期客户", yesterday)
        disabled_id = db.list_licenses(conn)[1]["id"]
        db.update_license(conn, disabled_id, "禁用客户", "disabled", None)
        disabled = db.verify_license(conn, disabled_code, "device-a", "1.0.0")
        expired = db.verify_license(conn, expired_code, "device-a", "1.0.0")

    assert disabled["reason"] == "disabled"
    assert expired["reason"] == "expired"


def test_license_code_is_not_stored_in_plaintext(tmp_path):
    database_path = tmp_path / "licenses.sqlite3"
    db.init_db(database_path)

    with db.connect(database_path) as conn:
        code = db.create_license(conn, "测试客户", None)
        row = conn.execute("SELECT code_hash, code_prefix FROM licenses").fetchone()

    assert row["code_hash"] != code
    assert row["code_prefix"] == code[:10]
