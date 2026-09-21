"""Local terminal chat against the booking graph -- no Retell account needed.

Usage:
    python scripts/chat.py [--phone +15551234567]

Creates a real `calls` row via repository.create_call (using a synthetic
retell_call_id like "cli-<uuid>") so the session shows up in the dashboard
like any other call, then loops stdin/stdout through app.graph.runner.run_turn
until the graph reaches a terminal call_outcome, escalates, or the user quits.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Windows terminals often default to cp1252, which can't encode the smart
# quotes/typographic characters LLM replies tend to contain.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db import repository  # noqa: E402
from app.db.client import close_pool  # noqa: E402
from app.graph.graph import get_compiled_graph  # noqa: E402
from app.graph.runner import run_turn, thread_config  # noqa: E402

TERMINAL_OUTCOMES = {"booked", "rescheduled", "escalated", "faq_only", "abandoned"}


async def _main(phone: str) -> None:
    retell_call_id = f"cli-{uuid.uuid4().hex[:8]}"
    call_id = await repository.create_call(retell_call_id, phone)
    print(f"[call created: id={call_id} retell_call_id={retell_call_id}]\n")

    reply = await run_turn(call_id, phone, user_utterance=None)
    print(f"Agent: {reply}\n")

    graph = get_compiled_graph()
    try:
        while True:
            state = await graph.aget_state(thread_config(call_id))
            if state.values.get("call_outcome") in TERMINAL_OUTCOMES:
                print(f"[call ended: outcome={state.values['call_outcome']}]")
                break

            try:
                user_input = input("You: ").strip()
            except EOFError:
                print("\n[input closed, quitting]")
                break
            if user_input.lower() in ("quit", "exit"):
                print("[quitting]")
                break

            reply = await run_turn(call_id, phone, user_utterance=user_input)
            print(f"Agent: {reply}\n")
    finally:
        final_state = await graph.aget_state(thread_config(call_id))
        outcome = final_state.values.get("call_outcome")
        await repository.update_call(
            call_id, status="completed", outcome=outcome, ended_at=datetime.now(UTC)
        )
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the Chairside booking agent locally.")
    parser.add_argument("--phone", default="+15551234567", help="Caller phone in E.164 format.")
    args = parser.parse_args()
    asyncio.run(_main(args.phone))


if __name__ == "__main__":
    main()
