from app.graph.state import new_state


def test_new_state_defaults():
    state = new_state("call-123", "+15551234567")
    assert state["call_id"] == "call-123"
    assert state["caller_phone"] == "+15551234567"
    assert state["messages"] == []
    assert state["current_node"] == "greeting"
    assert state["node_visit_counts"] == {}
    assert state["booking_confirmed"] is False
    assert state["escalated"] is False
    assert state["call_outcome"] is None
