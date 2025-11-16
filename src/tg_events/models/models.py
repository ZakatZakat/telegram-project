from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tg_events.models.base import Base, TimestampMixin


class AiComment(TimestampMixin, Base):
    __tablename__ = "ai_comments"
    __table_args__ = (UniqueConstraint("message_id", "model", name="uq_ai_comments_message_model"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages_raw.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)

    message: Mapped["MessageRaw"] = relationship()


class Topic(TimestampMixin, Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("name", name="uq_topics_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    items: Mapped[list["TopicItem"]] = relationship(back_populates="topic", cascade="all, delete-orphan")


class TopicItem(TimestampMixin, Base):
    __tablename__ = "topic_items"
    __table_args__ = (
        UniqueConstraint("topic_id", "channel_tg_id", "msg_id", name="uq_topic_items_topic_msgkey"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    # legacy link (may be null) — kept for backward-compat
    message_id: Mapped[Optional[int]] = mapped_column(ForeignKey("messages_raw.id", ondelete="CASCADE"), index=True, nullable=True)
    # stable key
    channel_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    msg_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    # snapshot
    post_text: Mapped[Optional[str]] = mapped_column(Text)
    comment_text: Mapped[Optional[str]] = mapped_column(Text)
    channel_username: Mapped[Optional[str]] = mapped_column(String(255))
    source_url: Mapped[Optional[str]] = mapped_column(Text)

    topic: Mapped["Topic"] = relationship(back_populates="items")
    message: Mapped["MessageRaw"] = relationship()

class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft")

    ideas: Mapped[list["ProjectIdea"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectIdea(TimestampMixin, Base):
    __tablename__ = "project_ideas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    topic_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topic_items.id", ondelete="SET NULL"))
    # stable key and snapshot (duplicated from TopicItem at the time of addition)
    channel_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    msg_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    post_text: Mapped[Optional[str]] = mapped_column(Text)
    comment_text: Mapped[Optional[str]] = mapped_column(Text)
    channel_username: Mapped[Optional[str]] = mapped_column(String(255))
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    note: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="idea")  # idea|planned|in_progress|done

    project: Mapped["Project"] = relationship(back_populates="ideas")
    topic: Mapped[Optional["Topic"]] = relationship()
    topic_item: Mapped[Optional["TopicItem"]] = relationship()

class Channel(TimestampMixin, Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    invite_link: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text)
    is_private: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    polling_status: Mapped[Optional[str]] = mapped_column(String(32))

    messages: Mapped[list["MessageRaw"]] = relationship(back_populates="channel")


class MessageRaw(TimestampMixin, Base):
    __tablename__ = "messages_raw"
    __table_args__ = (UniqueConstraint("channel_id", "msg_id", name="uq_messages_channel_msg"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    msg_id: Mapped[int] = mapped_column(BigInteger)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[Optional[str]] = mapped_column(Text)
    attachments: Mapped[Optional[dict]] = mapped_column(JSONB)
    features: Mapped[Optional[dict]] = mapped_column(JSONB)
    hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    channel: Mapped["Channel"] = relationship(back_populates="messages")
    events: Mapped[list["Event"]] = relationship(back_populates="source_message")


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(64))

    location_text: Mapped[Optional[str]] = mapped_column(Text)
    latitude: Mapped[Optional[float]] = mapped_column()
    longitude: Mapped[Optional[float]] = mapped_column()
    city: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    venue: Mapped[Optional[str]] = mapped_column(String(256))

    price_min: Mapped[Optional[float]] = mapped_column()
    price_max: Mapped[Optional[float]] = mapped_column()
    currency: Mapped[Optional[str]] = mapped_column(String(8))
    is_free: Mapped[bool] = mapped_column(default=False, nullable=False)

    category: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSONB)

    source_channel_id: Mapped[Optional[int]] = mapped_column(ForeignKey("channels.id"))
    source_msg_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    source_url: Mapped[Optional[str]] = mapped_column(Text)

    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    relevance_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    raw_text: Mapped[str] = mapped_column(Text)

    source_message_id: Mapped[Optional[int]] = mapped_column(ForeignKey("messages_raw.id"))
    source_message: Mapped[Optional["MessageRaw"]] = relationship(back_populates="events")


