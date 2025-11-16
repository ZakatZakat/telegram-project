"""add projects and project_ideas

Revision ID: projects_0005
Revises: topic_snapshots_0004
Create Date: 2025-11-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "projects_0005"
down_revision = "topic_snapshots_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "project_ideas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("topic_item_id", sa.Integer(), sa.ForeignKey("topic_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("msg_id", sa.BigInteger(), nullable=True),
        sa.Column("post_text", sa.Text(), nullable=True),
        sa.Column("comment_text", sa.Text(), nullable=True),
        sa.Column("channel_username", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="idea"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_project_ideas_project_id", "project_ideas", ["project_id"], unique=False)
    op.create_index("ix_project_ideas_channel_msg", "project_ideas", ["channel_tg_id", "msg_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_project_ideas_channel_msg", table_name="project_ideas")
    op.drop_index("ix_project_ideas_project_id", table_name="project_ideas")
    op.drop_table("project_ideas")
    op.drop_table("projects")



