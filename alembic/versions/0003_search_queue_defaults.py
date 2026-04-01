"""Add search queue default options to app settings.

Revision ID: 0003_search_queue_defaults
Revises: 0002_indexer_category_catalog
Create Date: 2026-03-12 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_search_queue_defaults"
down_revision = "0002_indexer_category_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "default_sequential_download", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "default_first_last_piece_prio", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "default_first_last_piece_prio")
    op.drop_column("app_settings", "default_sequential_download")
