from __future__ import annotations

import sys
from typing import Any

from openai import OpenAI
from tg_events.config import get_settings


def main(argv: list[str]) -> int:
    s = get_settings()
    if not s.openai_api_key:
        print("OPENAI_API_KEY is not set")
        return 2
    client = OpenAI(api_key=s.openai_api_key)

    text = " ".join(argv).strip() if argv else "Скажи 'ОК' одним коротким предложением."
    model = s.ai_model or "gpt-5-nano"

    print(f"Model: {model}")
    print("Making Chat Completions call…")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Отвечай кратко и по делу, 1 короткое предложение."},
            {"role": "user", "content": text},
        ],
        # GPT-5 requires this param name; do not send temperature
        max_completion_tokens=200,
        reasoning={"effort": "low"},
    )
    choice = resp.choices[0]
    finish = getattr(choice, "finish_reason", None)
    content = choice.message.content if choice and choice.message else ""
    print(f"finish_reason: {finish}")
    print(f"content: {content!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


