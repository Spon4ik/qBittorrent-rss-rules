"""Add phase-9 rule poster and release-ops settings fields.

Revision ID: 0005_rules_main_page_release_ops
Revises: 0004_rule_search_snapshots
Create Date: 2026-03-15 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_rules_main_page_release_ops"
down_revision = "0004_rule_search_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rules",
        sa.Column("poster_url", sa.String(length=512), nullable=True),
    )

    op.add_column(
        "app_settings",
        sa.Column("rules_fetch_schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "rules_fetch_schedule_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="360",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "rules_fetch_schedule_scope",
            sa.String(length=32),
            nullable=False,
            server_default="enabled",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("rules_fetch_schedule_last_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column("rules_fetch_schedule_next_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "rules_fetch_schedule_last_status",
            sa.String(length=32),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "rules_fetch_schedule_last_message",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("rules_page_view_mode", sa.String(length=16), nullable=False, server_default="table"),
    )
    op.add_column(
        "app_settings",
        sa.Column("rules_page_sort_field", sa.String(length=64), nullable=False, server_default="updated_at"),
    )
    op.add_column(
        "app_settings",
        sa.Column("rules_page_sort_direction", sa.String(length=8), nullable=False, server_default="desc"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "rules_page_sort_direction")
    op.drop_column("app_settings", "rules_page_sort_field")
    op.drop_column("app_settings", "rules_page_view_mode")
    op.drop_column("app_settings", "rules_fetch_schedule_last_message")
    op.drop_column("app_settings", "rules_fetch_schedule_last_status")
    op.drop_column("app_settings", "rules_fetch_schedule_next_run_at")
    op.drop_column("app_settings", "rules_fetch_schedule_last_run_at")
    op.drop_column("app_settings", "rules_fetch_schedule_scope")
    op.drop_column("app_settings", "rules_fetch_schedule_interval_minutes")
    op.drop_column("app_settings", "rules_fetch_schedule_enabled")
    op.drop_column("rules", "poster_url")
