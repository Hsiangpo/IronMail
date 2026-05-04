# -*- coding: utf-8 -*-
from __future__ import annotations

"""授权服务配置。"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    admin_username: str
    admin_password: str
    session_secret: str
    data_dir: Path
    database_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("IRONMAIL_DATA_DIR", "./data")).resolve()
        database_path = Path(
            os.getenv("IRONMAIL_DATABASE_PATH", str(data_dir / "licenses.sqlite3"))
        ).resolve()
        return cls(
            admin_username=os.getenv("IRONMAIL_ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("IRONMAIL_ADMIN_PASSWORD", "admin"),
            session_secret=os.getenv("IRONMAIL_SESSION_SECRET", "change-me"),
            data_dir=data_dir,
            database_path=database_path,
        )
