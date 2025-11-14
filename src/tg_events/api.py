import asyncio
from pathlib import Path
import logging
from typing import List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.staticfiles import StaticFiles

from tg_events.db import SessionLocal, get_session
from tg_events.config import get_settings
from tg_events.ingest.service import ingest_channels
from tg_events.repositories.miniapp_queries import list_recent_messages, list_forward_usernames
from tg_events.ingest.telethon_client import build_client, open_client
from telethon.utils import get_display_name
from telethon.tl.types import Channel as TlChannel, User as TlUser
from tg_events.ai.commenter import comment_message, get_prompt_template, set_prompt_template
from sqlalchemy import delete, select
from tg_events.models import AiComment, Channel, MessageRaw, Event


settings = get_settings()
app = FastAPI(title=settings.app_name)
logger = logging.getLogger("tg_events.api")
cancel_generation: bool = False
current_generation_task: asyncio.Task | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class IngestRequest(BaseModel):
    """Request to trigger ingestion."""

    channels: List[str]
    limit: Optional[int] = 1000
    force_media: Optional[bool] = False


@app.post("/ingest")
async def ingest(req: IngestRequest, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    return await ingest_channels(
        session,
        req.channels,
        limit=req.limit or 1000,
        update_existing_media=bool(req.force_media),
    )


class MiniappPostsResponse(BaseModel):
    items: List[dict]


@app.get("/miniapp/api/posts", response_model=MiniappPostsResponse)
async def miniapp_posts(
    session: AsyncSession = Depends(get_session),
    limit: int = 500,
    username: Optional[str] = None,
    channel_id: Optional[int] = None,
    fwd_username: Optional[str] = None,
) -> MiniappPostsResponse:
    items = await list_recent_messages(
        session, limit=limit, channel_username=username, channel_tg_id=channel_id, fwd_username=fwd_username
    )
    return MiniappPostsResponse(items=items)
class ForwardsResponse(BaseModel):
    items: List[dict]


@app.get("/miniapp/api/forwards", response_model=ForwardsResponse)
async def miniapp_forwards(
    session: AsyncSession = Depends(get_session),
    limit: int = 200,
    username: Optional[str] = None,
    channel_id: Optional[int] = None,
) -> ForwardsResponse:
    items = await list_forward_usernames(
        session, limit=limit, channel_username=username, channel_tg_id=channel_id
    )
    return ForwardsResponse(items=items)


class PromptResponse(BaseModel):
    template: str


class PromptUpdate(BaseModel):
    template: str


@app.get("/miniapp/api/prompt", response_model=PromptResponse)
def get_prompt() -> PromptResponse:
    return PromptResponse(template=get_prompt_template())


@app.put("/miniapp/api/prompt", response_model=PromptResponse)
def update_prompt(req: PromptUpdate) -> PromptResponse:
    set_prompt_template(req.template)
    return PromptResponse(template=get_prompt_template())


# Serve media files
media_dir = Path(settings.media_root)
media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_dir), html=False), name="media")


class ChannelItem(BaseModel):
    id: int
    kind: str
    name: str
    username: Optional[str] = None


class ChannelsResponse(BaseModel):
    items: List[ChannelItem]


@app.get("/miniapp/api/channels", response_model=ChannelsResponse)
async def miniapp_channels(limit: int = 300) -> ChannelsResponse:
    items: list[ChannelItem] = []
    async with open_client() as client:
        try:
            async for d in client.iter_dialogs(limit=limit):
                e = d.entity
                if isinstance(e, TlChannel):
                    kind = "channel" if getattr(e, "broadcast", False) else "supergroup"
                    items.append(
                        ChannelItem(
                            id=int(getattr(e, "id", 0)),
                            kind=kind,
                            name=get_display_name(e) or "",
                            username=getattr(e, "username", None),
                        )
                    )
                elif isinstance(e, TlUser):
                    items.append(
                        ChannelItem(
                            id=int(getattr(e, "id", 0)),
                            kind="user",
                            name=get_display_name(e) or "",
                            username=getattr(e, "username", None),
                        )
                    )
        finally:
            pass
    # sort by name
    items.sort(key=lambda x: (x.username is None, (x.username or x.name or "").lower()))
    return ChannelsResponse(items=items)


class MiniIngestRequest(BaseModel):
    channel: str
    limit: Optional[int] = 500
    force_media: Optional[bool] = True


