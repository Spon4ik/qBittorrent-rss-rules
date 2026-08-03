from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

SECRET_ENVELOPE_PREFIX = "enc:v1:"
DEFAULT_SECRET_KEY_PATH = Path(__file__).resolve().parents[2] / "data" / ".secret-key"


class SecretStorageError(RuntimeError):
    pass


def encrypt_secret(value: str) -> str:
    token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{SECRET_ENVELOPE_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith(SECRET_ENVELOPE_PREFIX):
        token = value.removeprefix(SECRET_ENVELOPE_PREFIX)
        try:
            return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise SecretStorageError(
                "A saved secret cannot be decrypted with the configured application key. "
                "Restore data/.secret-key (or QB_RULES_SECRET_KEY) with the database backup, "
                "or clear and re-enter the affected credential."
            ) from exc

    # Backward compatibility for the pre-v1.4 base64-only storage format.
    try:
        return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
    except Exception:
        return None


def is_encrypted_secret(value: str | None) -> bool:
    return bool(value and value.startswith(SECRET_ENVELOPE_PREFIX))


def migrate_secret_envelope(value: str | None) -> str | None:
    if not value or is_encrypted_secret(value):
        return value
    plaintext = decrypt_secret(value)
    if plaintext is None:
        return value
    return encrypt_secret(plaintext)


def reset_secret_store_cache() -> None:
    _fernet.cache_clear()


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw_key = str(os.getenv("QB_RULES_SECRET_KEY") or "").strip()
    if raw_key:
        return _build_fernet(raw_key.encode("ascii"), source="QB_RULES_SECRET_KEY")

    key_path = DEFAULT_SECRET_KEY_PATH
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        key = key_path.read_bytes().strip()
    except FileNotFoundError:
        key = Fernet.generate_key()
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = key_path.read_bytes().strip()
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(key + b"\n")
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
    except OSError as exc:
        raise SecretStorageError(f"Unable to read application secret key at {key_path}: {exc}") from exc
    return _build_fernet(key, source=str(key_path))


def _build_fernet(key: bytes, *, source: str) -> Fernet:
    try:
        return Fernet(key)
    except (TypeError, ValueError) as exc:
        raise SecretStorageError(
            f"The application secret key from {source} is not a valid Fernet key."
        ) from exc
