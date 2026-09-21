from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import repository
from app.main import app


def test_list_calls_returns_data_and_excludes_transcript(monkeypatch):
    call_id = str(uuid4())
    canned = {
        "id": call_id,
        "retell_call_id": "retell-1",
        "caller_phone": "+15551234567",
        "started_at": datetime.now(UTC),
        "ended_at": None,
        "status": "completed",
        "outcome": "booked",
        "transcript": [{"role": "user", "content": "hi"}],
        "recording_url": None,
        "created_at": datetime.now(UTC),
    }

    async def _fake_list_calls(limit=50, offset=0):
        return [canned]

    monkeypatch.setattr(repository, "list_calls", _fake_list_calls)

    with TestClient(app) as client:
        response = client.get("/api/calls")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == call_id
    assert "transcript" not in body[0]


def test_list_eval_scores_returns_data(monkeypatch):
    score_id = str(uuid4())
    call_id = str(uuid4())
    canned = {
        "id": score_id,
        "call_id": call_id,
        "slot_filling_accuracy": 0.9,
        "hallucination_score": 1.0,
        "escalation_correctness": 1.0,
        "overall_score": 0.95,
        "notes": None,
        "evaluated_at": datetime.now(UTC),
    }

    async def _fake_list_eval_scores(limit=50, offset=0):
        return [canned]

    monkeypatch.setattr(repository, "list_eval_scores", _fake_list_eval_scores)

    with TestClient(app) as client:
        response = client.get("/api/eval-scores")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["call_id"] == call_id
    assert body[0]["overall_score"] == 0.95
