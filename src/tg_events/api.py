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
from sqlalchemy import delete, select, and_, or_
from tg_events.models import AiComment, Channel, MessageRaw, Event, Topic, TopicItem, Project, ProjectIdea


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
    model: Optional[str] = None,
) -> MiniappPostsResponse:
    items = await list_recent_messages(
        session,
        limit=limit,
        channel_username=username,
        channel_tg_id=channel_id,
        fwd_username=fwd_username,
        model=model,
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

    logger.warning("comments.generate:schedule", extra={"requested": len(req.message_ids or []), "resolved_ids": len(ids)})
    async def _run() -> None:
        global cancel_generation
        # Sequential processing with ~1s delay between items
        # Reset cancel flag at the beginning of a new run
        cancel_generation = False
        for mid in ids:
            if cancel_generation:
                logger.warning("generation cancelled by user")
                break
            async with SessionLocal() as ses:
                try:
                    logger.warning("comments.generate:item:start", extra={"message_id": mid})
                    await comment_message(ses, mid, model=req.model or s.ai_model)
                    logger.warning("comments.generate:item:done", extra={"message_id": mid})
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


class GenerateOverrideItem(BaseModel):
    message_id: int
    text: str
    model: Optional[str] = None


class GenerateOverrideRequest(BaseModel):
    items: List[GenerateOverrideItem]
    model: Optional[str] = None


@app.post("/miniapp/api/comments/generate_override")
async def generate_comments_override(req: GenerateOverrideRequest) -> dict[str, int]:
    """Generate comments using provided text overrides for specific message_ids."""
    s = get_settings()
    if not s.openai_api_key:
        logger.warning("OPENAI_API_KEY missing; skip override generation", requested=len(req.items))
        return {"accepted": 0}

    global cancel_generation, current_generation_task
    try:
        if current_generation_task and not current_generation_task.done():
            current_generation_task.cancel()
    except Exception:
        pass
    cancel_generation = False

    logger.warning("comments.generate_override:schedule", extra={"requested": len(req.items or [])})
    async def _run_override() -> None:
        from sqlalchemy import update as sa_update
        from tg_events.models import AiComment
        for it in req.items:
            if cancel_generation:
                break
            text = (it.text or "").strip()
            if not text:
                logger.warning("comments.generate_override:skip_empty", extra={"message_id": it.message_id})
                continue
            # run sync generator in executor
            loop = asyncio.get_running_loop()
            from tg_events.ai.commenter import generate_comment_sync

            try:
                mdl = it.model or req.model or s.ai_model
                logger.warning("comments.generate_override:item:start", extra={"message_id": it.message_id, "model": mdl})
                comment = await loop.run_in_executor(
                    None, lambda: generate_comment_sync(text, model=mdl)
                )
                async with SessionLocal() as ses:
                    # upsert: try update, if 0 rows affected → insert
                    res = await ses.execute(
                        sa_update(AiComment)
                        .where(
                            AiComment.message_id == it.message_id,
                            AiComment.model == mdl,
                        )
                        .values(comment_text=comment)
                    )
                    if (res.rowcount or 0) == 0:
                        rec = AiComment(
                            message_id=it.message_id,
                            model=mdl,
                            comment_text=comment,
                        )
                        ses.add(rec)
                    await ses.commit()
                logger.warning("comments.generate_override:item:stored", extra={"message_id": it.message_id, "chars": len(comment or "")})
            except Exception as e:
                logger.exception("generate_override failed", extra={"message_id": it.message_id, "error": str(e)})
            await asyncio.sleep(0)  # yield control

    current_generation_task = asyncio.create_task(_run_override())
    return {"accepted": len(req.items)}


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

# Topics API
class TopicItemOut(BaseModel):
    id: int
    message_id: Optional[int] = None
    channel_tg_id: Optional[int] = None
    msg_id: Optional[int] = None
    post_text: Optional[str] = None
    comment_text: Optional[str] = None
    channel_username: Optional[str] = None
    source_url: Optional[str] = None


class TopicOut(BaseModel):
    id: int
    name: str
    message_ids: list[int]
    items: list[TopicItemOut] = []


class TopicsResponse(BaseModel):
    items: list[TopicOut]


class TopicCreate(BaseModel):
    name: str


class TopicItemAdd(BaseModel):
    topic_id: int
    message_id: int
    channel_tg_id: Optional[int] = None
    msg_id: Optional[int] = None
    post_text: Optional[str] = None
    comment_text: Optional[str] = None
    channel_username: Optional[str] = None
    source_url: Optional[str] = None


@app.get("/miniapp/api/topics", response_model=TopicsResponse)
async def list_topics(session: AsyncSession = Depends(get_session)) -> TopicsResponse:
    rows = (await session.execute(select(Topic.id, Topic.name))).all()
    items: list[TopicOut] = []
    if rows:
        for tid, name in rows:
            # resolve current message_ids via stable key if present
            ids_q = (
                select(MessageRaw.id)
                .join(Channel, Channel.id == MessageRaw.channel_id)
                .join(
                    TopicItem,
                    (TopicItem.topic_id == tid)
                    & (TopicItem.msg_id == MessageRaw.msg_id)
                    & (TopicItem.channel_tg_id == Channel.tg_id),
                )
            )
            msg_ids = (await session.execute(ids_q)).scalars().all()
            # also include snapshot items
            snap_rows = (
                await session.execute(
                    select(
                        TopicItem.id,
                        TopicItem.message_id,
                        TopicItem.channel_tg_id,
                        TopicItem.msg_id,
                        TopicItem.post_text,
                        TopicItem.comment_text,
                        TopicItem.channel_username,
                        TopicItem.source_url,
                    ).where(TopicItem.topic_id == tid)
                )
            ).all()
            item_objs = [
                TopicItemOut(
                    id=int(r[0]),
                    message_id=r[1],
                    channel_tg_id=r[2],
                    msg_id=r[3],
                    post_text=r[4],
                    comment_text=r[5],
                    channel_username=r[6],
                    source_url=r[7],
                )
                for r in snap_rows
            ]
            items.append(TopicOut(id=int(tid), name=name, message_ids=[int(x) for x in msg_ids], items=item_objs))
    return TopicsResponse(items=items)


@app.post("/miniapp/api/topics", response_model=TopicOut)
async def create_topic(req: TopicCreate, session: AsyncSession = Depends(get_session)) -> TopicOut:
    name = (req.name or "").strip()
    if not name:
        raise ValueError("name required")
    # try find existing
    row = (await session.execute(select(Topic).where(Topic.name == name))).scalar_one_or_none()
    if row is None:
        row = Topic(name=name)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    # load items
    ids = (await session.execute(select(TopicItem.message_id).where(TopicItem.topic_id == row.id))).scalars().all()
    return TopicOut(id=int(row.id), name=row.name, message_ids=[int(x) for x in ids])


class TopicItemRemove(BaseModel):
    topic_id: Optional[int] = None
    message_id: Optional[int] = None
    channel_tg_id: Optional[int] = None
    msg_id: Optional[int] = None
    topic_item_id: Optional[int] = None


@app.delete("/miniapp/api/topics/remove")
async def remove_topic_item(req: TopicItemRemove, session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    logger.info(
        "topics_remove request",
        extra={
            "topic_id": req.topic_id,
            "message_id": req.message_id,
            "topic_item_id": req.topic_item_id,
            "channel_tg_id": req.channel_tg_id,
            "msg_id": req.msg_id,
        },
    )
    if req.topic_item_id is not None:
        cond = (TopicItem.id == req.topic_item_id)
        if req.topic_id is not None:
            cond = and_(cond, TopicItem.topic_id == req.topic_id)
        res = await session.execute(delete(TopicItem).where(cond))
        await session.commit()
        deleted = int(res.rowcount or 0)
        logger.info("topics_remove direct by topic_item_id", extra={"deleted": deleted})
        return {"deleted": deleted}
    if req.topic_id is None:
        raise ValueError("topic_id required when topic_item_id not provided")
    if req.topic_item_id is None and req.message_id is None and (req.msg_id is None or req.channel_tg_id is None):
        raise ValueError("topic_item_id or message_id/stable key required")
    msg_id_val = req.msg_id
    tg_id_val = req.channel_tg_id
    if msg_id_val is None or tg_id_val is None:
        sub = (
            select(MessageRaw.msg_id, Channel.tg_id)
            .join(Channel, Channel.id == MessageRaw.channel_id)
            .where(MessageRaw.id == req.message_id)
        )
        row = (await session.execute(sub)).first()
        if row is not None:
            msg_id_val, tg_id_val = row
    conds = []
    if req.message_id is not None:
        conds.append(TopicItem.message_id == req.message_id)
    if msg_id_val is not None and tg_id_val is not None:
        conds.append(and_(TopicItem.msg_id == msg_id_val, TopicItem.channel_tg_id == tg_id_val))
    if not conds:
        raise ValueError("unable to resolve message identifier for deletion")
    res = await session.execute(
        delete(TopicItem).where(TopicItem.topic_id == req.topic_id).where(or_(*conds))
    )
    deleted = int(res.rowcount or 0)
    await session.commit()
    logger.info(
        "topics_remove summary",
        extra={
            "topic_id": req.topic_id,
            "message_id": req.message_id,
            "topic_item_id": req.topic_item_id,
            "channel_tg_id": tg_id_val,
            "msg_id": msg_id_val,
            "deleted": deleted,
        },
    )
    return {"deleted": deleted}


@app.delete("/miniapp/api/topics/{topic_id}")
async def delete_topic(topic_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    res = await session.execute(delete(Topic).where(Topic.id == topic_id))
    await session.commit()
    return {"deleted": int(res.rowcount or 0)}


@app.post("/miniapp/api/topics/add")
async def add_topic_item(req: TopicItemAdd, session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    # idempotent upsert by (topic_id, channel_tg_id, msg_id). If those are not provided, fall back to message_id.
    if req.channel_tg_id is not None and req.msg_id is not None:
        exists = (
            await session.execute(
                select(TopicItem.id).where(
                    TopicItem.topic_id == req.topic_id,
                    TopicItem.channel_tg_id == req.channel_tg_id,
                    TopicItem.msg_id == req.msg_id,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                TopicItem(
                    topic_id=req.topic_id,
                    message_id=req.message_id,
                    channel_tg_id=req.channel_tg_id,
                    msg_id=req.msg_id,
                    post_text=(req.post_text or None),
                    comment_text=(req.comment_text or None),
                    channel_username=(req.channel_username or None),
                    source_url=(req.source_url or None),
                )
            )
        else:
            # update snapshot on re-add
            from sqlalchemy import update as sa_update
            await session.execute(
                sa_update(TopicItem)
                .where(TopicItem.id == exists)
                .values(
                    message_id=req.message_id,
                    post_text=(req.post_text or None),
                    comment_text=(req.comment_text or None),
                    channel_username=(req.channel_username or None),
                    source_url=(req.source_url or None),
                )
            )
        await session.commit()
        return {"added": 1}
    # fallback using message_id only
    m = (await session.execute(select(MessageRaw.id).where(MessageRaw.id == req.message_id))).scalar_one_or_none()
    if m is None:
        return {"added": 0}
    exists = (
        await session.execute(
            select(TopicItem.id).where(TopicItem.topic_id == req.topic_id, TopicItem.message_id == req.message_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(
            TopicItem(
                topic_id=req.topic_id,
                message_id=req.message_id,
                post_text=(req.post_text or None),
                comment_text=(req.comment_text or None),
            )
        )
    else:
        from sqlalchemy import update as sa_update
        await session.execute(
            sa_update(TopicItem)
            .where(TopicItem.id == exists)
            .values(post_text=(req.post_text or None), comment_text=(req.comment_text or None))
        )
    await session.commit()
    return {"added": 1}

# Projects API
class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: str
    ideas_count: int = 0


class ProjectsResponse(BaseModel):
    items: list[ProjectOut]


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


@app.get("/miniapp/api/projects", response_model=ProjectsResponse)
async def list_projects(session: AsyncSession = Depends(get_session)) -> ProjectsResponse:
    rows = (await session.execute(select(Project.id, Project.name, Project.description, Project.status))).all()
    out: list[ProjectOut] = []
    for pid, name, desc, status in rows:
        ids = (await session.execute(select(ProjectIdea.id).where(ProjectIdea.project_id == pid))).scalars().all()
        out.append(ProjectOut(id=int(pid), name=name, description=desc, status=status, ideas_count=len(ids)))
    return ProjectsResponse(items=out)


@app.post("/miniapp/api/projects", response_model=ProjectOut)
async def create_project(req: ProjectCreate, session: AsyncSession = Depends(get_session)) -> ProjectOut:
    name = (req.name or "").strip()
    if not name:
        raise ValueError("name required")
    row = (await session.execute(select(Project).where(Project.name == name))).scalar_one_or_none()
    if row is None:
        row = Project(name=name, description=req.description or None)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    ids = (await session.execute(select(ProjectIdea.id).where(ProjectIdea.project_id == row.id))).scalars().all()
    return ProjectOut(id=int(row.id), name=row.name, description=row.description, status=row.status, ideas_count=len(ids))


class ProjectIdeaAdd(BaseModel):
    project_id: int
    topic_id: Optional[int] = None
    topic_item_id: Optional[int] = None
    channel_tg_id: Optional[int] = None
    msg_id: Optional[int] = None
    post_text: Optional[str] = None
    comment_text: Optional[str] = None
    channel_username: Optional[str] = None
    source_url: Optional[str] = None
    note: Optional[str] = None


@app.post("/miniapp/api/projects/ideas")
async def add_project_idea(req: ProjectIdeaAdd, session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    idea = ProjectIdea(
        project_id=req.project_id,
        topic_id=req.topic_id,
        topic_item_id=req.topic_item_id,
        channel_tg_id=req.channel_tg_id,
        msg_id=req.msg_id,
        post_text=req.post_text,
        comment_text=req.comment_text,
        channel_username=req.channel_username,
        source_url=req.source_url,
        note=req.note,
    )
    session.add(idea)
    await session.commit()
    return {"added": 1}


class ProjectIdeaUpdate(BaseModel):
    note: Optional[str] = None
    status: Optional[str] = None


@app.put("/miniapp/api/projects/{project_id}/ideas/{idea_id}")
async def update_project_idea(
    project_id: int, idea_id: int, req: ProjectIdeaUpdate, session: AsyncSession = Depends(get_session)
) -> dict[str, int]:
    from sqlalchemy import update as sa_update
    res = await session.execute(
        sa_update(ProjectIdea)
        .where(ProjectIdea.id == idea_id, ProjectIdea.project_id == project_id)
        .values(
            note=req.note if req.note is not None else ProjectIdea.note,
            status=req.status if req.status is not None else ProjectIdea.status,
        )
    )
    await session.commit()
    return {"updated": int(res.rowcount or 0)}


@app.delete("/miniapp/api/projects/{project_id}/ideas/{idea_id}")
async def delete_project_idea(project_id: int, idea_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    res = await session.execute(delete(ProjectIdea).where(ProjectIdea.id == idea_id, ProjectIdea.project_id == project_id))
    await session.commit()
    return {"deleted": int(res.rowcount or 0)}

# Serve static Mini App (mounted AFTER API routes so it doesn't shadow /miniapp/api/*)
miniapp_dir = Path(__file__).parent / "miniapp_static"
if miniapp_dir.exists():
    app.mount("/miniapp", StaticFiles(directory=str(miniapp_dir), html=True), name="miniapp")
