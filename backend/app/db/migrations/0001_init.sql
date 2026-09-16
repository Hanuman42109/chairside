-- Chairside initial schema: calls, sessions, eval_scores.
-- Run via `python -m app.db.migrate` (see app/db/migrate.py) or paste into
-- the Supabase SQL editor.

create extension if not exists "pgcrypto"; -- for gen_random_uuid()

create table if not exists calls (
    id uuid primary key default gen_random_uuid(),
    retell_call_id text unique not null,
    caller_phone text not null,
    started_at timestamptz not null default now(),
    ended_at timestamptz,
    status text not null default 'in_progress'
        check (status in ('in_progress', 'completed', 'failed')),
    outcome text
        check (outcome in ('booked', 'rescheduled', 'escalated', 'abandoned', 'faq_only')),
    transcript jsonb not null default '[]'::jsonb,
    recording_url text,
    created_at timestamptz not null default now()
);

create index if not exists idx_calls_caller_phone on calls (caller_phone);
create index if not exists idx_calls_started_at on calls (started_at desc);

-- One row per call, overwritten each turn with the latest LangGraph state --
-- this is a snapshot for the dashboard/debugging, not the graph's own
-- checkpointer (see app/graph/graph.py docstring).
create table if not exists sessions (
    id uuid primary key default gen_random_uuid(),
    call_id uuid not null unique references calls (id) on delete cascade,
    graph_state jsonb not null default '{}'::jsonb,
    current_node text,
    updated_at timestamptz not null default now()
);

create table if not exists eval_scores (
    id uuid primary key default gen_random_uuid(),
    call_id uuid not null references calls (id) on delete cascade,
    slot_filling_accuracy float,
    hallucination_score float,
    escalation_correctness float,
    overall_score float,
    notes text,
    evaluated_at timestamptz not null default now()
);

create index if not exists idx_eval_scores_call_id on eval_scores (call_id);
