from __future__ import annotations

import asyncio
from typing import Optional

import logging
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_events.config import get_settings
from tg_events.models import AiComment, MessageRaw


_sem = asyncio.Semaphore(get_settings().ai_max_concurrency)
logger = logging.getLogger("tg_events.ai.commenter")

def _preview(text: str, limit: int = 400) -> str:
    if not isinstance(text, str):
        return ""
    s = text.replace("\n", "\\n").replace("\r", "\\r")
    return s[:limit] + ("…" if len(s) > limit else "")

def _usage_tokens(obj: object) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        u = getattr(obj, "usage", None)
        if u is None:
            return out
        # Responses API
        for k in ("input_tokens", "output_tokens", "total_tokens"):
            v = getattr(u, k, None)
            if isinstance(v, int):
                out[k] = v
        # Chat Completions naming
        for k in ("prompt_tokens", "completion_tokens"):
            v = getattr(u, k, None)
            if isinstance(v, int):
                out[k] = v
    except Exception:
        pass
    return out

# Default prompt template and runtime-overridable template.
# Use {post} placeholder for the message text.
DEFAULT_PROMPT_TEMPLATE = (
    "You are an assistant that briefly comments on a Telegram post.\n"
    "Return 1-2 sentences: concise, factual, no emojis, no hashtags.\n"
    "If the text is not in the target language, still summarize concisely.\n\n"
    "Post:\n{post}"
)
_prompt_template: str | None = None


def get_prompt_template() -> str:
    return _prompt_template or DEFAULT_PROMPT_TEMPLATE


def set_prompt_template(template: str) -> None:
    global _prompt_template
    _prompt_template = template.strip() if template is not None else None


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _build_client() -> OpenAI:
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=s.openai_api_key)

def _extract_responses_output_text(resp: object) -> str:
    # Preferred property
    out = getattr(resp, "output_text", None)
    if isinstance(out, str) and out.strip():
        return out
    # Fallback for SDK structured output
    try:
        output = getattr(resp, "output", None)
        if output:
            parts: list[str] = []
            for item in output:
                content = getattr(item, "content", None)
                if not content:
                    continue
                for c in content:
                    t = getattr(c, "type", None)
                    # Some SDK versions use "output_text", others just "text"
                    txt = getattr(c, "text", None)
                    if isinstance(txt, str) and txt:
                        parts.append(txt)
                        continue
                    # text as object with .value
                    val = getattr(txt, "value", None) if txt is not None else None
                    if isinstance(val, str) and val:
                        parts.append(val)
                        continue
                    # text as dict {"value": "..."}
                    if isinstance(txt, dict):
                        v = txt.get("value")
                        if isinstance(v, str) and v:
                            parts.append(v)
                    # explicit refusals sometimes carry message/reason
                    refusal = getattr(c, "refusal", None)
                    if isinstance(refusal, str) and refusal:
                        parts.append(refusal)
                    elif isinstance(refusal, dict):
                        msg = refusal.get("message") or refusal.get("reason")
                        if isinstance(msg, str) and msg:
                            parts.append(msg)
            if parts:
                return "\n".join(parts)
    except Exception:
        pass
    return ""

def generate_comment_sync(text: str, *, model: Optional[str] = None, max_chars: int = 800) -> str:
    s = get_settings()
    client = _build_client()
    template = get_prompt_template()
    prompt = template.replace("{post}", text)
    m = model or s.ai_model
    is_gpt5 = str(m).startswith("gpt-5")
    logger.warning(
        "generate_comment_sync:start",
        extra={
            "model": m,
            "is_gpt5": is_gpt5,
            "input_chars": len(prompt),
            "max_chars": max_chars,
            "prompt_preview": _preview(prompt, 260),
        },
    )
    # Use Responses API for GPT‑5 family per latest docs; keep Chat Completions for older models
    if is_gpt5:
        # Use legacy-compatible shape for installed SDK (no 'messages' arg), plus explicit text format
        resp = client.responses.create(
            model=m,
            input=prompt,
            instructions="Summarize and briefly comment in 1-2 sentences. No emojis, no hashtags.",
            max_output_tokens=200,
            reasoning={"effort": "low"},
        )
        # diagnostics about shape for debugging empties
        try:
            has_out_text = bool(getattr(resp, "output_text", None))
            output_seq = getattr(resp, "output", []) or []
            kinds: list[str] = []
            for it in output_seq:
                for cc in getattr(it, "content", []) or []:
                    kinds.append(str(getattr(cc, "type", None)))
            logger.warning(
                "responses.shape has_output_text=%s items=%s content_types=%s usage=%s",
                int(has_out_text),
                len(output_seq),
                ",".join(kinds[:8]),
                _usage_tokens(resp),
            )
        except Exception:
            logger.warning("responses.shape:inspect_failed")
        out_text = _extract_responses_output_text(resp)
        logger.warning(
            "responses.output len=%s preview=%s usage=%s",
            len(out_text or ""),
            _preview(out_text or "", 360),
            _usage_tokens(resp),
        )
    else:
        params = {
            "model": m,
            "messages": [
                {"role": "system", "content": "You summarize and comment briefly."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 200,
        }
        resp = client.chat.completions.create(**params)
        choice0 = resp.choices[0] if getattr(resp, "choices", None) else None
        finish = getattr(choice0, "finish_reason", None)
        out_text = (choice0.message.content or "") if choice0 else ""
        logger.warning(
            "chat.output finish=%s len=%s preview=%s usage=%s",
            str(finish),
            len(out_text or ""),
            _preview(out_text or "", 360),
            _usage_tokens(resp),
        )
    out = (out_text or "").strip()
    logger.warning(
        "generate_comment_sync:done model=%s output_chars=%s empty=%s preview=%s",
        m,
        len(out),
        int(not bool(out)),
        _preview(out, 240),
    )
    return _truncate_text(out, max_chars)


async def comment_message(session: AsyncSession, message_id: int, *, model: Optional[str] = None) -> AiComment:
    s = get_settings()
    mdl = model or s.ai_model
    logger.warning("comment_message:start", extra={"message_id": message_id, "model": mdl})
    async with _sem:
        # Check existing
        existing = await session.execute(
            select(AiComment).where(AiComment.message_id == message_id, AiComment.model == mdl)
        )
        found = existing.scalar_one_or_none()
        if found:
            logger.warning("comment_message:exists", extra={"message_id": message_id, "model": mdl})
            return found

        msg_row = await session.execute(select(MessageRaw).where(MessageRaw.id == message_id))
        msg = msg_row.scalar_one_or_none()
        if not msg:
            raise ValueError(f"MessageRaw {message_id} not found")
        text = (msg.text or "").strip()
        if not text:
            text = "(no text)"
        logger.warning(
            "comment_message:invoke",
            extra={"message_id": message_id, "model": mdl, "text_chars": len(text)},
        )

        comment = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generate_comment_sync(_truncate_text(text, s.ai_comment_max_chars), model=mdl)
        )

        rec = AiComment(message_id=message_id, model=mdl, comment_text=comment)
        session.add(rec)
        await session.commit()
        await session.refresh(rec)
        logger.warning(
            "comment_message:stored",
            extra={"message_id": message_id, "model": mdl, "comment_chars": len(comment or "")},
        )
        return rec


