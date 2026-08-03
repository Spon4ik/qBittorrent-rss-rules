from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import obfuscate_secret
from app.models import AppSettings
from app.services.real_debrid import RealDebridAuthError, RealDebridClient
from app.services.settings_service import SettingsService


def ensure_real_debrid_access_token(session: Session, settings: AppSettings) -> str:
    config = SettingsService.resolve_real_debrid(settings)
    if not config.is_connected:
        raise RealDebridAuthError("Real-Debrid Device OAuth is not connected.")

    expires_at = getattr(settings, "real_debrid_token_expires_at", None)
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if config.access_token and (
        expires_at is None or expires_at > datetime.now(UTC) + timedelta(seconds=60)
    ):
        return config.access_token

    if not (config.client_id and config.client_secret and config.refresh_token):
        raise RealDebridAuthError("Real-Debrid refresh credentials are incomplete.")
    with RealDebridClient() as client:
        token = client.refresh_token(
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
        )
    settings.real_debrid_access_token_encrypted = obfuscate_secret(token.access_token)
    settings.real_debrid_refresh_token_encrypted = obfuscate_secret(token.refresh_token)
    settings.real_debrid_token_expires_at = token.expires_at
    session.add(settings)
    session.commit()
    return token.access_token
