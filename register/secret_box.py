"""API Key 的对称加密。

密钥由 SECRET_KEY 经 SHA-256 派生，不额外引入配置项。
注意：更换 SECRET_KEY 会导致已存的 key 无法解密，用户需要重新填写。
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _box(secret):
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(secret, plain):
    return _box(secret).encrypt(plain.encode("utf-8"))


def decrypt(secret, token):
    try:
        return _box(secret).decrypt(bytes(token)).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


def mask(api_key):
    """sk-abcdef123456 → sk-****3456"""
    if not api_key:
        return ""
    k = api_key.strip()
    if len(k) <= 8:
        return "****"
    prefix = "sk-" if k.startswith("sk-") else k[:3]
    return f"{prefix}****{k[-4:]}"
