"""Small helpers shared between nodes.py and edges.py."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graph.state import BookingState


def to_langchain_messages(state: BookingState) -> list:
    lc_messages: list = []
    for m in state.get("messages", []):
        if m["role"] == "user":
            lc_messages.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            lc_messages.append(AIMessage(content=m["content"]))
        else:  # transient "system" hints injected by a node, e.g. proposed slot
            lc_messages.append(SystemMessage(content=m["content"]))
    return lc_messages


def last_user_message(state: BookingState) -> str:
    for m in reversed(state.get("messages", [])):
        if m["role"] == "user":
            return m["content"]
    return ""


def bump_retry(state: BookingState, node_name: str) -> dict:
    """Increment this node's own re-ask counter. Merge the returned dict into
    a node's output whenever it's re-asking for the same thing."""
    counts = dict(state.get("node_visit_counts") or {})
    counts[node_name] = counts.get(node_name, 0) + 1
    return {"node_visit_counts": counts}


def retry_count_for(state: BookingState, node_name: str) -> int:
    return (state.get("node_visit_counts") or {}).get(node_name, 0)
