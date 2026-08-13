"""Add acceleration notification dismissal state.

Revision ID: 0009_acceleration_notification_lifecycle
Revises: 0008_phase36_acceleration_jobs
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_acceleration_notification_lifecycle"
down_revision = "0008_phase36_acceleration_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "download_acceleration_jobs",
        sa.Column("notification_dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "download_acceleration_jobs",
        sa.Column("torrent_name", sa.String(length=512), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("download_acceleration_jobs", "torrent_name")
    op.drop_column("download_acceleration_jobs", "notification_dismissed_at")
