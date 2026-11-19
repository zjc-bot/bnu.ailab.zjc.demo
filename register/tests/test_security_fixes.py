"""安全修复回归测试：SSRF 白名单、邮件 HTML 转义。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-for-security")

import mailer  # noqa: E402

# 从 app 模块导入校验函数（导入会触发 SECRET_KEY 检查，已设置）
import app as app_module  # noqa: E402

base_url_safe = app_module._base_url_safe


def test_ssrf_rejects_local_and_private():
    for url in (
        "http://127.0.0.1:8080",
        "https://127.0.0.1",
        "http://169.254.169.254/latest/meta-data",
        "https://localhost",
        "https://10.0.0.1",
        "https://192.168.1.1",
        "https://foo.local",
        "http://api.deepseek.com",       # 非 https 也拒绝
    ):
        ok, _ = base_url_safe(url)
        assert ok is False, url


def test_ssrf_accepts_public_https(monkeypatch):
    # 避免真实 DNS 查询：mock getaddrinfo 返回公网 IP
    import socket
    monkeypatch.setattr(
        app_module.socket, "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))],
    )
    ok, why = base_url_safe("https://api.example.com/v1")
    assert ok is True, why


def test_ssrf_rejects_credentials_and_query():
    for url in (
        "https://user:pass@api.example.com",
        "https://api.example.com?x=1",
        "https://api.example.com/#frag",
    ):
        ok, _ = base_url_safe(url)
        assert ok is False, url


def test_mailer_escapes_user_agent(monkeypatch):
    """UA 含 HTML 时必须转义，不能原样进邮件正文。"""
    captured = {}

    def fake_send(to, subject, text, body_html):
        captured["html"] = body_html

    monkeypatch.setattr(mailer, "_send", fake_send)
    evil = '<a href="//evil.test">click</a>'
    mailer.send_login_alert("a@b.com", "昵称", "203.0.113.1", evil, "现在")
    assert "<a href" not in captured["html"]
    assert "&lt;a href" in captured["html"]


def test_ssrf_rejects_domain_resolving_to_private(monkeypatch):
    """核心分支：域名解析到私网 IP 必须拒绝（原测试零覆盖）。"""
    import socket

    def fake(*a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]

    monkeypatch.setattr(app_module.socket, "getaddrinfo", fake)
    ok, why = base_url_safe("https://evil.example.com/v1")
    assert ok is False and "内网" in why


def test_ssrf_rejects_any_private_ip_among_many(monkeypatch):
    """多 IP 时任一为私网即拒绝（不能只看第一个）。"""
    import socket

    def fake(*a, **kw):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
        ]

    monkeypatch.setattr(app_module.socket, "getaddrinfo", fake)
    ok, _ = base_url_safe("https://multi.example.com/v1")
    assert ok is False


def test_ssrf_hostname_blacklist_independent_of_dns(monkeypatch):
    """即使 DNS 返回公网 IP，localhost/.local 也必须被主机名黑名单拒绝。"""
    import socket

    monkeypatch.setattr(
        app_module.socket, "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))],
    )
    for url in ("https://localhost/v1", "https://foo.local/v1"):
        ok, _ = base_url_safe(url)
        assert ok is False, url


def test_ssrf_rejects_malformed_port():
    """畸形端口不能抛 ValueError / 500，而是友好拒绝。"""
    for url in ("https://api.example.com:abc/v1", "https://api.example.com:99999/v1"):
        ok, why = base_url_safe(url)
        assert ok is False and why, url


def test_ssrf_metadata_https():
    """云元数据地址即使走 https 也要拒绝（原 http 用例是假阳性）。"""
    ok, _ = base_url_safe("https://169.254.169.254/latest/meta-data")
    assert ok is False
