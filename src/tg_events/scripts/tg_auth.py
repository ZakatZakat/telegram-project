from __future__ import annotations

import asyncio
from getpass import getpass
from typing import Optional

from telethon.errors import SessionPasswordNeededError

from tg_events.ingest.telethon_client import build_client


async def _main(phone: Optional[str] = None) -> None:
    """Interactive one-time Telethon authorization to create session file."""
    client = build_client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            phone_number = phone or input("Enter phone number (international): ").strip()
            await client.send_code_request(phone_number)
            code = input("Enter code: ").strip()
            try:
                await client.sign_in(phone=phone_number, code=code)
            except SessionPasswordNeededError:
                pw = getpass("Two-step password: ")
                await client.sign_in(password=pw)
        print("Authorization OK. Session saved.")
    finally:
        await client.disconnect()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()


