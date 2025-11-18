from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

from tg_events.db import SessionLocal
from tg_events.repositories.miniapp_queries import list_recent_messages


def normalize_text(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.split()).strip().lower()


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
    print(f"Fetched: {len(items)}")
    # by id
    ids = [it["id"] for it in items]
    dup_ids = [k for k, v in Counter(ids).items() if v > 1]
    if dup_ids:
        print(f"Duplicate ids: {len(dup_ids)}")
        for i in dup_ids[:20]:
            print("  id", i)
    else:
        print("No duplicate ids.")
    # by (channel_tg_id,msg_id)
    keys: List[Tuple[int | None, int | None]] = [
        (it.get("channel_tg_id"), it.get("msg_id")) for it in items
    ]
    dup_keys = [k for k, v in Counter(keys).items() if v > 1]
    if dup_keys:
        print(f"Duplicate stable keys: {len(dup_keys)}")
        for k in dup_keys[:20]:
            print(" ", k)
    else:
        print("No duplicate stable keys.")
    # by normalized first-line text
    buckets: Dict[str, List[int]] = defaultdict(list)
    for it in items:
        key = normalize_text((it.get("text") or "").split("\n")[0])
        if key:
            buckets[key].append(it["id"])
    noisy = [(k, v) for k, v in buckets.items() if len(v) > 1]
    noisy.sort(key=lambda x: -len(x[1]))
    if noisy:
        print(f"Possible duplicates by first-line text: {len(noisy)}")
        for k, v in noisy[:20]:
            print(f"  '{k[:80]}' → ids={v}")
    else:
        print("No duplicates by text heuristic.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Check duplicates in recent posts")
    ap.add_argument("--username", type=str, default=None, help="@username (without @ also ok)")
    ap.add_argument("--channel-id", type=int, default=None)
    ap.add_argument("--fwd-username", type=str, default=None)
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    if args.username and args.username.startswith("@"):
        args.username = args.username[1:]
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())


