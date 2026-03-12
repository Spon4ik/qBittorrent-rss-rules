"""Initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-01 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_name", sa.String(length=255), nullable=False),
        sa.Column("content_name", sa.String(length=255), nullable=False),
        sa.Column("imdb_id", sa.String(length=32), nullable=True),
        sa.Column("normalized_title", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("quality_profile", sa.String(length=32), nullable=False),
        sa.Column("release_year", sa.String(length=16), nullable=False),
        sa.Column("include_release_year", sa.Boolean(), nullable=False),
        sa.Column("additional_includes", sa.Text(), nullable=False),
        sa.Column("quality_include_tokens", sa.JSON(), nullable=False),
        sa.Column("quality_exclude_tokens", sa.JSON(), nullable=False),
        sa.Column("use_regex", sa.Boolean(), nullable=False),
        sa.Column("must_contain_override", sa.Text(), nullable=True),
        sa.Column("must_not_contain", sa.Text(), nullable=False),
        sa.Column("start_season", sa.Integer(), nullable=True),
        sa.Column("start_episode", sa.Integer(), nullable=True),
        sa.Column("episode_filter", sa.Text(), nullable=False),
        sa.Column("ignore_days", sa.Integer(), nullable=False),
        sa.Column("add_paused", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("smart_filter", sa.Boolean(), nullable=False),
        sa.Column("assigned_category", sa.String(length=255), nullable=False),
        sa.Column("save_path", sa.String(length=255), nullable=False),
        sa.Column("feed_urls", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("remote_rule_name_last_synced", sa.String(length=255), nullable=True),
        sa.Column("last_sync_status", sa.String(length=32), nullable=False),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_name"),
    )
    op.create_table(
        "app_settings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("qb_base_url", sa.String(length=255), nullable=True),
        sa.Column("qb_username", sa.String(length=255), nullable=True),
        sa.Column("qb_password_encrypted", sa.Text(), nullable=True),
        sa.Column("jackett_api_url", sa.String(length=255), nullable=True),
        sa.Column("jackett_qb_url", sa.String(length=255), nullable=True),
        sa.Column("jackett_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("metadata_provider", sa.String(length=32), nullable=False),
        sa.Column("omdb_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("series_category_template", sa.String(length=255), nullable=False),
        sa.Column("movie_category_template", sa.String(length=255), nullable=False),
        sa.Column("save_path_template", sa.String(length=255), nullable=False),
        sa.Column("default_add_paused", sa.Boolean(), nullable=False),
        sa.Column("default_sequential_download", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_first_last_piece_prio", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_enabled", sa.Boolean(), nullable=False),
        sa.Column("quality_profile_rules", sa.JSON(), nullable=False),
        sa.Column("saved_quality_profiles", sa.JSON(), nullable=False),
        sa.Column("default_feed_urls", sa.JSON(), nullable=False),
        sa.Column("search_result_view_mode", sa.String(length=16), nullable=False),
        sa.Column("search_sort_criteria", sa.JSON(), nullable=False),
        sa.Column("default_quality_profile", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sync_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=True),
        sa.Column("rule_name", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("import_batches")
    op.drop_table("sync_events")
    op.drop_table("app_settings")
    op.drop_table("rules")
