from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, List

from tg_events.db import SessionLocal
from tg_events.repositories.miniapp_queries import list_recent_messages


async def run(args: argparse.Namespace) -> int:
    async with SessionLocal() as ses:
        items: List[Dict[str, Any]] = await list_recent_messages(
            ses,
            limit=args.limit,
            channel_username=args.username,
            channel_tg_id=args.channel_id,
            fwd_username=args.fwd_username,
            model=None,
        )
    q = (args.substr or "").strip()
    print(f"Fetched: {len(items)}, query: {q!r}")
    matches = []
    for it in items:
        text = (it.get("text") or "")
        if q and q in text:
            matches.append(
                {
                    "id": it["id"],
                    "msg_id": it.get("msg_id"),
                    "date": it.get("date"),
                    "channel_tg_id": it.get("channel_tg_id"),
                    "first_line": text.split("\n", 1)[0][:200],
                }
            )
    print(f"Matches: {len(matches)}")
    for m in matches:
        print(
            f"id={m['id']} msg_id={m['msg_id']} date={m['date']} tg={m['channel_tg_id']} first='{m['first_line']}'"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Find posts containing substring")
    ap.add_argument("--username", type=str, default=None, help="@username (without @ also ok)")
    ap.add_argument("--channel-id", type=int, default=None)
    ap.add_argument("--fwd-username", type=str, default=None)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--substr", type=str, required=True)
    args = ap.parse_args()
    if args.username and args.username.startswith("@"):
        args.username = args.username[1:]
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())


