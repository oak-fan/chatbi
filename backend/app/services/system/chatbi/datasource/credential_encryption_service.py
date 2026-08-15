"""ChatBI 数据源凭证 AES-256-GCM 加解密。"""

from __future__ import annotations

import base64
import binascii
import os
from hashlib import sha256

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE_BYTES = 12


def _derive_key(raw: str) -> bytes:
    digest = sha256(raw.encode("utf-8")).digest()
    return digest


class ChatbiCredentialEncryptionService:
    """AES-256-GCM，密文 Base64（nonce + ciphertext + tag）。"""

    def __init__(self, *, key_material: str | None) -> None:
        self._key_material = key_material

    def encrypt(self, plaintext: str) -> str:
        """明文密码 → Base64 密文（nonce + tag + ciphertext）。"""

        if not self._key_material:
            msg = "CHATBI_DATASOURCE_CREDENTIAL_ENCRYPTION_KEY 未配置"
            raise ValueError(msg)
        key = _derive_key(self._key_material)
        aesgcm = AESGCM(key)
        nonce = os.urandom(_NONCE_SIZE_BYTES)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, ciphertext_b64: str) -> str:
        """Base64 密文 → 明文密码。"""

        if not self._key_material:
            msg = "CHATBI_DATASOURCE_CREDENTIAL_ENCRYPTION_KEY 未配置"
            raise ValueError(msg)
        try:
            raw = base64.b64decode(ciphertext_b64.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError) as exc:
            msg = "数据源凭证解密失败"
            raise ValueError(msg) from exc
        if len(raw) <= _NONCE_SIZE_BYTES:
            msg = "数据源凭证解密失败"
            raise ValueError(msg)
        nonce, ct = raw[:_NONCE_SIZE_BYTES], raw[_NONCE_SIZE_BYTES:]
        key = _derive_key(self._key_material)
        aesgcm = AESGCM(key)
        try:
            pt = aesgcm.decrypt(nonce, ct, None)
            return pt.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            msg = "数据源凭证解密失败"
            raise ValueError(msg) from exc


__all__ = ["ChatbiCredentialEncryptionService"]
