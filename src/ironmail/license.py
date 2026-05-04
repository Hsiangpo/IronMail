# -*- coding: utf-8 -*-
from __future__ import annotations

"""授权码联网验证。"""

import hashlib
import json
import platform
import ssl
import urllib.error
import urllib.request
import uuid
from typing import Any


APP_VERSION = "1.0.0"


REASON_MESSAGES = {
    "missing_code": "授权码不能为空。",
    "not_found": "授权码不存在。",
    "disabled": "授权码已被禁用。",
    "expired": "授权码已过期。",
    "device_mismatch": "授权码已绑定到其他电脑，请联系管理员解绑。",
    "server_error": "授权服务器异常。",
}


def get_device_id() -> str:
    """生成当前电脑的稳定设备指纹。"""
    raw_id = _get_windows_machine_guid() or _get_fallback_machine_id()
    return hashlib.sha256(f"ironmail-device-v1|{raw_id}".encode("utf-8")).hexdigest()


def _get_windows_machine_guid() -> str:
    """读取Windows机器ID，非Windows环境返回空字符串。"""
    if platform.system().lower() != "windows":
        return ""

    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(machine_guid).strip()
    except Exception:
        return ""


def _get_fallback_machine_id() -> str:
    """非Windows或读取失败时使用基础硬件信息生成指纹。"""
    return "|".join(
        [
            platform.node(),
            platform.system(),
            platform.machine(),
            str(uuid.getnode()),
        ]
    )


def verify_license(config: dict[str, Any]) -> bool:
    """向授权服务器验证授权码。"""
    license_config = config.get("license") or {}
    server_url = str(license_config.get("server_url") or "").strip().rstrip("/")
    code = str(license_config.get("code") or "").strip()
    timeout = int(license_config.get("timeout_seconds") or 10)

    if not server_url:
        print("错误: 未配置授权服务器地址，请检查 config/config.yaml 的 license.server_url")
        return False

    if not code:
        code = input("请输入授权码: ").strip()

    if not code:
        print("错误: 授权码不能为空。")
        return False

    try:
        result = _post_verify_request(server_url, code, timeout, config.get("smtp_proxy"))
    except urllib.error.URLError as exc:
        print(f"错误: 无法连接授权服务器，已禁止发送。详情: {exc.reason}")
        return False
    except Exception as exc:
        print(f"错误: 授权验证失败，已禁止发送。详情: {exc}")
        return False

    if result.get("valid") is True:
        expires_at = result.get("expires_at") or "永久"
        print(f"授权验证通过，有效期: {expires_at}")
        return True

    reason = str(result.get("reason") or "server_error")
    message = REASON_MESSAGES.get(reason, "授权验证未通过。")
    print(f"错误: {message}")
    return False


def _post_verify_request(
    server_url: str,
    code: str,
    timeout: int,
    proxy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """发送授权验证请求。"""
    payload = {
        "code": code,
        "device_id": get_device_id(),
        "app_version": APP_VERSION,
    }
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None

    for proxy_route in _license_proxy_routes(proxy):
        try:
            return _open_verify_request(server_url, body, timeout, proxy_route)
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as error:
            last_error = error

    if last_error:
        raise last_error
    raise urllib.error.URLError("没有可用的授权验证出网路线")


def _open_verify_request(
    server_url: str,
    body: bytes,
    timeout: int,
    proxies: dict[str, str] | None,
) -> dict[str, Any]:
    """按指定出网路线发送授权验证请求。"""
    request = urllib.request.Request(
        f"{server_url}/api/v1/licenses/verify",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"IronMail/{APP_VERSION}",
        },
        method="POST",
    )
    if proxies is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler())
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))

    with opener.open(request, timeout=timeout) as response:
        response_body = response.read().decode("utf-8")
        return json.loads(response_body)


def _license_proxy_routes(proxy: dict[str, Any] | None) -> list[dict[str, str] | None]:
    """生成授权验证的出网路线，先直连，再尝试代理。"""
    routes: list[dict[str, str] | None] = [{}]
    if urllib.request.getproxies():
        routes.append(None)
    if _is_http_proxy_available(proxy):
        for candidate in _proxy_candidates(proxy or {}):
            proxy_url = f"http://{candidate['host']}:{int(candidate['port'])}"
            routes.append({"http": proxy_url, "https": proxy_url})
    return _dedupe_proxy_routes(routes)


def _is_http_proxy_available(proxy: dict[str, Any] | None) -> bool:
    """判断是否配置了可尝试的HTTP代理。"""
    if not proxy:
        return False
    mode = str(proxy.get("mode") or "").lower()
    if not mode:
        mode = "proxy" if proxy.get("enabled") else "direct"
    return mode in {"auto", "proxy"} and str(proxy.get("type") or "http").lower() == "http"


def _proxy_candidates(proxy: dict[str, Any]) -> list[dict[str, Any]]:
    """生成本机代理候选端口。"""
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
        candidates.append(candidate)
    return candidates


def _dedupe_proxy_routes(routes: list[dict[str, str] | None]) -> list[dict[str, str] | None]:
    """去掉重复出网路线。"""
    deduped: list[dict[str, str] | None] = []
    seen = set()
    for route in routes:
        if route is None:
            key = ("env",)
        else:
            key = tuple(sorted(route.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(route)
    return deduped
