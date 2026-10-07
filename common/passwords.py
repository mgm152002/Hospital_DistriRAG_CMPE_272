"""Salted scrypt password hashes; passwords never leave the authentication boundary."""

import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("Use a password between 12 and 128 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        kind, salt_hex, expected = encoded.split("$")
        if kind != "scrypt" or len(salt_hex) != 32 or len(expected) != 64 or len(password) > 128:
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False
