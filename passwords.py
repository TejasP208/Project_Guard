"""Typed wrapper around Passlib's dynamically exposed password hash."""

from importlib import import_module
from typing import Protocol, cast


class PasswordHasher(Protocol):
    def hash(self, secret: str) -> str: ...

    def verify(self, secret: str, hashed: str) -> bool: ...


_passlib_hash = import_module("passlib.hash")
_pbkdf2_sha256 = cast(PasswordHasher, _passlib_hash.pbkdf2_sha256)


def hash_password(password: str) -> str:
    return _pbkdf2_sha256.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pbkdf2_sha256.verify(password, hashed)
