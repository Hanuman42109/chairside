"""Retell Custom LLM websocket: this is the "brain" of the call.

Retell opens one websocket per call and streams turn-by-turn events; we run
the LangGraph graph (app/graph/graph.py) once per caller utterance and
stream back the assistant's reply. See that module's docstring for how
turn-taking/interrupt-and-resume works.

Message shapes verified against Retell's own reference implementation
(github.com/RetellAI/retell-custom-llm-python-demo, app/server.py +
app/custom_types.py), not just documentation prose:
- We must send a `config` message right after accepting the connection, with
  `"call_details": True`, or Retell never sends us the `call_details` event
  (the caller's phone number is NOT passed via query params/URL -- it only
  arrives in `call_details.call.from_number`).
- Every message we send back needs an explicit `response_type` field
  ("config" | "ping_pong" | "response") -- Retell doesn't infer it.
- `interaction_type` values: call_details, ping_pong, update_only,
  response_required, reminder_required. Transcript entries use
  `role: "agent" | "user" | "system"` (not "assistant").
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import repository
from app.graph.graph import get_compiled_graph
from app.graph.runner import run_turn, thread_config

logger = logging.getLogger(__name__)
router = APIRouter(tags=["retell-llm-websocket"])


@router.websocket("/llm-websocket/{retell_call_id}")
async def llm_websocket(websocket: WebSocket, retell_call_id: str) -> None:
    await websocket.accept()
    await websocket.send_json(
        {"response_type": "config", "config": {"auto_reconnect": True, "call_details": True}}
    )

    # Caller phone isn't known yet -- it arrives via the call_details event
    # below, not query params. Create the call row with an empty phone so we
    # have a stable internal UUID (LangGraph thread id / sessions FK) to greet
    # with, then backfill it once call_details lands.
    caller_phone = ""
    internal_call_id = await repository.create_call(retell_call_id, caller_phone)

    try:
        # `auto_reconnect` (enabled in the config message above) means this
        # handler can run again for the SAME call after a dropped connection.
        # Only speak first (and thereby advance the graph) on a genuinely new
        # call -- on a reconnect, the graph already has state and re-running a
        # turn with no new caller input would silently re-execute whatever
        # node is next, regenerating a near-duplicate message out of nowhere
        # instead of waiting for the caller's actual next utterance.
        graph = get_compiled_graph()
        existing_state = await graph.aget_state(thread_config(internal_call_id))
        if not existing_state.values:
            greeting_reply = await run_turn(internal_call_id, caller_phone, user_utterance=None)
            await websocket.send_json(
                {
                    "response_type": "response",
                    "response_id": 0,
                    "content": greeting_reply,
                    "content_complete": True,
                    "end_call": False,
                }
            )

        while True:
            raw = await websocket.receive_text()
            event: dict[str, Any] = json.loads(raw)
            interaction_type = event.get("interaction_type")

            if interaction_type == "call_details":
                from_number = event.get("call", {}).get("from_number", "")
                if from_number and from_number != caller_phone:
                    caller_phone = from_number
                    await repository.update_call(internal_call_id, caller_phone=caller_phone)
                    await graph.aupdate_state(
                        thread_config(internal_call_id), {"caller_phone": caller_phone}
                    )
                continue

            if interaction_type == "ping_pong":
                await websocket.send_json(
                    {"response_type": "ping_pong", "timestamp": event.get("timestamp")}
                )
                continue

            if interaction_type == "update_only":
                continue  # partial transcript update; no response expected

            if interaction_type in ("response_required", "reminder_required"):
                transcript = event.get("transcript", [])
                last_user_msg = next(
                    (t["content"] for t in reversed(transcript) if t.get("role") == "user"), ""
                )
                try:
                    reply = await run_turn(internal_call_id, caller_phone, user_utterance=last_user_msg)
                except Exception:
                    logger.exception("graph turn failed for call_id=%s", internal_call_id)
                    reply = "I'm sorry, I'm having trouble right now -- let me get a team member to help you."

                await websocket.send_json(
                    {
                        "response_type": "response",
                        "response_id": event.get("response_id", 0),
                        "content": reply,
                        "content_complete": True,
                        "end_call": False,
                    }
                )
    except WebSocketDisconnect:
        logger.info("llm websocket disconnected retell_call_id=%s", retell_call_id)
