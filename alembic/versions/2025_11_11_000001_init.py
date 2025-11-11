"""init schema

Revision ID: init_0001
Revises:
Create Date: 2025-11-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "init_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("invite_link", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_message_id", sa.BigInteger(), nullable=True),
        sa.Column("polling_status", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("tg_id", name="uq_channels_tg_id"),
    )
    op.create_index("ix_channels_username", "channels", ["username"], unique=False)

    op.create_table(
        "messages_raw",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="CASCADE")),
        sa.Column("msg_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("channel_id", "msg_id", name="uq_messages_channel_msg"),
    )
    op.create_index("ix_messages_raw_hash", "messages_raw", ["hash"], unique=False)

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ends_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("location_text", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("venue", sa.String(length=256), nullable=True),
        sa.Column("price_min", sa.Float(), nullable=True),
        sa.Column("price_max", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("is_free", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_channel_id", sa.Integer(), sa.ForeignKey("channels.id")),
        sa.Column("source_msg_id", sa.BigInteger(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("dedupe_key", sa.String(length=64), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), sa.ForeignKey("messages_raw.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_events_starts_at", "events", ["starts_at"], unique=False)
    op.create_index("ix_events_ends_at", "events", ["ends_at"], unique=False)
    op.create_index("ix_events_city", "events", ["city"], unique=False)
    op.create_index("ix_events_category", "events", ["category"], unique=False)
    op.create_index("ix_events_dedupe_key", "events", ["dedupe_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_events_dedupe_key", table_name="events")
    op.drop_index("ix_events_category", table_name="events")
    op.drop_index("ix_events_city", table_name="events")
    op.drop_index("ix_events_ends_at", table_name="events")
    op.drop_index("ix_events_starts_at", table_name="events")
    op.drop_table("events")

    op.drop_index("ix_messages_raw_hash", table_name="messages_raw")
    op.drop_table("messages_raw")

    op.drop_index("ix_channels_username", table_name="channels")
    op.drop_table("channels")


