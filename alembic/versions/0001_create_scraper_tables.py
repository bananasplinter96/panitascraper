"""create scraper tables

Revision ID: 0001
Revises:
Create Date: 2026-06-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "spider_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("urls", sa.JSON(), nullable=False),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("schedule", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_spider_config_name", "spider_config", ["name"])

    op.create_table(
        "scrape_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("spider_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("log_path", sa.String(512), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["spider_name"], ["spider_config.name"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scrape_run_spider_name", "scrape_run", ["spider_name"])

    op.create_table(
        "scraped_file",
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("spider_name", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("checksum"),
    )

    op.create_table(
        "run_file",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["checksum"], ["scraped_file.checksum"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["scrape_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "checksum", name="uq_run_file"),
    )
    op.create_index("ix_run_file_run_id", "run_file", ["run_id"])


def downgrade() -> None:
    op.drop_table("run_file")
    op.drop_table("scraped_file")
    op.drop_table("scrape_run")
    op.drop_table("spider_config")
