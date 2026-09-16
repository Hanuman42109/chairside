"""Retell Custom LLM websocket: this is the "brain" of the call.

Retell opens one websocket per call and streams turn-by-turn events; we run
the LangGraph graph (app/graph/graph.py) once per caller utterance and
stream back the assistant's reply. See that module's docstring for how
turn-taking/interrupt-and-resume works.

TODO: verify message field names (`interaction_type`, `response_id`,
`transcript`, how the caller's phone number is passed) against current
Retell Custom LLM docs before pointing a real agent at this endpoint --
the shape here follows the commonly documented pattern but has not been
checked against a live payload.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import repository
from app.graph.graph import get_compiled_graph
from app.graph.state import new_state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["retell-llm-websocket"])


def _thread_config(internal_call_id: str) -> dict:
    return {"configurable": {"thread_id": internal_call_id}}


async def _run_turn(internal_call_id: str, caller_phone: str, user_utterance: str | None) -> str:
    """Feed one caller utterance into the graph and return the assistant's reply.

    `user_utterance` is None only for the very first turn (the graph greets first).
    """
    graph = get_compiled_graph()
    config = _thread_config(internal_call_id)

    existing = await graph.aget_state(config)
    if not existing.values:
        input_state = new_state(internal_call_id, caller_phone)
    elif user_utterance:
        input_state = {"messages": [{"role": "user", "content": user_utterance}]}
    else:
        input_state = None  # reconnect/ping with nothing new to feed in

    result = await graph.ainvoke(input_state, config)

    await repository.upsert_session_state(internal_call_id, dict(result), result.get("current_node", ""))

    for message in reversed(result.get("messages", [])):
        if message["role"] == "assistant":
            return message["content"]
    return ""


@router.websocket("/llm-websocket/{retell_call_id}")
async def llm_websocket(websocket: WebSocket, retell_call_id: str) -> None:
    await websocket.accept()
    caller_phone = websocket.query_params.get("caller_phone", "")

    # Resolve/create our internal call row so we have a stable UUID to use as
    # the LangGraph thread id and the `sessions.call_id` foreign key --
    # Retell's own call id is a string, not our primary key.
    internal_call_id = await repository.create_call(retell_call_id, caller_phone)

    try:
        greeting_reply = await _run_turn(internal_call_id, caller_phone, user_utterance=None)
        await websocket.send_json(
            {"response_id": 0, "content": greeting_reply, "content_complete": True, "end_call": False}
        )

        while True:
            raw = await websocket.receive_text()
            event: dict[str, Any] = json.loads(raw)
            interaction_type = event.get("interaction_type")

            if interaction_type == "ping_pong":
                await websocket.send_json({"response_type": "ping_pong", "timestamp": event.get("timestamp")})
                continue

            if interaction_type == "update_only":
                continue  # partial transcript update; no response expected

            if interaction_type in ("response_required", "reminder_required"):
                transcript = event.get("transcript", [])
                last_user_msg = next(
                    (t["content"] for t in reversed(transcript) if t.get("role") == "user"), ""
                )
                try:
                    reply = await _run_turn(internal_call_id, caller_phone, user_utterance=last_user_msg)
                except Exception:
                    logger.exception("graph turn failed for call_id=%s", internal_call_id)
                    reply = "I'm sorry, I'm having trouble right now -- let me get a team member to help you."

                await websocket.send_json(
                    {
                        "response_id": event.get("response_id", 0),
                        "content": reply,
                        "content_complete": True,
                        "end_call": False,
                    }
                )
    except WebSocketDisconnect:
        logger.info("llm websocket disconnected retell_call_id=%s", retell_call_id)
