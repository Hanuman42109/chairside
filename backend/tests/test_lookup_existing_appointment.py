import pytest

from app.db import repository
from app.graph import nodes


class _FakeReply:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChatModel:
    async def ainvoke(self, messages):
        return _FakeReply("Found it -- is that the appointment you mean?")


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch):
    monkeypatch.setattr(nodes, "get_chat_model", lambda *a, **k: _FakeChatModel())


async def test_lookup_existing_appointment_escalates_when_no_match(monkeypatch):
    async def _no_match(caller_phone, exclude_call_id=None):
        return None

    monkeypatch.setattr(repository, "find_latest_booked_call", _no_match)

    result = await nodes.lookup_existing_appointment(
        {"call_id": "call-1", "caller_phone": "+15551234567", "messages": []}
    )

    assert result["escalation_reason"]
    assert result["current_node"] == "lookup_existing_appointment"


async def test_lookup_existing_appointment_finds_prior_booking(monkeypatch):
    async def _match(caller_phone, exclude_call_id=None):
        return {
            "call_id": "call-0",
            "graph_state": {
                "booking_uid": "cal-abc123",
                "appointment_type": "cleaning",
                "selected_slot": {"start": "2026-09-22T09:00:00-04:00"},
            },
        }

    monkeypatch.setattr(repository, "find_latest_booked_call", _match)

    result = await nodes.lookup_existing_appointment(
        {"call_id": "call-1", "caller_phone": "+15551234567", "messages": []}
    )

    assert result["existing_booking_uid"] == "cal-abc123"
    assert result["appointment_type"] == "cleaning"
    assert "escalation_reason" not in result
