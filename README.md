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
  ├─ unclear:      clarify_intent → detect_intent (re-classify with the caller's answer)
  └─ escalation:   escalate → closing
```

Every tool-calling node (`check_availability`, `book_appointment`,
`create_crm_contact`, `send_confirmation_sms`, `update_booking`,
`faq_lookup`) routes to `escalate` on failure via a shared
`route_or_escalate` helper, so failure handling is defined in exactly one
place (`backend/app/graph/edges.py`). Slot-filling loops (asking again for
missing info) are capped per-node at 3 retries before escalating, so a
confused back-and-forth can't loop forever. `detect_intent` itself only
escalates for genuinely urgent/complaint content -- small talk or ambiguous
input routes to `clarify_intent` instead (same 3-retry cap), so a caller
who says "hi, how are you?" before stating their request doesn't get
permanently escalated on the first ambiguous turn.

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

The dashboard reads live data from `GET /api/calls` and `GET /api/eval-scores`
(`backend/app/routes/dashboard.py`) — start the backend before the frontend
so those calls succeed.

## Local demo (no Retell/Cal.com/HubSpot/Twilio accounts needed)

With `TOOLS_MOCK_MODE=true` (the default — see `backend/.env.example`),
`check_availability`/`book_slot`/`reschedule_booking`/`cancel_booking`
(Cal.com), `upsert_contact` (HubSpot), and `send_sms` (Twilio) all return
realistic fake data instead of calling those providers, so the full booking
conversation can run end-to-end with only a Groq/Anthropic/OpenAI key and a
Postgres `DATABASE_URL`.

Talk to the agent directly from a terminal (no Retell account required):

```bash
cd backend
python scripts/chat.py                    # or: python scripts/chat.py --phone +15551234567
```

This creates a real row in the `calls` table (so it shows up on the
dashboard's Calls page like any other call) and drives the same LangGraph
turn logic the Retell websocket uses (`backend/app/graph/runner.py`), reading
your replies from stdin until the call reaches a terminal outcome or you type
`quit`.

To get a real `eval_scores` row on the dashboard's Eval Results page:

1. Run `scripts/chat.py`, complete a booking, and note the printed `call_id`.
2. Copy `backend/app/eval/fixtures/sample_new_booking.json` and set its
   `"call_id"` to that UUID.
3. `python -m app.eval.run_eval app/eval/fixtures/<your_copy>.json --write-db`

## What's real vs. stubbed right now

- **Real and tested:** the FastAPI app, the dashboard read endpoints, the
  full LangGraph state machine (compiles, routes, and resumes correctly
  across turns — see `backend/tests/test_graph_edges.py`), tool-mock mode for
  local demos, the eval scoring framework, the FAQ knowledge base (actually
  indexes and retrieves from `backend/app/tools/faq_data/faq.md`), the DB
  schema/migration runner, and the frontend shell (builds, lints, tests
  pass).
- **Verified against live accounts:** Cal.com (availability lookup, booking,
  reschedule, cancel all confirmed against a real Cal.com account —
  `check_availability` requires `CALCOM_EVENT_TYPE_ID` and a fixed
  `cal-api-version` per endpoint, see `backend/app/tools/calcom.py`) and
  HubSpot (contact create/update/dedupe-by-phone confirmed with standard
  properties; the three custom properties -- `chairside_appointment_type`,
  `chairside_insurance_provider`, `chairside_last_call_notes` -- must be
  created under HubSpot Settings → Properties → Contact properties before
  those fields will save, otherwise the contact create/update call fails).
- **Written, not yet verified against a live account:** Twilio SMS sending —
  the code follows the documented SDK usage but hasn't been run against a
  real account yet.
- **Verified against a live Retell agent:** the Custom LLM websocket
  (`backend/app/routes/llm_websocket.py`) and webhook signature verification
  (`backend/app/routes/webhook.py`) — both were fixed and confirmed against a
  real Retell agent over an ngrok tunnel, not just documentation. See
  [`docs/retell-integration-debugging-log.md`](docs/retell-integration-debugging-log.md)
  for the full list of issues found and how each was fixed.

## Environment variables

See `backend/.env.example` and `frontend/.env.example` for the full list.
Nothing needs to be filled in to run the test suites or the LangGraph graph
construction/routing locally — only the actual tool calls (LLM, Cal.com,
HubSpot, Twilio) need real keys.

## Further reading

- [`docs/retell-integration-debugging-log.md`](docs/retell-integration-debugging-log.md)
  — a technical log of every bug found while verifying the local demo and the
  live Retell integration against real traffic (LangGraph turn-resume bug,
  Cal.com/HubSpot API mismatches, Retell websocket protocol gaps, an
  intent-classification dead end, and a reconnect-handling bug), with root
  cause, fix, and verification for each.
