# Chairside

Chairside is a voice AI dental-office receptionist: a caller phones in, and an
AI agent handles new-appointment booking, rescheduling, FAQ questions, and
escalates anything it can't (or shouldn't) resolve on its own. After a
successful booking it creates a CRM contact, reserves the calendar slot, and
texts a confirmation.

Built as a portfolio project for a Forward Deployed Engineer application at
Retell AI. Runs entirely on free tiers.

## Architecture

```mermaid
flowchart LR
    Caller((Caller)) --> Retell[Retell AI\nvoice layer]
    Retell <-->|Custom LLM websocket\nper-utterance turns| Backend
    Retell -->|call lifecycle webhook| Backend
    Backend[FastAPI backend\nLangGraph state machine]
    Backend --> Groq[Groq LLM\n(swap: Claude / GPT-4o-mini)]
    Backend --> FAQ[LlamaIndex FAQ\n(local embeddings)]
    Backend --> Cal[Cal.com\navailability + booking]
    Backend --> Hub[HubSpot\nCRM contact]
    Backend --> Twilio[Twilio\nSMS confirmation]
    Backend --> DB[(Supabase Postgres\ncalls / sessions / eval_scores)]
    Dashboard[React + Tailwind\ndashboard] --> Backend
```

The backend is the brain of the call. Retell handles telephony and
speech-to-text/text-to-speech; our FastAPI service receives each caller
utterance, runs it through a LangGraph state machine that decides what to
say and which tools to call, and streams a reply back. See
[`backend/app/graph/graph.py`](backend/app/graph/graph.py) for exactly how
turn-taking works across that websocket.

## Repo structure

```
chairside/
├── backend/                   FastAPI service
│   ├── app/
│   │   ├── config.py           Centralized env-based settings
│   │   ├── main.py              FastAPI app + router wiring
│   │   ├── routes/              Retell-facing HTTP/WebSocket endpoints
│   │   ├── graph/                LangGraph state machine (state/nodes/edges/prompts)
│   │   ├── tools/                  Cal.com, HubSpot, Twilio, FAQ KB, LLM switch
│   │   ├── db/                       Postgres client, repository, SQL migrations
│   │   └── eval/                       Transcript scoring framework + fixtures
│   └── tests/                  Pytest suite (no API keys required)
├── frontend/                  React + Tailwind dashboard (Vite)
│   └── src/
│       ├── pages/               CallsListPage, EvalResultsPage
│       ├── components/          Layout, StatusBadge
│       └── lib/                 API client, types, hooks
├── .github/workflows/         CI (lint + test, backend and frontend independently)
└── docs/
```

## Tech stack

| Layer          | Choice                                   | Notes |
|----------------|-------------------------------------------|-------|
| Voice          | Retell AI                                | Configured separately in the Retell dashboard |
| Backend        | FastAPI (Python)                         | Async throughout |
| LLM            | Groq (Llama 3.3) by default              | One-line swap to Claude/GPT-4o-mini, see below |
| Orchestration  | LangGraph                                | Explicit state graph, see `backend/app/graph/` |
| Knowledge base | LlamaIndex + local HuggingFace embeddings | No API key needed, ~130MB model downloaded once |
| Scheduling     | Cal.com API                              | Availability + booking |
| CRM            | HubSpot (free tier)                      | Contact upsert by phone number |
| Notifications  | Twilio                                   | SMS booking confirmation |
| Database       | Supabase Postgres                        | Plain SQL migrations, `asyncpg` |
| Frontend       | React + TypeScript + Tailwind (Vite)     | Deployed to Vercel |
| Backend hosting| Render (free tier)                       | |
| CI             | GitHub Actions                           | Backend and frontend jobs, path-filtered |

## How the LangGraph flow is structured

```
greeting → detect_intent
  ├─ new_booking:  collect_patient_info → collect_appointment_prefs → check_availability
                   → confirm_slot → book_appointment → create_crm_contact
                   → send_confirmation_sms → closing
  ├─ reschedule:   lookup_existing_appointment → collect_new_time → check_availability
                   → confirm_reschedule → update_booking → send_confirmation_sms → closing
  ├─ faq:          faq_lookup → answer_faq → anything_else → (yes: detect_intent | no: closing)
  └─ escalation:   escalate → closing
```

Every tool-calling node (`check_availability`, `book_appointment`,
`create_crm_contact`, `send_confirmation_sms`, `update_booking`,
`faq_lookup`) routes to `escalate` on failure via a shared
`route_or_escalate` helper, so failure handling is defined in exactly one
place (`backend/app/graph/edges.py`). Slot-filling loops (asking again for
missing info) are capped per-node at 3 retries before escalating, so a
confused back-and-forth can't loop forever.

## Retell integration: two wiring options

The backend exposes both, so the choice can be made later in the Retell
dashboard without changing backend code:

