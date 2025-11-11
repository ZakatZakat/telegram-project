from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal, Optional, Sequence

from telethon.tl import types as tl
from telethon.utils import get_display_name

from tg_events.ingest.telethon_client import build_client


@dataclass
class Post:
    id: int
    date: str
    text: str
    views: Optional[int]
    forwards: Optional[int]
    replies: Optional[int]
    username: Optional[str]
    channel_id: Optional[int]
    channel_title: Optional[str]
    media_kind: Optional[str]
    media_paths: Optional[Sequence[str]] = None


def _coerce_channel_arg(arg: str) -> object:
    arg = arg.strip()
    if arg.startswith("@"):
        return arg
    if arg.isdigit():
        return tl.PeerChannel(int(arg))
    return arg


def _fit_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid date format: {s}")


async def dump_channel(
    *,
    channel: str,
    limit: int,
    from_dt: Optional[datetime],
    to_dt: Optional[datetime],
    media_dir: Optional[Path] = None,
    media_types: Literal["photos", "all"] = "photos",
) -> Iterable[Post]:
    client = build_client()
    await client.connect()
    try:
        entity = await client.get_entity(_coerce_channel_arg(channel))
        async for m in client.iter_messages(entity, limit=limit, reverse=True):
            if not m or m.id is None or m.date is None:
                continue
            if from_dt and m.date < from_dt:
                continue
            if to_dt and m.date > to_dt:
                continue
            chan = m.peer_id
            username = getattr(entity, "username", None)
            title = get_display_name(entity)
            media_kind = type(m.media).__name__ if m.media is not None else None
            saved_paths: list[str] = []
            if media_dir is not None:
                media_dir.mkdir(parents=True, exist_ok=True)
                should_download = False
                if getattr(m, "photo", None) is not None:
                    should_download = True
                elif media_types == "all" and m.media is not None:
                    should_download = True
                if should_download:
                    # Telethon will choose filename/extension; prefix with channel/id for uniqueness.
                    base = f"{username or getattr(entity, 'id', 'chan')}_{m.id}"
                    path = await client.download_media(m, file=str(media_dir / base))
                    if path:
                        saved_paths.append(str(path))
            yield Post(
                id=int(m.id),
                date=m.date.isoformat(),
                text=m.message or "",
                views=getattr(m, "views", None),
                forwards=getattr(m, "forwards", None),
                replies=(m.replies.replies if getattr(m, "replies", None) else None),
                username=username,
                channel_id=getattr(entity, "id", None),
                channel_title=title,
                media_kind=media_kind,
                media_paths=saved_paths or None,
            )
    finally:
        await client.disconnect()


def _write_jsonl(path: Path, posts: Iterable[Post]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")


def _write_csv(path: Path, posts: Iterable[Post]) -> None:
    rows = list(posts)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump Telegram channel posts.")
    parser.add_argument("channel", help="Channel username (@name) or numeric id (e.g. 2448500938)")
    parser.add_argument("--limit", type=int, default=1000, help="Max messages to fetch")
    parser.add_argument("--from", dest="from_dt", type=str, default=None, help="From date (YYYY-MM-DD or ISO)")
    parser.add_argument("--to", dest="to_dt", type=str, default=None, help="To date (YYYY-MM-DD or ISO)")
    parser.add_argument("--jsonl", type=Path, default=None, help="Write JSONL to path")
    parser.add_argument("--csv", type=Path, default=None, help="Write CSV to path")
    parser.add_argument("--media-dir", type=Path, default=None, help="Download media to directory")
    parser.add_argument(
        "--media-types",
        type=str,
        choices=["photos", "all"],
        default="photos",
        help="What media to download (default: photos only)",
    )
    parser.add_argument(
        "--print-text",
        action="store_true",
        help="Print post text bodies to stdout",
    )
    args = parser.parse_args()

    from_dt = _fit_date(args.from_dt)
    to_dt = _fit_date(args.to_dt)
    async def _collect() -> list[Post]:
        return [
            p
            async for p in dump_channel(
                channel=args.channel,
                limit=args.limit,
                from_dt=from_dt,
                to_dt=to_dt,
                media_dir=args.media_dir,
                media_types=args.media_types,  # type: ignore[arg-type]
            )
        ]
    posts = asyncio.run(_collect())

    if args.jsonl:
        _write_jsonl(args.jsonl, posts)
        print(f"Wrote {len(posts)} posts to {args.jsonl}")
    if args.csv:
        _write_csv(args.csv, posts)
        print(f"Wrote {len(posts)} posts to {args.csv}")
    if not args.jsonl and not args.csv:
        for p in posts:
            print(f"{p.id} {p.date} views={p.views or 0} text_len={len(p.text)} media={len(p.media_paths or [])}")
            if args.print_text and p.text:
                print("---")
                print(p.text)


if __name__ == "__main__":
    main()


