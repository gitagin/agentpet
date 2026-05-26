from __future__ import annotations

import hashlib


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
