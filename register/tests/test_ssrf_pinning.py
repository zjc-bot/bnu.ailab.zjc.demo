"""BYOK SSRF：非 global 地址拒绝与 DNS pin/Host/SNI/证书回归。"""

import os
import socket
import sys
from urllib.parse import urlparse

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-for-ssrf-pinning")

import app as app_module


def dns_result(*addresses):
    return [
        (socket.AF_INET6 if ":" in address else socket.AF_INET,
         socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
         (address, 443, 0, 0) if ":" in address else (address, 443))
        for address in addresses
    ]


@pytest.mark.parametrize("address", [
    "100.64.0.0", "100.127.255.255", "127.0.0.1", "10.0.0.1",
    "169.254.169.254", "192.0.2.1", "198.18.0.1", "::1", "fc00::1",
    "2001:db8::1", "::ffff:127.0.0.1", "::ffff:100.64.0.1",
])
def test_bad_ip_rejects_non_global_addresses(address):
    assert app_module._bad_ip(address) is True


@pytest.mark.parametrize("address", ["1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"])
def test_bad_ip_accepts_global_addresses(address):
    assert app_module._bad_ip(address) is False


def test_public_domain_returns_all_pinned_ips(monkeypatch):
    monkeypatch.setattr(app_module.socket, "getaddrinfo",
                        lambda *args, **kwargs: dns_result("1.1.1.1", "8.8.8.8"))
    ok, why, ips = app_module._base_url_pinned("https://api.example.com/v1")
    assert ok is True and why == ""
    assert ips == ["1.1.1.1", "8.8.8.8"]


@pytest.mark.parametrize("url", [
    "https://100.64.0.1/v1", "https://192.0.2.1/v1", "https://[::ffff:127.0.0.1]/v1",
])
def test_private_literal_rejected_without_dns(monkeypatch, url):
    monkeypatch.setattr(app_module.socket, "getaddrinfo",
                        lambda *args, **kwargs: pytest.fail("字面 IP 不应解析 DNS"))
    ok, why, ips = app_module._base_url_pinned(url)
    assert ok is False and "内网" in why and ips == []


def test_mixed_dns_answers_fail_closed(monkeypatch):
    monkeypatch.setattr(app_module.socket, "getaddrinfo",
                        lambda *args, **kwargs: dns_result("1.1.1.1", "100.64.0.1"))
    ok, why, ips = app_module._base_url_pinned("https://evil.example/v1")
    assert ok is False and "内网" in why and ips == []


def test_pinned_post_uses_ip_hostname_and_no_environment_proxy(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

    class Session:
        def __enter__(self):
            self.trust_env = True
            return self

        def __exit__(self, *args):
            captured["closed"] = True
            return False

        def mount(self, prefix, adapter):
            captured["pool"] = adapter.poolmanager.connection_pool_kw.copy()

        def post(self, url, **kwargs):
            captured.update(url=url, headers=kwargs["headers"],
                            redirects=kwargs["allow_redirects"], trust_env=self.trust_env)
            return Response()

    monkeypatch.setattr(app_module.requests, "Session", Session)
    app_module._pinned_post(
        "https://api.example.com:8443/v1/chat/completions", ["1.1.1.1"],
        headers={"Authorization": "Bearer x"}, allow_redirects=True,
    )
    assert urlparse(captured["url"]).hostname == "1.1.1.1"
    assert captured["headers"]["Host"] == "api.example.com:8443"
    assert captured["redirects"] is False
    assert captured["trust_env"] is False and captured["closed"] is True
    assert captured["pool"]["server_hostname"] == "api.example.com"
    assert captured["pool"]["assert_hostname"] == "api.example.com"


def test_ipv6_url_uses_brackets_and_original_host_header(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def mount(self, *args): pass
        def post(self, url, **kwargs):
            captured.update(url=url, headers=kwargs["headers"])
            return Response()

    monkeypatch.setattr(app_module.requests, "Session", Session)
    app_module._pinned_post("https://[2606:4700:4700::1111]/v1/chat/completions",
                            ["2606:4700:4700::1111"])
    assert captured["url"] == "https://[2606:4700:4700::1111]:443/v1/chat/completions"
    assert captured["headers"]["Host"] == "[2606:4700:4700::1111]"


def test_pinned_post_falls_back_without_ips(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

    def post(url, **kwargs):
        captured.update(url=url, redirects=kwargs["allow_redirects"])
        return Response()

    monkeypatch.setattr(app_module.requests, "post", post)
    app_module._pinned_post("https://api.deepseek.com/chat/completions", [])
    assert captured == {"url": "https://api.deepseek.com/chat/completions", "redirects": False}
