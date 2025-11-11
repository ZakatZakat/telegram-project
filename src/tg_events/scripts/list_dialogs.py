from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Iterable, List, Literal, Optional

from telethon.tl.types import Channel as TlChannel
from telethon.tl.types import Chat as TlChat
from telethon.tl.types import User as TlUser
from telethon.utils import get_display_name

from tg_events.ingest.telethon_client import build_client


DialogKind = Literal["channel", "supergroup", "group", "user", "unknown"]
OnlyFilter = Literal["all", "channels", "groups", "private"]


@dataclass
class DialogInfo:
    id: int
    kind: DialogKind
    name: str
    username: Optional[str]


def _detect_kind(entity: object) -> DialogKind:
    if isinstance(entity, TlChannel):
        if getattr(entity, "broadcast", False):
            return "channel"
        if getattr(entity, "megagroup", False):
            return "supergroup"
        return "channel"
    if isinstance(entity, TlChat):
        return "group"
    if isinstance(entity, TlUser):
        return "user"
    return "unknown"


def _only_match(kind: DialogKind, only: OnlyFilter) -> bool:
    if only == "all":
        return True
    if only == "channels":
        return kind in ("channel",)
    if only == "groups":
        return kind in ("group", "supergroup")
    if only == "private":
        return kind == "user"
    return True


async def list_dialogs(
    *, limit: int, only: OnlyFilter, query: Optional[str]
) -> List[DialogInfo]:
    client = build_client()
    await client.connect()
    try:
        items: list[DialogInfo] = []
        async for d in client.iter_dialogs(limit=limit):
            e = d.entity
            kind = _detect_kind(e)
            if not _only_match(kind, only):
                continue
            name = get_display_name(e)
            username = getattr(e, "username", None)
            if query:
                needle = query.lower()
                haystack = " ".join(
                    x for x in [name or "", username or ""] if x
                ).lower()
                if needle not in haystack:
                    continue
            dialog_id = getattr(e, "id", None)
            if isinstance(dialog_id, int):
                items.append(
                    DialogInfo(
                        id=dialog_id,
                        kind=kind,
                        name=name or "",
                        username=username,
                    )
                )
        return items
    finally:
        await client.disconnect()


def _print_table(rows: Iterable[DialogInfo]) -> None:
    data = list(rows)
    if not data:
        print("No dialogs found.")
        return
    name_w = max(len(x.name) for x in data)
    kind_w = max(len(x.kind) for x in data)
    user_w = max(len(x.username or "") for x in data)
    header = f"{'ID':>12}  {'KIND':<{kind_w}}  {'USERNAME':<{user_w}}  {'NAME':<{name_w}}"
    print(header)
    print("-" * len(header))
    for d in data:
        print(
            f"{d.id:>12}  {d.kind:<{kind_w}}  {(d.username or ''):<{user_w}}  {d.name:<{name_w}}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List Telegram dialogs/channels from your authorized session."
    )
    parser.add_argument("--limit", type=int, default=500, help="Max dialogs to fetch")
    parser.add_argument(
        "--only",
        type=str,
        choices=["all", "channels", "groups", "private"],
        default="all",
        help="Filter by dialog type",
    )
    parser.add_argument(
        "-q", "--query", type=str, default=None, help="Substring filter over name/username"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output JSON array instead of table"
    )
    args = parser.parse_args()

    items = asyncio.run(
        list_dialogs(limit=args.limit, only=args.only, query=args.query)
    )
    if args.json:
        print(json.dumps([asdict(x) for x in items], ensure_ascii=False, indent=2))
    else:
        _print_table(items)


if __name__ == "__main__":
    main()


