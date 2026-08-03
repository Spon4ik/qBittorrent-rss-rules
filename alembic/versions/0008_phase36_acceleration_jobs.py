"""Add persistent download acceleration jobs.

Revision ID: 0008_phase36_acceleration_jobs
Revises: 0007_phase36_integration_settings
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_phase36_acceleration_jobs"
down_revision = "0007_phase36_integration_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "download_acceleration_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identity_key", sa.String(length=320), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("info_hash", sa.String(length=64), nullable=True),
        sa.Column("rule_id", sa.String(length=36), nullable=True),
        sa.Column("provider_torrent_id", sa.String(length=128), nullable=True),
        sa.Column("provider_download_id", sa.String(length=128), nullable=True),
        sa.Column("selected_files", sa.JSON(), nullable=False),
        sa.Column("webseed_token", sa.String(length=128), nullable=True),
        sa.Column("webseed_files", sa.JSON(), nullable=False),
        sa.Column("app_webseed_urls", sa.JSON(), nullable=False),
        sa.Column("myjd_job_ids", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_key"),
        sa.UniqueConstraint("webseed_token"),
    )
    op.create_index(
        "ix_download_acceleration_jobs_info_hash",
        "download_acceleration_jobs",
        ["info_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_download_acceleration_jobs_info_hash",
        table_name="download_acceleration_jobs",
    )
    op.drop_table("download_acceleration_jobs")
