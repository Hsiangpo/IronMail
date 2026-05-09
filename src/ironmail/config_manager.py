# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


DEFAULT_SMTP = {
    "host": "smtp.gmail.com",
    "port": 465,
    "use_ssl": True,
}

PROVIDER_SMTP_DEFAULTS = {
    "gmail.com": DEFAULT_SMTP,
    "googlemail.com": DEFAULT_SMTP,
    "gmx.com": {"host": "mail.gmx.com", "port": 465, "use_ssl": True},
    "gmx.us": {"host": "mail.gmx.com", "port": 465, "use_ssl": True},
}

DEFAULT_SMTP_PROXY = {
    "mode": "auto",
    "type": "http",
    "host": "127.0.0.1",
    "port": 7897,
    "candidate_ports": [7897, 7890, 7891, 1080, 1087, 10809],
    "connect_timeout_seconds": 8,
}

EMAIL_ADDRESS_PATTERN = (
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}"
)
EMAIL_RE = re.compile(EMAIL_ADDRESS_PATTERN)
BATCH_SEPARATOR_PATTERN = r"(?:-{2,}|[—–]+|[:：,，;；|]|\t+|\s+)"
BATCH_SENDER_PAIR_RE = re.compile(
    rf"(?P<email>{EMAIL_ADDRESS_PATTERN})\s*"
    rf"{BATCH_SEPARATOR_PATTERN}\s*"
    rf"(?P<password>(?!{EMAIL_ADDRESS_PATTERN})[^\s,，;；|]+)"
)
BATCH_SINGLE_LINE_RE = re.compile(
    rf"^\s*.*?(?P<email>{EMAIL_ADDRESS_PATTERN})\s*"
    rf"{BATCH_SEPARATOR_PATTERN}\s*"
    rf"(?P<password>.+?)\s*$"
)


def load_config(config_path: str | Path) -> dict[str, Any]:
    """读取配置文件，并补齐缺失的基础结构"""
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    return normalize_config(config)


def save_config(config_path: str | Path, config: dict[str, Any]) -> None:
    """保存配置文件，统一使用UTF-8编码"""
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_config = normalize_config(config)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(clean_config, file, allow_unicode=True, sort_keys=False)


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """补齐老配置缺失字段，兼容旧版config.yaml"""
    config.setdefault("license", {})
    config.setdefault("smtp", DEFAULT_SMTP.copy())
    config.setdefault("smtp_proxy", DEFAULT_SMTP_PROXY.copy())
    config.setdefault("senders", [])
    config.setdefault("settings", {})
    config["smtp"] = normalize_smtp(config.get("smtp"))
    config["smtp_proxy"] = normalize_smtp_proxy(config.get("smtp_proxy"))
    config["senders"] = [
        normalize_sender(sender)
        for sender in config.get("senders", [])
        if isinstance(sender, dict) and sender.get("email")
    ]
    settings = config["settings"]
    settings.setdefault("delay_seconds", 12)
    settings.setdefault("max_retries", 3)
    settings.setdefault("emails_per_account", 1)
    settings.setdefault("log_file", "logs/send_log.txt")
    return config


def normalize_smtp(smtp: dict[str, Any] | None) -> dict[str, Any]:
    """标准化SMTP配置"""
    merged = DEFAULT_SMTP.copy()
    if isinstance(smtp, dict):
        merged.update({key: value for key, value in smtp.items() if value not in (None, "")})
    merged["port"] = int(merged.get("port") or DEFAULT_SMTP["port"])
    merged["use_ssl"] = bool(merged.get("use_ssl"))
    return merged


def smtp_defaults_for_email(email: str) -> dict[str, Any]:
    """按邮箱域名返回常见SMTP默认值。"""
    domain = email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""
    return normalize_smtp(PROVIDER_SMTP_DEFAULTS.get(domain, DEFAULT_SMTP))


