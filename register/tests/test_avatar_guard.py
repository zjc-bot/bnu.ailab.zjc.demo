"""头像上传应用层加固回归：真实格式白名单与解码前像素上限。"""

import io
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-for-avatar-guard")

import app as app_module  # noqa: E402


DISGUISED = [
    b"8BPS\x00\x01" + b"\x00" * 32,          # PSD
    b"II*\x00" + b"\x00" * 32,               # TIFF
    b"BM" + b"\x00" * 32,                    # BMP
    b"GIF89a" + b"\x00" * 32,                # GIF
    b"%PDF-1.7\n" + b"\x00" * 32,            # PDF
    b"RIFF\x00\x00\x00\x00XXXX",             # 伪装 RIFF 但非 WEBP
    b"",                                      # 空文件
]


def _encoded(fmt, size=(200, 200)):
    im = Image.new("RGB", size, (12, 34, 56))
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


@pytest.mark.parametrize("fmt,expected", [
    ("JPEG", "JPEG"), ("PNG", "PNG"), ("WEBP", "WEBP"),
])
def test_real_format_accepts_only_allowed(fmt, expected):
    assert app_module._avatar_real_format(_encoded(fmt)) == expected


@pytest.mark.parametrize("payload", DISGUISED)
def test_real_format_rejects_other_formats(payload):
    assert app_module._avatar_real_format(payload) is None


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_open_accepts_valid_images(fmt):
    im, err = app_module._open_avatar_image(_encoded(fmt))
    assert err is None
    assert im.size == (200, 200)


@pytest.mark.parametrize("payload", DISGUISED)
def test_open_rejects_disguised_payload_before_parsing(payload):
    im, err = app_module._open_avatar_image(payload)
    assert im is None
    assert "格式" in err


def test_open_rejects_tiny_image():
    im, err = app_module._open_avatar_image(_encoded("PNG", (10, 10)))
    assert im is None
    assert "太小" in err


def test_pixel_limit_is_checked_before_decode(monkeypatch):
    class Huge:
        format = "PNG"
        size = (100000, 100000)
        width = height = 100000

        def load(self):
            raise AssertionError("load() 不应在像素上限检查之前被调用")

    monkeypatch.setattr(Image, "open", lambda fp: Huge())
    im, err = app_module._open_avatar_image(_encoded("PNG"))
    assert im is None
    assert "像素过大" in err


def test_format_mismatch_is_rejected(monkeypatch):
    class Mismatch:
        format = "TIFF"
        size = (200, 200)
        width = height = 200

        def load(self):
            raise AssertionError("格式不一致时不应解码")

    monkeypatch.setattr(Image, "open", lambda fp: Mismatch())
    im, err = app_module._open_avatar_image(_encoded("PNG"))
    assert im is None
    assert "不一致" in err


def test_open_rejects_truncated_image():
    im, err = app_module._open_avatar_image(_encoded("PNG")[:40])
    assert im is None
    assert err is not None
