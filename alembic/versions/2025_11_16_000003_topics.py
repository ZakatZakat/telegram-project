"""add topics and topic_items

Revision ID: topics_0003
Revises: ai_comments_0002
Create Date: 2025-11-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "topics_0003"
down_revision = "ai_comments_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("name", name="uq_topics_name"),
    )
    op.create_table(
        "topic_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages_raw.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("topic_id", "message_id", name="uq_topic_items_topic_message"),
    )
    op.create_index("ix_topic_items_topic_id", "topic_items", ["topic_id"], unique=False)
    op.create_index("ix_topic_items_message_id", "topic_items", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_topic_items_message_id", table_name="topic_items")
    op.drop_index("ix_topic_items_topic_id", table_name="topic_items")
    op.drop_table("topic_items")
    op.drop_table("topics")



