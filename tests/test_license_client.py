# -*- coding: utf-8 -*-

import json
import urllib.error

from ironmail import license as license_client


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_license_verify_falls_back_to_configured_http_proxy(monkeypatch):
    attempts = []

    class FakeOpener:
        def __init__(self, proxies):
            self.proxies = proxies

        def open(self, request, timeout):
            attempts.append(self.proxies)
            if self.proxies == {}:
                raise urllib.error.URLError("direct blocked")
            if self.proxies and self.proxies.get("https") == "http://127.0.0.1:7897":
                return FakeResponse({"valid": True, "expires_at": None})
            raise urllib.error.URLError("proxy blocked")

    def fake_build_opener(handler=None):
        return FakeOpener(getattr(handler, "proxies", None))

    monkeypatch.setattr("urllib.request.build_opener", fake_build_opener)

    result = license_client._post_verify_request(
        "https://tmpmail.oldiron.us",
        "IM-CAX45O-JQIJZX-I6RIPY-U03NEV",
        10,
        {
            "mode": "auto",
            "type": "http",
            "host": "127.0.0.1",
            "port": 7897,
            "candidate_ports": [7897, 7890],
        },
    )

    assert result["valid"] is True
    assert {} in attempts
    assert any(
        attempt and attempt.get("https") == "http://127.0.0.1:7897"
        for attempt in attempts
    )


def test_license_verify_raises_last_network_error_when_all_routes_fail(monkeypatch):
    def fake_build_opener(handler=None):
        class FakeOpener:
            def open(self, request, timeout):
                raise urllib.error.URLError("blocked")

        return FakeOpener()

    monkeypatch.setattr("urllib.request.build_opener", fake_build_opener)

    try:
        license_client._post_verify_request(
            "https://tmpmail.oldiron.us",
            "IM-CAX45O-JQIJZX-I6RIPY-U03NEV",
            10,
            {"mode": "auto", "type": "http", "host": "127.0.0.1", "port": 7897},
        )
    except urllib.error.URLError as error:
        assert "blocked" in str(error.reason)
    else:
        raise AssertionError("授权验证网络全部失败时必须抛出最后一次错误")
