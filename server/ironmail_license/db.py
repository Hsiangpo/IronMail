# -*- coding: utf-8 -*-
from __future__ import annotations

"""SQLite授权码仓储。"""

import hashlib
import secrets
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def connect(database_path: Path) -> sqlite3.Connection:
    """创建SQLite连接。"""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(database_path: Path) -> None:
    """初始化数据库表。"""
    with connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS licenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_hash TEXT NOT NULL UNIQUE,
                code_prefix TEXT NOT NULL,
                code_plain TEXT,
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                expires_at TEXT,
                bound_device_id TEXT,
                bound_at TEXT,
                last_seen_at TEXT,
                last_app_version TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        ensure_column(conn, "licenses", "code_plain", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status)")


def now_iso() -> str:
    """返回UTC时间字符串。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_code(code: str) -> str:
    """哈希授权码，数据库不保存明文。"""
    return hashlib.sha256(f"ironmail-license-v1|{code}".encode("utf-8")).hexdigest()


def generate_code() -> str:
    """生成新的授权码。"""
    token = secrets.token_urlsafe(24).replace("-", "").replace("_", "")
    return f"IM-{token[:6]}-{token[6:12]}-{token[12:18]}-{token[18:24]}".upper()


def normalize_expires_at(value: str | None) -> str | None:
    """规范化过期日期，空值表示永久。"""
    if not value:
        return None
    parsed = date.fromisoformat(value)
    return parsed.isoformat()


def list_licenses(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """列出授权码。"""
    rows = conn.execute(
        """
        SELECT * FROM licenses
        ORDER BY id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def create_license(conn: sqlite3.Connection, note: str, expires_at: str | None) -> str:
    """创建授权码并返回明文授权码。"""
    code = generate_code()
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO licenses (
            code_hash, code_prefix, code_plain, note, status, expires_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            hash_code(code),
            code[:10],
            code,
            note.strip(),
            normalize_expires_at(expires_at),
            timestamp,
            timestamp,
        ),
    )
    return code


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """确保旧数据库存在新字段。"""
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def update_license(
    conn: sqlite3.Connection,
    license_id: int,
    note: str,
    status: str,
    expires_at: str | None,
) -> None:
    """更新授权码信息。"""
    if status not in {"active", "disabled"}:
        raise ValueError("授权码状态不正确")

    conn.execute(
        """
        UPDATE licenses
        SET note = ?, status = ?, expires_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (note.strip(), status, normalize_expires_at(expires_at), now_iso(), license_id),
    )


def delete_license(conn: sqlite3.Connection, license_id: int) -> None:
    """删除授权码。"""
    conn.execute("DELETE FROM licenses WHERE id = ?", (license_id,))


def unbind_license(conn: sqlite3.Connection, license_id: int) -> None:
    """解绑授权码设备。"""
    conn.execute(
        """
        UPDATE licenses
        SET bound_device_id = NULL, bound_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (now_iso(), license_id),
    )


def verify_license(
    conn: sqlite3.Connection,
    code: str,
    device_id: str,
    app_version: str,
) -> dict[str, Any]:
    """验证授权码，并在首次使用时绑定设备。"""
    if not code.strip():
        return _invalid("missing_code")

    row = conn.execute(
        "SELECT * FROM licenses WHERE code_hash = ?",
        (hash_code(code.strip()),),
    ).fetchone()
    if row is None:
        return _invalid("not_found")

    license_row = dict(row)
    if license_row["status"] != "active":
        return _invalid("disabled", license_row.get("expires_at"))

    if _is_expired(license_row.get("expires_at")):
        return _invalid("expired", license_row.get("expires_at"))

    bound_device_id = license_row.get("bound_device_id")
    if bound_device_id and bound_device_id != device_id:
        return _invalid("device_mismatch", license_row.get("expires_at"))

    timestamp = now_iso()
    if not bound_device_id:
        conn.execute(
            """
            UPDATE licenses
            SET bound_device_id = ?, bound_at = ?, last_seen_at = ?,
                last_app_version = ?, updated_at = ?
            WHERE id = ?
            """,
            (device_id, timestamp, timestamp, app_version, timestamp, license_row["id"]),
        )
    else:
        conn.execute(
            """
            UPDATE licenses
            SET last_seen_at = ?, last_app_version = ?, updated_at = ?
            WHERE id = ?
            """,
            (timestamp, app_version, timestamp, license_row["id"]),
        )

    return {
        "valid": True,
        "reason": "ok",
        "expires_at": license_row.get("expires_at"),
        "device_bound": True,
    }


def _invalid(reason: str, expires_at: str | None = None) -> dict[str, Any]:
    """生成失败响应。"""
    return {
        "valid": False,
        "reason": reason,
        "expires_at": expires_at,
        "device_bound": False,
    }


def _is_expired(expires_at: str | None) -> bool:
    """判断授权码是否过期。"""
    if not expires_at:
        return False
    return date.fromisoformat(expires_at) < date.today()
