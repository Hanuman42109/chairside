"""Data-access functions for the `calls`, `sessions`, and `eval_scores` tables.

Kept as plain async functions over asyncpg rather than an ORM -- the query
surface here is small and the SQL is worth being able to read directly.
"""

import json
from datetime import datetime
from typing import Any

from app.db.client import get_pool


async def create_call(retell_call_id: str, caller_phone: str) -> str:
    """Create a call row (or return the existing one if this retell_call_id
    was already seen -- webhooks can be retried)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        insert into calls (retell_call_id, caller_phone)
        values ($1, $2)
        on conflict (retell_call_id) do update set caller_phone = excluded.caller_phone
        returning id
        """,
        retell_call_id,
        caller_phone,
    )
    return str(row["id"])


async def update_call(
    call_id: str,
    *,
    status: str | None = None,
    outcome: str | None = None,
    ended_at: datetime | None = None,
    transcript: list[dict] | None = None,
    recording_url: str | None = None,
    caller_phone: str | None = None,
) -> None:
    pool = await get_pool()
    values: list[Any] = []
    set_clauses: list[str] = []

    for column, value in (
        ("status", status),
        ("outcome", outcome),
        ("ended_at", ended_at),
        ("recording_url", recording_url),
        ("caller_phone", caller_phone),
    ):
        if value is not None:
            values.append(value)
            set_clauses.append(f"{column} = ${len(values)}")

    if transcript is not None:
        values.append(json.dumps(transcript))
        set_clauses.append(f"transcript = ${len(values)}::jsonb")

    if not set_clauses:
        return

    values.append(call_id)
    await pool.execute(
        f"update calls set {', '.join(set_clauses)} where id = ${len(values)}", *values
    )


async def get_call(call_id: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow("select * from calls where id = $1", call_id)
    return dict(row) if row else None


async def list_calls(limit: int = 50, offset: int = 0) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "select * from calls order by started_at desc limit $1 offset $2", limit, offset
    )
    return [dict(r) for r in rows]


async def find_latest_booked_call(caller_phone: str, exclude_call_id: str | None = None) -> dict | None:
    """Most recent call for this phone number that ended in a confirmed
    booking, with its final graph_state -- used by lookup_existing_appointment
    to find an existing appointment without a Cal.com round-trip."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        select c.id as call_id, s.graph_state
        from calls c
        join sessions s on s.call_id = c.id
        where c.caller_phone = $1
          and c.outcome = 'booked'
          and ($2::uuid is null or c.id != $2)
        order by c.started_at desc
        limit 1
        """,
        caller_phone,
        exclude_call_id,
    )
    if row is None:
        return None
    result = dict(row)
    result["graph_state"] = json.loads(result["graph_state"]) if result["graph_state"] else {}
    return result


async def upsert_session_state(call_id: str, graph_state: dict, current_node: str) -> None:
    """Overwrite the single `sessions` row for this call with the latest
    LangGraph state -- called once per turn from the websocket handler."""
    pool = await get_pool()
    await pool.execute(
        """
        insert into sessions (call_id, graph_state, current_node, updated_at)
        values ($1, $2::jsonb, $3, now())
        on conflict (call_id) do update
            set graph_state = excluded.graph_state,
                current_node = excluded.current_node,
                updated_at = now()
        """,
        call_id,
        json.dumps(graph_state, default=str),
        current_node,
    )


async def get_session_state(call_id: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow("select * from sessions where call_id = $1", call_id)
    return dict(row) if row else None


async def create_eval_score(
    call_id: str,
    *,
    slot_filling_accuracy: float,
    hallucination_score: float,
    escalation_correctness: float,
    overall_score: float,
    notes: str | None = None,
) -> str:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        insert into eval_scores
            (call_id, slot_filling_accuracy, hallucination_score, escalation_correctness, overall_score, notes)
        values ($1, $2, $3, $4, $5, $6)
        returning id
        """,
        call_id,
        slot_filling_accuracy,
        hallucination_score,
        escalation_correctness,
        overall_score,
        notes,
    )
    return str(row["id"])


async def list_eval_scores(limit: int = 50, offset: int = 0) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "select * from eval_scores order by evaluated_at desc limit $1 offset $2", limit, offset
    )
    return [dict(r) for r in rows]
