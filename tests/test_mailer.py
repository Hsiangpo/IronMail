# -*- coding: utf-8 -*-

from ironmail import mailer


def test_choose_sender_rotates_by_sent_count_not_row_index():
    senders = [{"email": "a@example.com"}, {"email": "b@example.com"}]

    assert mailer.choose_sender(senders, sent_count=0, emails_per_account=2)["email"] == "a@example.com"
    assert mailer.choose_sender(senders, sent_count=1, emails_per_account=2)["email"] == "a@example.com"
    assert mailer.choose_sender(senders, sent_count=2, emails_per_account=2)["email"] == "b@example.com"
    assert mailer.choose_sender(senders, sent_count=4, emails_per_account=2)["email"] == "a@example.com"


def test_choose_sender_treats_bad_threshold_as_one():
    senders = [{"email": "a@example.com"}, {"email": "b@example.com"}]

    assert mailer.choose_sender(senders, sent_count=1, emails_per_account=0)["email"] == "b@example.com"


def test_build_message_uses_sender_display_name():
    message = mailer.build_message(
        sender={"email": "sales@oldiron.us", "name": "销售"},
        recipient_email="buyer@example.com",
        subject="主题",
        body="正文",
    )

    assert message["From"] == "销售 <sales@oldiron.us>"
    assert message["To"] == "buyer@example.com"
    assert "主题" in str(message["Subject"])


def test_auto_route_uses_direct_when_it_works(monkeypatch):
    calls = []

    def fake_direct(host, port, use_ssl, context, timeout):
        calls.append(("direct", host, port, use_ssl, timeout))
        return object()

    monkeypatch.setattr(mailer, "_open_direct_smtp", fake_direct)
    mailer._ROUTE_CACHE.clear()

    result = mailer.open_smtp_connection(
        {
            "host": "smtp.gmail.com",
            "port": 465,
            "use_ssl": True,
            "proxy": {"mode": "auto", "type": "http", "host": "127.0.0.1", "port": 7897},
        }
    )

    assert result is not None
    assert calls == [("direct", "smtp.gmail.com", 465, True, 8)]


def test_auto_route_falls_back_to_proxy_and_caches(monkeypatch):
    calls = []

    def fake_direct(host, port, use_ssl, context, timeout):
        calls.append(("direct", host, port, use_ssl, timeout))
        raise TimeoutError("blocked")

    def fake_proxy(host, port, use_ssl, proxy, context, timeout):
        calls.append(("proxy", host, port, use_ssl, proxy["host"], proxy["port"], timeout))
        return object(), f"proxy://{proxy['host']}:{proxy['port']}"

    monkeypatch.setattr(mailer, "_open_direct_smtp", fake_direct)
    monkeypatch.setattr(mailer, "_open_proxy_smtp", fake_proxy)
    mailer._ROUTE_CACHE.clear()
    smtp = {
        "host": "smtp.gmail.com",
        "port": 465,
        "use_ssl": True,
        "proxy": {
            "mode": "auto",
            "type": "http",
            "host": "127.0.0.1",
            "port": 7897,
            "candidate_ports": [7897, 7890],
        },
    }

    first = mailer.open_smtp_connection(smtp)
    second = mailer.open_smtp_connection(smtp)

    assert first is not None
    assert second is not None
    assert calls == [
        ("direct", "smtp.gmail.com", 465, True, 8),
        ("proxy", "smtp.gmail.com", 465, True, "127.0.0.1", 7897, 8),
        ("proxy", "smtp.gmail.com", 465, True, "127.0.0.1", 7897, 8),
    ]


def test_proxy_candidates_try_primary_then_fallback(monkeypatch):
    calls = []

    class FakeSMTP:
        def starttls(self, context):
            calls.append(("starttls",))

    def fake_ssl(host, port, proxy, context, timeout):
        calls.append(("ssl", proxy["port"]))
        if proxy["port"] == 7897:
            raise OSError("closed")
        return FakeSMTP()

    monkeypatch.setattr(mailer, "_HttpProxySMTPSSL", fake_ssl)

    server, route = mailer._open_proxy_smtp(
        "smtp.gmail.com",
        465,
        True,
        {
            "mode": "auto",
            "type": "http",
            "host": "127.0.0.1",
            "port": 7897,
            "candidate_ports": [7897, 7890],
        },
        context=None,
        timeout=8,
    )

    assert isinstance(server, FakeSMTP)
    assert route == "proxy://127.0.0.1:7890"
    assert calls == [("ssl", 7897), ("ssl", 7890)]
