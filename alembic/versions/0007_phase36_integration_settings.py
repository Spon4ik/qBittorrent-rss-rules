"""Add Phase 36 Real-Debrid and MyJDownloader settings.

Revision ID: 0007_phase36_integration_settings
Revises: b444a9971f02
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_phase36_integration_settings"
down_revision = "b444a9971f02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        sa.Column("real_debrid_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("real_debrid_client_id_encrypted", sa.Text(), nullable=True),
        sa.Column("real_debrid_client_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("real_debrid_access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("real_debrid_refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("real_debrid_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("real_debrid_account_username", sa.String(length=255), nullable=True),
        sa.Column("real_debrid_account_premium_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "real_debrid_connection_status",
            sa.String(length=32),
            nullable=False,
            server_default="disconnected",
        ),
        sa.Column(
            "real_debrid_connection_message", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column(
            "real_debrid_webseed_base_url",
            sa.String(length=512),
            nullable=False,
            server_default="http://127.0.0.1:8000",
        ),
        sa.Column(
            "real_debrid_metadata_wait_seconds",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
        sa.Column("myjd_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("myjd_email", sa.String(length=255), nullable=True),
        sa.Column("myjd_password_encrypted", sa.Text(), nullable=True),
        sa.Column("myjd_device_id", sa.String(length=255), nullable=True),
        sa.Column("myjd_device_name", sa.String(length=255), nullable=True),
        sa.Column(
            "myjd_connection_status",
            sa.String(length=32),
            nullable=False,
            server_default="disconnected",
        ),
        sa.Column("myjd_connection_message", sa.Text(), nullable=False, server_default=""),
    )
    for column in columns:
        op.add_column("app_settings", column)


def downgrade() -> None:
    for column_name in (
        "myjd_connection_message",
        "myjd_connection_status",
        "myjd_device_name",
        "myjd_device_id",
        "myjd_password_encrypted",
        "myjd_email",
        "myjd_enabled",
        "real_debrid_metadata_wait_seconds",
        "real_debrid_webseed_base_url",
        "real_debrid_connection_message",
        "real_debrid_connection_status",
        "real_debrid_account_premium_until",
        "real_debrid_account_username",
        "real_debrid_token_expires_at",
        "real_debrid_refresh_token_encrypted",
        "real_debrid_access_token_encrypted",
        "real_debrid_client_secret_encrypted",
        "real_debrid_client_id_encrypted",
        "real_debrid_enabled",
    ):
        op.drop_column("app_settings", column_name)
