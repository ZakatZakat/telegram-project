from __future__ import annotations

import asyncio
from typing import Optional

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_events.config import get_settings
from tg_events.models import AiComment, MessageRaw


_sem = asyncio.Semaphore(get_settings().ai_max_concurrency)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _build_client() -> OpenAI:
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=s.openai_api_key)


def generate_comment_sync(text: str, *, model: Optional[str] = None, max_chars: int = 800) -> str:
    s = get_settings()
    client = _build_client()
    prompt = (
        "You are an assistant that briefly comments on a Telegram post.\n"
        "Return 1-2 sentences: concise, factual, no emojis, no hashtags.\n"
        "If the text is not in the target language, still summarize concisely.\n\n"
        f"Post:\n{text}"
    )
    m = model or s.ai_model
    resp = client.chat.completions.create(
        model=m,
        messages=[
            {"role": "system", "content": "You summarize and comment briefly."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=200,
    )
    out = (resp.choices[0].message.content or "").strip()
    return _truncate_text(out, max_chars)


async def comment_message(session: AsyncSession, message_id: int, *, model: Optional[str] = None) -> AiComment:
    s = get_settings()
    mdl = model or s.ai_model
    async with _sem:
        # Check existing
        existing = await session.execute(
            select(AiComment).where(AiComment.message_id == message_id, AiComment.model == mdl)
        )
        found = existing.scalar_one_or_none()
        if found:
            return found

        msg_row = await session.execute(select(MessageRaw).where(MessageRaw.id == message_id))
        msg = msg_row.scalar_one_or_none()
        if not msg:
            raise ValueError(f"MessageRaw {message_id} not found")
        text = (msg.text or "").strip()
        if not text:
            text = "(no text)"

        comment = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generate_comment_sync(_truncate_text(text, s.ai_comment_max_chars), model=mdl)
        )

        rec = AiComment(message_id=message_id, model=mdl, comment_text=comment)
        session.add(rec)
        await session.commit()
        await session.refresh(rec)
        return rec


