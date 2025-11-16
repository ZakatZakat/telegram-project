"""extend topic_items with stable keys and snapshot

Revision ID: topic_snapshots_0004
Revises: topics_0003
Create Date: 2025-11-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "topic_snapshots_0004"
down_revision = "topics_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # add new columns (nullable for backfill)
    op.add_column("topic_items", sa.Column("channel_tg_id", sa.BigInteger(), nullable=True))
    op.add_column("topic_items", sa.Column("msg_id", sa.BigInteger(), nullable=True))
    op.add_column("topic_items", sa.Column("post_text", sa.Text(), nullable=True))
    op.add_column("topic_items", sa.Column("comment_text", sa.Text(), nullable=True))
    op.add_column("topic_items", sa.Column("channel_username", sa.String(length=255), nullable=True))
    op.add_column("topic_items", sa.Column("source_url", sa.Text(), nullable=True))
    # replace unique constraint
    with op.batch_alter_table("topic_items") as batch_op:
        batch_op.drop_constraint("uq_topic_items_topic_message", type_="unique")
        batch_op.create_unique_constraint("uq_topic_items_topic_msgkey", ["topic_id", "channel_tg_id", "msg_id"])
    # backfill keys and snapshot from existing link if present
    op.execute(
        """
        UPDATE topic_items ti
        SET channel_tg_id = c.tg_id,
            msg_id = m.msg_id,
            post_text = COALESCE(m.text, ''),
            comment_text = ac.comment_text,
            channel_username = c.username,
            source_url = CASE WHEN c.username IS NOT NULL THEN 'https://t.me/' || c.username || '/' || m.msg_id ELSE NULL END
        FROM messages_raw m
        JOIN channels c ON c.id = m.channel_id
        LEFT JOIN LATERAL (
            SELECT comment_text FROM ai_comments WHERE message_id = m.id ORDER BY id DESC LIMIT 1
        ) ac ON TRUE
        WHERE ti.message_id = m.id
        """
    )
    op.create_index("ix_topic_items_channel_tg_id", "topic_items", ["channel_tg_id"], unique=False)
    op.create_index("ix_topic_items_msg_id", "topic_items", ["msg_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("topic_items") as batch_op:
        batch_op.drop_constraint("uq_topic_items_topic_msgkey", type_="unique")
        batch_op.create_unique_constraint("uq_topic_items_topic_message", ["topic_id", "message_id"])
    op.drop_index("ix_topic_items_msg_id", table_name="topic_items")
    op.drop_index("ix_topic_items_channel_tg_id", table_name="topic_items")
    op.drop_column("topic_items", "source_url")
    op.drop_column("topic_items", "channel_username")
    op.drop_column("topic_items", "comment_text")
    op.drop_column("topic_items", "post_text")
    op.drop_column("topic_items", "msg_id")
    op.drop_column("topic_items", "channel_tg_id")



