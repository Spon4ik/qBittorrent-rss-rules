"""Add dedicated rule snapshot release-cache columns.

Revision ID: 0006_rule_snapshot_release_cache_columns
Revises: 0005_rules_main_page_release_ops
Create Date: 2026-03-22 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_rule_snapshot_release_cache_columns"
down_revision = "0005_rules_main_page_release_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule_search_snapshots",
        sa.Column("release_filter_cache_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "rule_search_snapshots",
        sa.Column("release_filtered_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "rule_search_snapshots",
        sa.Column("release_fetched_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rule_search_snapshots", "release_fetched_count")
    op.drop_column("rule_search_snapshots", "release_filtered_count")
    op.drop_column("rule_search_snapshots", "release_filter_cache_key")
