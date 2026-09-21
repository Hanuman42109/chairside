"""Read-only endpoints backing the React dashboard (frontend/src/lib/api.ts)."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import repository

router = APIRouter(prefix="/api", tags=["dashboard"])


class CallOut(BaseModel):
    id: UUID
    retell_call_id: str
    caller_phone: str
    started_at: datetime
    ended_at: datetime | None
    status: str
    outcome: str | None
    recording_url: str | None
    # transcript intentionally excluded -- frontend's Call type omits it too


class EvalScoreOut(BaseModel):
    id: UUID
    call_id: UUID
    slot_filling_accuracy: float | None
    hallucination_score: float | None
    escalation_correctness: float | None
    overall_score: float | None
    notes: str | None
    evaluated_at: datetime


@router.get("/calls", response_model=list[CallOut])
async def list_calls(limit: int = 50, offset: int = 0) -> list[dict]:
    return await repository.list_calls(limit=limit, offset=offset)


@router.get("/eval-scores", response_model=list[EvalScoreOut])
async def list_eval_scores(limit: int = 50, offset: int = 0) -> list[dict]:
    return await repository.list_eval_scores(limit=limit, offset=offset)