@app.post("/miniapp/api/ingest")
async def miniapp_ingest(
    req: MiniIngestRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    return await ingest_channels(
        session, [req.channel], limit=req.limit or 500, update_existing_media=bool(req.force_media)
    )

class GenerateCommentsRequest(BaseModel):
    message_ids: List[int]
    model: Optional[str] = None
    # optional scope restriction to a single channel/user
    username: Optional[str] = None
    channel_id: Optional[int] = None


@app.post("/miniapp/api/comments/generate")
async def generate_comments(req: GenerateCommentsRequest) -> dict[str, int]:
    # Process in background to keep UI responsive
    s = get_settings()
    # cap batch size to avoid overload
    ids = list(dict.fromkeys(req.message_ids))
    if not s.openai_api_key:
        logger.warning("OPENAI_API_KEY missing; skip generation", requested=len(req.message_ids))
        return {"accepted": 0}

    # If scope provided, filter message_ids to the chosen channel/user
    if req.username or req.channel_id is not None:
        from sqlalchemy import and_, select
        from tg_events.models import Channel, MessageRaw

        async with SessionLocal() as ses:
            conds = []
            if req.username:
                conds.append(Channel.username == req.username)
            if req.channel_id is not None:
                conds.append(Channel.tg_id == req.channel_id)
            q = (
                select(MessageRaw.id)
                .join(Channel, Channel.id == MessageRaw.channel_id)
                .where(MessageRaw.id.in_(ids))
            )
            if conds:
                from sqlalchemy import and_ as _and
                q = q.where(_and(*conds))
            rows = (await ses.execute(q)).scalars().all()
            ids = list(dict.fromkeys(rows))

    async def _run() -> None:
        global cancel_generation
        # Sequential processing with ~1s delay between items
        # Reset cancel flag at the beginning of a new run
        cancel_generation = False
        for mid in ids:
            if cancel_generation:
                logger.info("generation cancelled by user")
                break
            async with SessionLocal() as ses:
                try:
                    await comment_message(ses, mid, model=req.model or s.ai_model)
                except Exception as e:
                    logger.exception("generate_comment failed", extra={"message_id": mid, "error": str(e)})
            await asyncio.sleep(1.0)

    # Start as a cancellable asyncio task (not BackgroundTasks)
    global current_generation_task
    try:
        if current_generation_task and not current_generation_task.done():
            current_generation_task.cancel()
    except Exception:
        pass
    current_generation_task = asyncio.create_task(_run())
    return {"accepted": len(ids)}


class StopResponse(BaseModel):
    status: str


@app.post("/miniapp/api/comments/stop", response_model=StopResponse)
def stop_generation() -> StopResponse:
    global cancel_generation, current_generation_task
    cancel_generation = True
    try:
        if current_generation_task and not current_generation_task.done():
            current_generation_task.cancel()
    except Exception:
        pass
    return StopResponse(status="stopping")


class DeleteCommentsRequest(BaseModel):
    # delete by explicit messages, or by scope, or everything if neither provided
    message_ids: Optional[List[int]] = None
    username: Optional[str] = None
    channel_id: Optional[int] = None


@app.delete("/miniapp/api/comments")
async def delete_comments(req: DeleteCommentsRequest) -> dict[str, int]:
    deleted = 0
    async with SessionLocal() as ses:
        if req.message_ids:
            stmt = delete(AiComment).where(AiComment.message_id.in_(req.message_ids))
            res = await ses.execute(stmt)
            deleted = res.rowcount or 0
        elif req.username or req.channel_id is not None:
            conds = []
            if req.username:
                conds.append(Channel.username == req.username)
            if req.channel_id is not None:
                conds.append(Channel.tg_id == req.channel_id)
            sub = (
                select(MessageRaw.id)
                .join(Channel, Channel.id == MessageRaw.channel_id)
            )
            if conds:
                from sqlalchemy import and_ as _and
                sub = sub.where(_and(*conds))
            stmt = delete(AiComment).where(AiComment.message_id.in_(sub))
            res = await ses.execute(stmt)
            deleted = res.rowcount or 0
        else:
            # delete all comments
            res = await ses.execute(delete(AiComment))
            deleted = res.rowcount or 0
        await ses.commit()
    return {"deleted": int(deleted)}


class DeletePostsRequest(BaseModel):
    message_ids: List[int]
    delete_media: Optional[bool] = True


@app.delete("/miniapp/api/posts")
async def delete_posts(req: DeletePostsRequest) -> dict[str, int]:
    ids = list(dict.fromkeys(req.message_ids))
    if not ids:
        return {"deleted": 0}
    media_deleted = 0
    async with SessionLocal() as ses:
        # delete dependent events first to avoid FK restriction
        await ses.execute(delete(Event).where(Event.source_message_id.in_(ids)))
        if req.delete_media:
            rows = await ses.execute(select(MessageRaw.id, MessageRaw.attachments).where(MessageRaw.id.in_(ids)))
            for _mid, atts in rows.all():
                media = None
                if isinstance(atts, dict):
                    media = atts.get("media")
                if isinstance(media, list) and media:
                    for it in media:
                        p = None
                        if isinstance(it, dict):
                            p = it.get("path")
                        elif isinstance(it, str):
                            p = it
                        if p:
                            try:
                                f = Path(settings.media_root) / p
                                if f.is_file():
                                    f.unlink(missing_ok=True)
                                    media_deleted += 1
                            except Exception:
                                pass
        res = await ses.execute(delete(MessageRaw).where(MessageRaw.id.in_(ids)))
        await ses.commit()
        return {"deleted": int(res.rowcount or 0), "media_deleted": int(media_deleted)}


class UpdateCommentRequest(BaseModel):
    message_id: int
    text: str
    model: Optional[str] = None


@app.put("/miniapp/api/comments")
async def update_comment(req: UpdateCommentRequest) -> dict[str, int]:
    s = get_settings()
    mdl = req.model or s.ai_model
    async with SessionLocal() as ses:
        # try update existing
        from sqlalchemy import update as sa_update
        res = await ses.execute(
            sa_update(AiComment)
            .where(AiComment.message_id == req.message_id, AiComment.model == mdl)
            .values(comment_text=req.text)
        )
        updated = res.rowcount or 0
        if not updated:
            # create new if absent
            rec = AiComment(message_id=req.message_id, model=mdl, comment_text=req.text)
            ses.add(rec)
            await ses.commit()
            return {"updated": 1}
        await ses.commit()
        return {"updated": int(updated)}

# Serve static Mini App (mounted AFTER API routes so it doesn't shadow /miniapp/api/*)
miniapp_dir = Path(__file__).parent / "miniapp_static"
if miniapp_dir.exists():
    app.mount("/miniapp", StaticFiles(directory=str(miniapp_dir), html=True), name="miniapp")
