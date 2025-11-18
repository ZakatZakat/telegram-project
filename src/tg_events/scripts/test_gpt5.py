from __future__ import annotations

import json
import sys
from typing import Any, Iterable

from openai import OpenAI

from tg_events.config import get_settings


def _extract_text_from_responses(resp: Any) -> list[str]:
    out: list[str] = []
    txt = getattr(resp, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        out.append(txt)
        return out
    try:
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "type", None)
                if t and str(t).lower().endswith("text"):
                    tx = getattr(c, "text", None)
                    if isinstance(tx, str) and tx:
                        out.append(tx)
                        continue
                    val = getattr(tx, "value", None) if tx is not None else None
                    if isinstance(val, str) and val:
                        out.append(val)
                        continue
                    if isinstance(tx, dict):
                        v = tx.get("value")
                        if isinstance(v, str) and v:
                            out.append(v)
                            continue
                ref = getattr(c, "refusal", None)
                if isinstance(ref, str) and ref:
                    out.append(ref)
                elif isinstance(ref, dict):
                    msg = ref.get("message") or ref.get("reason")
                    if isinstance(msg, str) and msg:
                        out.append(msg)
    except Exception:
        pass
    return out


def _print_kv(title: str, kv: dict[str, Any]) -> None:
    print(f"\n== {title} ==")
    for k, v in kv.items():
        try:
            if isinstance(v, (dict, list, tuple)):
                print(f"{k}: {json.dumps(v, ensure_ascii=False)[:800]}")
            else:
                print(f"{k}: {v}")
        except Exception:
            print(f"{k}: <unserializable>")


def main(argv: list[str]) -> int:
    s = get_settings()
    if not s.openai_api_key:
        print("OPENAI_API_KEY is not set")
        return 2
    client = OpenAI(api_key=s.openai_api_key)

    # Very simple args: optional --model MODEL then text
    model = s.ai_model or "gpt-5-nano"
    args = list(argv)
    if args and args[0] == "--model":
        if len(args) >= 2:
            model = args[1]
            args = args[2:]
    elif args and args[0].startswith("--model="):
        model = args[0].split("=", 1)[1] or model
        args = args[1:]
    text = " ".join(args).strip() if args else "Say OK in one short sentence."

    print(f"Model: {model}")
    print("Making Responses API call…")
    resp = client.responses.create(
        model=model,
        input=text,
        instructions="Reply with a short, helpful sentence.",
        max_output_tokens=200,
        reasoning={"effort": "low"},
    )
    usage = {}
    u = getattr(resp, "usage", None)
    if u is not None:
        for k in ("input_tokens", "output_tokens", "total_tokens"):
            v = getattr(u, k, None)
            if isinstance(v, int):
                usage[k] = v
    extracted = _extract_text_from_responses(resp)

    _print_kv(
        "Responses API summary",
        {
            "has_output_text": int(bool(getattr(resp, "output_text", None))),
            "output_text": getattr(resp, "output_text", None),
            "num_output_items": len(getattr(resp, "output", []) or []),
            "extracted_lines": extracted,
            "usage": usage,
        },
    )

    # Raw dump (truncated)
    try:
        raw = resp.model_dump()
        print("\n== Raw response (truncated) ==")
        sraw = json.dumps(raw, ensure_ascii=False, indent=2)
        print(sraw[:4000])
    except Exception:
        print("\n(raw dump unavailable)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