1. **Custom LLM websocket** (`WS /llm-websocket/{retell_call_id}`) — Retell
   streams the conversation to us; our LangGraph graph is the "brain" driving
   every turn. This is the integration that actually uses the state machine.
2. **Retell's own LLM + custom functions** (`POST /webhook/retell/functions`)
   — Retell's built-in LLM handles the conversation and calls our backend
   only for specific actions (`check_availability`, `book_appointment`,
   `create_crm_contact`, `send_confirmation_sms`, `query_faq`). Stateless,
   simpler, but doesn't exercise the LangGraph flow.

Call lifecycle events (`call_started` / `call_ended` / `call_analyzed`) land
on a third endpoint, `POST /webhook/retell/events`, for logging to the
`calls` table regardless of which integration is used.

**Note:** the exact Retell webhook/Custom-LLM message field names in
`backend/app/routes/webhook.py` and `backend/app/routes/llm_websocket.py`
follow the commonly documented pattern but haven't been checked against a
live Retell payload yet — check those `TODO` comments against current Retell
docs before pointing a real agent at this backend.

## Swapping the LLM provider

Set `LLM_PROVIDER=groq|anthropic|openai` in `backend/.env` (plus that
provider's API key). Every graph node gets its model from
`app/tools/llm.get_chat_model()`, so this is the only place the switch needs
to happen — no code changes.

## Database

Three tables (`backend/app/db/migrations/0001_init.sql`):

- **calls** — one row per phone call (status, outcome, transcript, recording).
- **sessions** — one row per call, overwritten each turn with the latest
  LangGraph state snapshot. This is for the dashboard/debugging, *not* a
  replacement for LangGraph's own checkpointer (see the caveat below).
- **eval_scores** — one row per evaluated call (slot-filling accuracy,
  hallucination score, escalation correctness, overall score).

Migrations are plain SQL, applied in order by
`python -m app.db.migrate` (tracked in a `schema_migrations` table). No ORM —
the schema is meant to be readable directly, and paste-able into the
Supabase SQL editor if you'd rather run it by hand.

**Checkpointer caveat:** the LangGraph graph currently uses `MemorySaver`
(in-process, in-memory). That's fine for local dev, but it will not survive
a Render free-tier dyno restart/redeploy and won't work across multiple
worker processes. Before relying on multi-turn calls in production, swap it
for `langgraph.checkpoint.postgres.AsyncPostgresSaver` pointed at the same
Supabase database — see the docstring in `backend/app/graph/graph.py`.

## Eval framework

`backend/app/eval/` scores a call transcript against an expected outcome on
three axes: slot-filling accuracy, hallucination (did the agent claim
availability/info not in the ground truth), and escalation correctness.
Scoring is deterministic/heuristic by default (substring + regex matching)
rather than an LLM-judge, to keep the default cost at $0 — see
`backend/app/eval/evaluator.py` for where an optional LLM-judge pass could
be added later.

```bash
cd backend
python -m app.eval.run_eval app/eval/fixtures/sample_new_booking.json app/eval/fixtures/sample_escalation.json
```

## Local setup

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt

cp .env.example .env          # fill in whatever keys you have; everything has a safe default
python -m app.db.migrate      # applies SQL migrations to DATABASE_URL

uvicorn app.main:app --reload --port 8000
```

Run tests/lint (no API keys required — external calls are mocked or simply
not exercised by the unit tests):

```bash
pytest -q
ruff check app tests
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev        # http://localhost:5173
```

```bash
npm run lint
npm run build
npm run test
```

The dashboard currently points at `GET /api/calls` and `GET /api/eval-scores`,
which don't exist on the backend yet (see the `TODO` in
`frontend/src/lib/api.ts`) — the pages render a clear "not wired up yet"
state until those read endpoints are added.

## What's real vs. stubbed right now

- **Real and tested:** the FastAPI app, the full LangGraph state machine
  (compiles and routes correctly — see `backend/tests/test_graph_edges.py`),
  the eval scoring framework, the FAQ knowledge base (actually indexes and
  retrieves from `backend/app/tools/faq_data/faq.md`), the DB schema/migration
  runner, and the frontend shell (builds, lints, tests pass).
- **Stubbed, needs real credentials:** Cal.com, HubSpot, Twilio, and your
  chosen LLM provider — the integration code is written and typed against
  each provider's real API shape, but untested against live accounts. Fill in
  `backend/.env` and go one integration at a time.
- **Needs your input before going live:** confirm the Retell webhook/Custom
  LLM message shapes (flagged above), decide which of the two Retell wiring
  options to use, and add the dashboard read endpoints if you want live data
  in the frontend.

## Environment variables

See `backend/.env.example` and `frontend/.env.example` for the full list.
Nothing needs to be filled in to run the test suites or the LangGraph graph
construction/routing locally — only the actual tool calls (LLM, Cal.com,
HubSpot, Twilio) need real keys.
