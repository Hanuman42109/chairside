"""Shared "one turn of the booking graph" logic, used by both the Retell
websocket handler (app/routes/llm_websocket.py) and the local CLI chat
script (scripts/chat.py) so call-row resolution, state building, graph
invocation, and session persistence live in exactly one place.
"""

from app.db import repository
from app.graph.graph import get_compiled_graph
from app.graph.state import new_state


def thread_config(internal_call_id: str) -> dict:
    return {"configurable": {"thread_id": internal_call_id}}


async def run_turn(internal_call_id: str, caller_phone: str, user_utterance: str | None) -> str:
    """Feed one caller utterance into the graph and return the assistant's reply.

    `user_utterance` is None only for the very first turn (the graph greets first)
    or a reconnect/ping with nothing new to feed in.

    Resuming a thread paused at an `interrupt_after` node must be done with
    `ainvoke(None, config)` -- passing a non-None value is treated as fresh
    input to START, which would silently restart the conversation from
    `greeting` every turn instead of continuing where it left off. The new
    user message is merged into the checkpointed state first (the same way a
    node's return value would be), then execution resumes from `None`.
    """
    graph = get_compiled_graph()
    config = thread_config(internal_call_id)

    existing = await graph.aget_state(config)
    if not existing.values:
        result = await graph.ainvoke(new_state(internal_call_id, caller_phone), config)
    else:
        if user_utterance:
            await graph.aupdate_state(config, {"messages": [{"role": "user", "content": user_utterance}]})
        result = await graph.ainvoke(None, config)

    await repository.upsert_session_state(internal_call_id, dict(result), result.get("current_node", ""))

    for message in reversed(result.get("messages", [])):
        if message["role"] == "assistant":
            return message["content"]
    return ""