def parse_sender_batch_text(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """Parse pasted sender accounts into email/password pairs.

    Supports common copy/paste forms such as:
    email----password, email password, email,password, email:password.
    """
    records: list[dict[str, str]] = []
    errors: list[str] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        raw_line = line.strip()
        if not raw_line:
            continue
        email_matches = list(EMAIL_RE.finditer(raw_line))
        if not email_matches:
            continue

        parsed_email_spans: list[tuple[int, int]] = []
        if len(email_matches) == 1:
            match = BATCH_SINGLE_LINE_RE.match(raw_line)
            if match:
                password = clean_batch_password(match.group("password"))
                if password and not EMAIL_RE.fullmatch(password):
                    records.append({"email": match.group("email").strip(), "password": password})
                    parsed_email_spans.append(match.span("email"))
            if parsed_email_spans:
                continue

        for match in BATCH_SENDER_PAIR_RE.finditer(raw_line):
            password = clean_batch_password(match.group("password"))
            if not password or EMAIL_RE.fullmatch(password):
                continue
            records.append({"email": match.group("email").strip(), "password": password})
            parsed_email_spans.append(match.span("email"))

        for email_match in email_matches:
            span = email_match.span()
            if span not in parsed_email_spans:
                errors.append(f"第 {line_number} 行未识别到密码: {email_match.group(0)}")

    if text.strip() and not records and not errors:
        errors.append("未识别到可导入的邮箱和密码，请检查粘贴格式。")
    return records, errors


def clean_batch_password(password: str) -> str:
    """Clean one password value without logging or exposing it."""
    cleaned = password.strip().strip("'\"").rstrip(".,;；，")
    cleaned = re.sub(r"^(?:密码|口令|授权码|应用密码|SMTP\s*密码|password)\s*[:：=]\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip().strip("'\"").rstrip(".,;；，")


def normalize_smtp_proxy(proxy: dict[str, Any] | None) -> dict[str, Any]:
    """标准化SMTP代理配置"""
    merged = DEFAULT_SMTP_PROXY.copy()
    if isinstance(proxy, dict):
        merged.update({key: value for key, value in proxy.items() if value not in (None, "")})
    if "enabled" in merged and "mode" not in (proxy or {}):
        merged["mode"] = "proxy" if merged.get("enabled") else "direct"
    merged["mode"] = str(merged.get("mode") or "auto").lower()
    merged["type"] = str(merged.get("type") or "http").lower()
    merged["port"] = int(merged.get("port") or DEFAULT_SMTP_PROXY["port"])
    merged["candidate_ports"] = normalize_candidate_ports(
        merged.get("candidate_ports"),
        merged["port"],
    )
    merged["connect_timeout_seconds"] = int(
        merged.get("connect_timeout_seconds") or DEFAULT_SMTP_PROXY["connect_timeout_seconds"]
    )
    merged.pop("enabled", None)
    return merged


def normalize_candidate_ports(value: Any, primary_port: int) -> list[int]:
    """标准化代理候选端口列表"""
    if value in (None, ""):
        ports: list[Any] = []
    elif isinstance(value, list):
        ports = value
    else:
        ports = [value]
    normalized = [primary_port]
    for port in ports:
        parsed = int(port)
        if parsed not in normalized:
            normalized.append(parsed)
    return normalized


def normalize_sender(sender: dict[str, Any]) -> dict[str, Any]:
    """标准化单个发件邮箱配置"""
    normalized = {
        "email": str(sender.get("email", "")).strip(),
        "password": str(sender.get("password", "") or ""),
        "name": str(sender.get("name", "") or ""),
    }
    smtp = sender.get("smtp")
    if isinstance(smtp, dict) and smtp.get("host"):
        normalized["smtp"] = normalize_smtp(smtp)
    return normalized


def build_sender(
    email: str,
    password: str,
    name: str = "",
    smtp_host: str = "",
    smtp_port: int | str | None = None,
    smtp_use_ssl: bool = True,
) -> dict[str, Any]:
    """构造发件邮箱配置，留空SMTP时默认走全局Gmail配置"""
    sender: dict[str, Any] = {
        "email": email.strip(),
        "password": password,
        "name": name.strip(),
    }
    if smtp_host.strip():
        sender["smtp"] = normalize_smtp(
            {"host": smtp_host.strip(), "port": smtp_port or 465, "use_ssl": smtp_use_ssl}
        )
    return normalize_sender(sender)


def active_senders(config: dict[str, Any]) -> list[dict[str, Any]]:
    """返回可以参与轮询的发件邮箱"""
    return [
        sender for sender in normalize_config(config).get("senders", [])
        if sender.get("email") and sender.get("password")
    ]


def resolve_sender_smtp(config: dict[str, Any], sender: dict[str, Any]) -> dict[str, Any]:
    """优先使用邮箱自己的SMTP配置，否则使用全局默认SMTP"""
    if isinstance(sender.get("smtp"), dict) and sender["smtp"].get("host"):
        return normalize_smtp(sender["smtp"])
    return normalize_smtp(config.get("smtp"))


def add_sender(config: dict[str, Any], sender: dict[str, Any]) -> None:
    """新增发件邮箱"""
    email = sender.get("email", "").strip()
    if not email:
        raise ValueError("邮箱地址不能为空")
    if find_sender_index(config, email) is not None:
        raise ValueError(f"发件邮箱已存在: {email}")
    config.setdefault("senders", []).append(normalize_sender(sender))


def update_sender(config: dict[str, Any], email: str, updates: dict[str, Any]) -> None:
    """修改发件邮箱"""
    index = find_sender_index(config, email)
    if index is None:
        raise ValueError(f"未找到发件邮箱: {email}")
    current = dict(config["senders"][index])
    current.update({key: value for key, value in updates.items() if value is not None})
    config["senders"][index] = normalize_sender(current)


def delete_sender(config: dict[str, Any], email: str) -> None:
    """删除发件邮箱"""
    index = find_sender_index(config, email)
    if index is None:
        raise ValueError(f"未找到发件邮箱: {email}")
    del config["senders"][index]


def find_sender_index(config: dict[str, Any], email: str) -> int | None:
    """按邮箱地址查找配置下标"""
    target = email.strip().lower()
    for index, sender in enumerate(config.get("senders", [])):
        if str(sender.get("email", "")).strip().lower() == target:
            return index
    return None


def mask_sender(sender: dict[str, Any]) -> dict[str, Any]:
    """隐藏发件邮箱密码，供终端展示使用"""
    masked = dict(sender)
    password = str(masked.get("password", "") or "")
    if len(password) <= 8:
        masked["password"] = "*" * len(password)
    else:
        masked["password"] = f"{password[:4]}********{password[-4:]}"
    return masked
