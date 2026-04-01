"""Add rule search snapshot storage.

Revision ID: 0004_rule_search_snapshots
Revises: 0003_search_queue_defaults
Create Date: 2026-03-14 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_rule_search_snapshots"
down_revision = "0003_search_queue_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_search_snapshots",
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("inline_search", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rule_id"),
    )


def downgrade() -> None:
    op.drop_table("rule_search_snapshots")
