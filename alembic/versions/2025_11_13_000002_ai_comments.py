"""add ai_comments

Revision ID: ai_comments_0002
Revises: init_0001
Create Date: 2025-11-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "ai_comments_0002"
down_revision = "init_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages_raw.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("comment_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("message_id", "model", name="uq_ai_comments_message_model"),
    )
    op.create_index("ix_ai_comments_message_id", "ai_comments", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_comments_message_id", table_name="ai_comments")
    op.drop_table("ai_comments")


