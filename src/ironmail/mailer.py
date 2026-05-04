# -*- coding: utf-8 -*-

from __future__ import annotations

import smtplib
import socket
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any

_ROUTE_CACHE: dict[tuple[Any, ...], str] = {}


def get_ssl_context() -> ssl.SSLContext:
    """获取SSL上下文，优先使用certifi证书"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def choose_sender(
    senders: list[dict[str, Any]],
    sent_count: int,
    emails_per_account: int,
) -> dict[str, Any]:
    """按实际发送数量轮询选择发件邮箱"""
    if not senders:
        raise ValueError("未配置有效的发件邮箱")
    return senders[choose_sender_index(senders, sent_count, emails_per_account)]


def choose_sender_index(
    senders: list[dict[str, Any]],
    sent_count: int,
    emails_per_account: int,
) -> int:
    """返回当前轮换策略选中的发件邮箱下标。"""
    if not senders:
        raise ValueError("未配置有效的发件邮箱")
    threshold = max(1, int(emails_per_account or 1))
    return (sent_count // threshold) % len(senders)


def sender_candidates(
    senders: list[dict[str, Any]],
    sent_count: int,
    emails_per_account: int,
) -> list[dict[str, Any]]:
    """从当前轮换位置开始，给出本封邮件可尝试的发件邮箱顺序。"""
    start = choose_sender_index(senders, sent_count, emails_per_account)
    return senders[start:] + senders[:start]


def build_message(
    sender: dict[str, Any],
    recipient_email: str,
    subject: str,
    body: str,
) -> MIMEMultipart:
    """构造邮件内容"""
    msg = MIMEMultipart()
    msg["From"] = format_sender_address(sender)
    msg["To"] = recipient_email
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(body, "plain", "utf-8"))
    return msg


def format_sender_address(sender: dict[str, Any]) -> str:
    """生成发件人From头，空显示名时使用裸邮箱地址。"""
    email = str(sender["email"]).strip()
    sender_name = str(sender.get("name") or "").strip()
    if not sender_name or sender_name.lower() == email.lower():
        return email
    return formataddr((str(Header(sender_name, "utf-8")), email))


def send_email(
    smtp_config: dict[str, Any],
    sender: dict[str, Any],
    recipient_email: str,
    subject: str,
    body: str,
) -> bool:
    """发送单封邮件"""
    msg = build_message(sender, recipient_email, subject, body)
    with open_smtp_connection(smtp_config) as server:
        server.login(sender["email"], sender["password"])
        server.sendmail(sender["email"], recipient_email, msg.as_string())
    return True


def test_smtp_login(smtp_config: dict[str, Any], sender: dict[str, Any]) -> bool:
    """测试SMTP账号是否可以登录"""
    with open_smtp_connection(smtp_config) as server:
        server.login(sender["email"], sender["password"])
    return True


def open_smtp_connection(smtp_config: dict[str, Any]):
    """创建SMTP连接，支持SSL和STARTTLS"""
    context = get_ssl_context()
    host = smtp_config["host"]
    port = int(smtp_config["port"])
    proxy = smtp_config.get("proxy")
    use_ssl = smtp_config.get("use_ssl", True)
    timeout = _connect_timeout(proxy)
    mode = _proxy_mode(proxy)
    if mode == "proxy":
        server, proxy_route = _open_proxy_smtp(host, port, use_ssl, proxy, context, timeout)
        _cache_route(host, port, use_ssl, proxy, proxy_route)
        return server
    cached_route = _cached_route(host, port, use_ssl, proxy)
    if mode == "auto" and cached_route and cached_route != "direct":
        server, _ = _open_proxy_smtp(
            host,
            port,
            use_ssl,
            _proxy_from_route(proxy, cached_route),
            context,
            timeout,
        )
        return server
    try:
        server = _open_direct_smtp(host, port, use_ssl, context, timeout)
        _cache_route(host, port, use_ssl, proxy, "direct")
        return server
    except OSError:
        if mode != "auto" or not _is_http_proxy_available(proxy):
            raise
        server, proxy_route = _open_proxy_smtp(host, port, use_ssl, proxy, context, timeout)
        _cache_route(host, port, use_ssl, proxy, proxy_route)
        return server


def _open_direct_smtp(
    host: str,
    port: int,
    use_ssl: bool,
    context: ssl.SSLContext,
    timeout: int,
):
    """使用当前网络直连SMTP"""
    if use_ssl:
        return smtplib.SMTP_SSL(host, port, context=context, timeout=timeout)
    server = smtplib.SMTP(host, port, timeout=timeout)
    server.starttls(context=context)
    return server


def _open_proxy_smtp(
    host: str,
    port: int,
    use_ssl: bool,
    proxy: dict[str, Any],
    context: ssl.SSLContext,
    timeout: int,
):
    """使用HTTP CONNECT代理连接SMTP"""
    last_error: Exception | None = None
    for candidate in _proxy_candidates(proxy):
        try:
            if use_ssl:
                server = _HttpProxySMTPSSL(host, port, proxy=candidate, context=context, timeout=timeout)
            else:
                server = _HttpProxySMTP(host, port, proxy=candidate, timeout=timeout)
                server.starttls(context=context)
            return server, _proxy_route(candidate)
        except OSError as error:
            last_error = error
    raise OSError(f"所有SMTP代理端口都连接失败: {last_error}")


def _proxy_mode(proxy: dict[str, Any] | None) -> str:
    """读取SMTP出网模式"""
    if not proxy:
        return "direct"
    mode = str(proxy.get("mode") or "").lower()
    if mode:
        return mode
    return "proxy" if proxy.get("enabled") else "direct"


def _connect_timeout(proxy: dict[str, Any] | None) -> int:
    """读取SMTP连接超时秒数"""
    if not proxy:
        return 8
    return int(proxy.get("connect_timeout_seconds") or 8)


def _is_http_proxy_available(proxy: dict[str, Any] | None) -> bool:
    """判断是否配置了可尝试的HTTP代理"""
    mode = _proxy_mode(proxy)
    return bool(proxy and mode in {"auto", "proxy"} and proxy.get("type", "http") == "http")


def _proxy_candidates(proxy: dict[str, Any]) -> list[dict[str, Any]]:
    """生成本机代理候选端口"""
    ports = proxy.get("candidate_ports") or [proxy.get("port")]
    candidates = []
    seen = set()
    for port in ports:
        parsed = int(port)
        if parsed in seen:
            continue
        seen.add(parsed)
        candidate = dict(proxy)
        candidate["port"] = parsed
        candidate["candidate_ports"] = [parsed]
        candidates.append(candidate)
    return candidates


def _proxy_route(proxy: dict[str, Any]) -> str:
    """把命中的代理路线编码成缓存值"""
    return f"proxy://{proxy['host']}:{int(proxy['port'])}"


def _proxy_from_route(proxy: dict[str, Any], route: str) -> dict[str, Any]:
    """从缓存路线恢复具体代理配置"""
    if not route.startswith("proxy://"):
        return proxy
    address = route.removeprefix("proxy://")
    host, port = address.rsplit(":", 1)
    selected = dict(proxy)
    selected["host"] = host
    selected["port"] = int(port)
    selected["candidate_ports"] = [int(port)]
    return selected


def _cache_key(host: str, port: int, use_ssl: bool, proxy: dict[str, Any] | None) -> tuple[Any, ...]:
    """生成SMTP出网路线缓存键"""
    proxy = proxy or {}
    return (
        host,
        port,
        use_ssl,
        proxy.get("type", "http"),
        proxy.get("host"),
        int(proxy.get("port") or 0),
        tuple(int(port) for port in proxy.get("candidate_ports", []) or []),
    )


def _cached_route(host: str, port: int, use_ssl: bool, proxy: dict[str, Any] | None) -> str | None:
    """读取已探测成功的出网路线"""
    return _ROUTE_CACHE.get(_cache_key(host, port, use_ssl, proxy))


def _cache_route(
    host: str,
    port: int,
    use_ssl: bool,
    proxy: dict[str, Any] | None,
    route: str,
) -> None:
    """缓存本次进程可用的SMTP出网路线"""
    _ROUTE_CACHE[_cache_key(host, port, use_ssl, proxy)] = route


def _open_http_proxy_socket(host: str, port: int, proxy: dict[str, Any], timeout: int):
    """通过HTTP CONNECT代理创建到SMTP服务器的socket"""
    proxy_host = proxy["host"]
    proxy_port = int(proxy["port"])
    raw = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    request = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode("ascii")
    raw.sendall(request)
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = raw.recv(4096)
        if not chunk:
            break
        response += chunk
    first_line = response.splitlines()[0].decode("latin1", errors="replace") if response else ""
    if " 200 " not in first_line:
        raw.close()
        raise OSError(f"SMTP代理连接失败: {first_line or '无响应'}")
    return raw


class _HttpProxySMTPSSL(smtplib.SMTP_SSL):
    """支持HTTP CONNECT代理的SMTP_SSL客户端"""

    def __init__(self, *args, proxy: dict[str, Any], **kwargs):
        self._proxy = proxy
        super().__init__(*args, **kwargs)

    def _get_socket(self, host, port, timeout):
        raw = _open_http_proxy_socket(host, port, self._proxy, timeout)
        return self.context.wrap_socket(raw, server_hostname=host)


class _HttpProxySMTP(smtplib.SMTP):
    """支持HTTP CONNECT代理的SMTP客户端"""

    def __init__(self, *args, proxy: dict[str, Any], **kwargs):
        self._proxy = proxy
        super().__init__(*args, **kwargs)

    def _get_socket(self, host, port, timeout):
        return _open_http_proxy_socket(host, port, self._proxy, timeout)
