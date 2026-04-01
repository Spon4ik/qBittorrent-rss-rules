"""Add indexer category catalog table.

Revision ID: 0002_indexer_category_catalog
Revises: 0001_initial_schema
Create Date: 2026-03-12 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_indexer_category_catalog"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "indexer_category_catalog",
        sa.Column("indexer", sa.String(length=255), nullable=False),
        sa.Column("category_id", sa.String(length=64), nullable=False),
        sa.Column("category_name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("indexer", "category_id"),
    )


def downgrade() -> None:
    op.drop_table("indexer_category_catalog")
