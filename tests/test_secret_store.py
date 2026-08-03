from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet

from app.services import secret_store


def test_secret_round_trip_uses_versioned_authenticated_envelope() -> None:
    encrypted = secret_store.encrypt_secret("provider-password")

    assert encrypted.startswith(secret_store.SECRET_ENVELOPE_PREFIX)
    assert "provider-password" not in encrypted
    assert secret_store.decrypt_secret(encrypted) == "provider-password"
    assert secret_store.is_encrypted_secret(encrypted) is True


def test_legacy_base64_secret_remains_readable_and_migrates() -> None:
    legacy = base64.urlsafe_b64encode(b"legacy-secret").decode("ascii")

    migrated = secret_store.migrate_secret_envelope(legacy)

    assert secret_store.decrypt_secret(legacy) == "legacy-secret"
    assert migrated is not None
    assert migrated.startswith(secret_store.SECRET_ENVELOPE_PREFIX)
    assert secret_store.decrypt_secret(migrated) == "legacy-secret"


def test_encrypted_secret_fails_closed_with_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    encrypted = secret_store.encrypt_secret("sensitive")
    monkeypatch.setenv("QB_RULES_SECRET_KEY", Fernet.generate_key().decode("ascii"))
    secret_store.reset_secret_store_cache()

    with pytest.raises(secret_store.SecretStorageError, match="cannot be decrypted"):
        secret_store.decrypt_secret(encrypted)


def test_secret_key_is_created_in_runtime_data(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_path = tmp_path / "data" / ".secret-key"
    monkeypatch.delenv("QB_RULES_SECRET_KEY", raising=False)
    monkeypatch.setattr(secret_store, "DEFAULT_SECRET_KEY_PATH", key_path)
    secret_store.reset_secret_store_cache()

    encrypted = secret_store.encrypt_secret("generated-key-secret")

    assert key_path.is_file()
    assert secret_store.decrypt_secret(encrypted) == "generated-key-secret"
