# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def progress_file_for(app_dir: Path, data_path: Path, template_path: Path | None) -> Path:
    """根据名单表和模板生成断点文件路径。"""
    progress_dir = app_dir / "logs" / "progress"
    source = {
        "data": _file_identity(data_path),
        "template": _file_identity(template_path) if template_path else "table_fields",
    }
    digest = hashlib.sha256(
        json.dumps(source, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return progress_dir / f"{data_path.stem}-{digest}.json"


def load_progress(app_dir: Path, data_path: Path, template_path: Path | None) -> dict[str, Any]:
    """读取断点文件，不存在时创建内存状态。"""
    progress_path = progress_file_for(app_dir, data_path, template_path)
    if progress_path.exists():
        with progress_path.open("r", encoding="utf-8") as file:
            state = json.load(file)
        state["path"] = str(progress_path)
        return state
    return {
        "path": str(progress_path),
        "data_file": str(data_path),
        "template_file": str(template_path) if template_path else None,
        "created_at": _now(),
        "updated_at": _now(),
        "completed_rows": {},
    }


def save_progress(state: dict[str, Any]) -> None:
    """保存断点文件。"""
    state["updated_at"] = _now()
    path = Path(state["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)


def reset_progress(state: dict[str, Any]) -> None:
    """清空当前发送记录。"""
    state["completed_rows"] = {}
    save_progress(state)


def mark_row_completed(state: dict[str, Any], row_key: str, status: str) -> None:
    """标记某一行为已处理。"""
    state.setdefault("completed_rows", {})[row_key] = {
        "status": status,
        "completed_at": _now(),
    }
    save_progress(state)


def is_row_completed(state: dict[str, Any], row_key: str) -> bool:
    """判断某一行是否已经成功或跳过。"""
    return row_key in state.get("completed_rows", {})


def row_key(index: int, recipient_email: str) -> str:
    """生成行断点键，index是DataFrame下标，Excel行号要加2。"""
    return f"{index + 2}|{recipient_email.strip().lower()}"


def progress_summary(state: dict[str, Any], total_rows: int) -> tuple[int, int]:
    """返回已完成数量和总行数。"""
    return len(state.get("completed_rows", {})), total_rows


def _file_identity(path: Path | None) -> dict[str, Any] | str:
    """生成文件身份，文件变更后自动使用新的断点。"""
    if path is None:
        return "none"
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _now() -> str:
    """生成本地时间字符串。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
