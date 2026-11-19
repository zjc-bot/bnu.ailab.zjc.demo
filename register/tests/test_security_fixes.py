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
