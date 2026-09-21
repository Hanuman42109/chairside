# Retell Integration Debugging Log

A technical record of the issues found while turning the Chairside scaffold into a working local demo and then a live Retell voice agent, and how each was diagnosed and fixed. Written chronologically, in the order the issues actually surfaced during live testing.

Context: the initial scaffold (LangGraph flow, tool modules, eval framework, dashboard shell) looked complete on paper, but most of it had never been exercised end-to-end against real traffic. Every issue below was found by actually running the system — local conversations, live API calls, a real Retell agent — not by code review alone.

---

## 1. Dashboard read endpoints missing (404)

**Symptom:** the React dashboard's Calls and Eval Results pages rendered a friendly "not wired up yet" banner instead of data.

**Root cause:** `GET /api/calls` and `GET /api/eval-scores` simply didn't exist as routes. The data-access functions (`repository.list_calls`, `repository.list_eval_scores`) were already implemented; nothing served them over HTTP.

**Fix:** added `backend/app/routes/dashboard.py` with two `GET` endpoints backed by those existing repository functions, wired into `main.py`. Response models use `datetime` and `uuid.UUID` field types (not `str`) so FastAPI/Pydantic handle JSON serialization automatically — an early version used `str` typing and failed with `ResponseValidationError` the moment real `datetime`/`UUID` objects came back from `asyncpg`, since Pydantic v2 doesn't silently coerce those to `str`.

---

## 2. Tool mock mode for local development

**Need:** exercise the full booking conversation (availability check → book → CRM upsert → SMS) without live Cal.com/HubSpot/Twilio accounts.

**Fix:** a `TOOLS_MOCK_MODE` setting (default `true`) with a small `app/tools/mock_data.py` module. Each real tool function (`calcom.check_availability`, `book_slot`, etc.) gains an early-return guard returning realistic fake data matching its normal Pydantic return type — no changes needed to the LangGraph nodes that call them.

A companion `backend/scripts/chat.py` was added: a terminal chat client that drives the same `run_turn()` logic the Retell websocket uses, creating a real `calls` row so the conversation shows up on the dashboard like any other call. This became the primary tool for reproducing and verifying every bug below without needing a live phone call.

---

## 3. LangGraph turn-resume bug — the graph silently restarted every turn

This was the most serious bug in the codebase, and the hardest to notice by reading code alone, because the symptom looked like a working (if slightly odd) conversation.

**Symptom:** using the CLI chat script for a multi-turn conversation, replies sounded contextually plausible turn after turn, but `book_appointment` never actually ran — `call_outcome` stayed `null` no matter how the conversation went.

**Diagnosis:** instrumented a debug script to print `current_node` and `state.next` after every turn. It showed `current_node` stuck at `"greeting"` forever, on every single turn, regardless of what was said.

**Root cause:** the turn-execution function (`app/graph/runner.py`, originally inline in `llm_websocket.py`) resumed a paused (`interrupt_after`) thread like this:

```python
# WRONG
input_state = {"messages": [{"role": "user", "content": user_utterance}]}
result = await graph.ainvoke(input_state, config)
```

In LangGraph, passing a **non-`None`** value to `ainvoke()` on a thread is treated as fresh input to `START`, regardless of any existing checkpoint — it does not resume from the paused point. So every turn silently restarted the graph from `greeting`. The LLM's replies still sounded coherent because the accumulated message history (via the `messages` field's `add` reducer) kept growing and getting fed to the `greeting` node's prompt, which is generic enough to free-associate a plausible-sounding continuation — masking the fact that no real state-machine progress was happening.

**Fix:**

```python
# CORRECT
if user_utterance:
    await graph.aupdate_state(config, {"messages": [{"role": "user", "content": user_utterance}]})
result = await graph.ainvoke(None, config)
```

Update the checkpointed state first (the same way a node's return value would), then resume with `None`, which LangGraph correctly interprets as "continue from where this thread left off."

**Verification:** re-ran the same multi-turn conversation and confirmed `current_node`/`state.next` advanced correctly turn over turn (`greeting` → `collect_patient_info` → `collect_appointment_prefs` → `confirm_slot` → `book_appointment`, with `call_outcome` finally reaching `"booked"`).

---

## 4. Cal.com v2 API — four separate mismatches found via live testing

The scaffold's Cal.com integration was fully written and typed, but had never been run against a real Cal.com account. Once real credentials were available, `check_availability` failed immediately with `404 Cannot GET /v2/slots?...`. Comparing the code against Cal.com's current API docs (not the version the scaffold's TODO comment assumed) surfaced four distinct bugs:

| # | What the code did | What the API actually needs |
|---|---|---|
| 1 | Query params `startTime` / `endTime` | `start` / `end` |
| 2 | Parsed response as `data.slots[date]` | Response is `data[date]` directly (no `slots` nesting) |
| 3 | One `cal-api-version` header value for every endpoint | Cal.com versions **each endpoint independently** — slots lookup needs `2024-09-04`, the booking endpoints (`book`/`reschedule`/`cancel`) need `2026-02-25` |
| 4 | `eventTypeId` sent as a string in the booking JSON body | Booking creation requires it as a JSON **integer** — the slots GET endpoint accepts it as a query-string value either way, but `POST /v2/bookings` returned `400 eventTypeId must be an integer number` |
| 5 | `cancel_booking` sent `{"reason": ...}` | The field is `cancellationReason` |

**Verification:** live-tested all four Cal.com functions end-to-end against a real account — booked a real slot, rescheduled it, then cancelled it — confirming the fixed request/response shapes work, and cleaning up the test bookings afterward.

---

## 5. HubSpot integration — two real-world quirks, not code bugs

**Custom properties don't exist by default.** `upsert_contact` tries to set `chairside_appointment_type`, `chairside_insurance_provider`, and `chairside_last_call_notes` — these are custom contact properties that must be created in HubSpot (Settings → Properties → Contact properties) before the API call will accept them. Without them, HubSpot returns `400 PROPERTY_DOESNT_EXIST`. This was already flagged in the code's docstring; live testing just confirmed the exact failure mode. Contact creation/update with only standard properties (`phone`, `firstname`, `lastname`) was verified working immediately.

**Search index propagation lag.** Calling `upsert_contact` twice in quick succession for the same new phone number created two duplicate contacts instead of updating one. Root cause: HubSpot's contact **search** index (used by `_find_contact_by_phone` for dedupe) takes a few seconds to catch up after a create — an immediate re-search doesn't find the just-created contact. Confirmed by re-running the same raw search a few seconds later and seeing both contacts returned correctly. Not a code bug (real phone calls are naturally spaced out in time), but documented in `hubspot.py` since it's a non-obvious characteristic of the API.

---

## 6. Retell webhook signature verification used a fictional secret

**Symptom:** Retell's dashboard "Test webhook" button returned `401 Unauthorized`.

**Root cause, part 1:** the scaffold's `.env.example` had a `RETELL_WEBHOOK_SECRET` field that doesn't correspond to anything Retell actually issues. Retell has no separate webhook secret — webhooks are signed with an **API key that has the "webhook" badge** in the dashboard, distinct from a general-purpose API key.

**Root cause, part 2:** even after switching to the correct key, the hand-rolled verification (`hmac.new(secret, raw_body, sha256).hexdigest()`) didn't match Retell's actual scheme, which is:

- HMAC-SHA256 over the **raw body concatenated with a millisecond timestamp**, not the raw body alone
- header format `v={timestamp},d={hex_digest}`
- a **5-minute replay window**: signatures older than that are rejected regardless of correctness

**Fix:** rather than reimplementing this precisely (easy to get the timestamp concatenation or replay window subtly wrong), switched to Retell's official `retell-sdk` package and its `retell.lib.webhook_auth.verify()` function, which implements the exact scheme. Confirmed correct by decoding a real captured request from ngrok's local inspector and validating it against the real signing key.

---

## 7. Retell Custom LLM websocket — three protocol mismatches

The scaffold's `llm_websocket.py` had an explicit TODO acknowledging its message shapes were "commonly documented pattern, not checked against a live payload." Comparing against Retell's own reference implementation (`RetellAI/retell-custom-llm-python-demo`) surfaced three real gaps:

1. **Missing required `config` message.** Retell does not send the `call_details` event (which carries the caller's phone number) unless the server first sends `{"response_type": "config", "config": {"call_details": true, ...}}` immediately after accepting the connection.
2. **Caller phone number doesn't arrive via query params.** The scaffold read `websocket.query_params.get("caller_phone")` — Retell never sends it that way. It only arrives in the `call_details` event's `call.from_number` field, and only once the config opt-in above is sent.
3. **Missing `response_type` field on every outbound message.** Every message sent back to Retell needs an explicit `response_type` (`"config"` | `"ping_pong"` | `"response"`); the scaffold's response messages omitted it entirely.

**Fix:** send the config message on connect; capture caller phone from `call_details` and backfill both the `calls` row and the LangGraph checkpoint state (`graph.aupdate_state(config, {"caller_phone": ...})`) once it arrives, since the call row is created before the phone number is known; add `response_type` to every outbound message.

**Verification:** a local smoke test using `TestClient.websocket_connect()` drives the full handshake (config → greeting → `call_details` → `ping_pong` → `response_required`) against the real app, asserting each message shape — then the same sequence was confirmed against the live server through the ngrok tunnel before pointing a real Retell agent at it.

---

## 8. `detect_intent` escalation dead end

**Symptom:** in a live Retell test call, opening with "Hi, how are you?" caused every subsequent message — including explicitly stating "I want to book an appointment" — to get the same frozen, unrelated reply ("I'm doing great, thank you!... Have a wonderful day!").

**Root cause:** the intent-classification prompt instructed the LLM: *"Use 'escalation' for ... anything you are not confident the other intents cover."* Small talk before stating a real request doesn't match `new_booking`/`reschedule`/`faq`, so the classifier defaulted to `escalation`. The graph has no recovery path out of escalation — `escalate → closing → END` is a dead end, unlike the FAQ path (which loops back to `detect_intent`). Once the graph reached `END`, every further turn resumed a completed thread with nothing left to execute, so `run_turn()` just kept returning the same frozen last message.

**Fix:** two changes, reusing the graph's existing retry-loop convention (used elsewhere for slot-filling):

- Narrowed the prompt: `escalation` is now reserved for genuinely urgent/complaint content; ambiguous input gets a new `unclear` label.
- Added a `clarify_intent` node — a proper conversational node (distinct from the silent `detect_intent` classifier, since LangGraph's static `interrupt_after` can't pause *conditionally*) that asks a clarifying question and loops back to `detect_intent` for re-classification, capped at 3 retries before escalating — the same pattern already used by `collect_patient_info` and friends.

**Verification:** reproduced the exact failing conversation via the CLI chat script first (confirmed the dead end), applied the fix, reproduced the identical scenario again and confirmed it now asks a clarifying question and correctly proceeds into booking once real intent is stated. Locked in with new tests in `test_graph_edges.py`.

---

## 9. Reconnect handling — the websocket handler re-advanced state on every reconnect

**Symptom:** in a longer live Retell test call, the agent got stuck repeating one canned response verbatim regardless of what the caller said afterward — including when the caller gave their full name, phone, and email.

**Diagnosis:** ngrok's local request inspector (`localhost:4040`) showed the **same** Retell call establishing five separate websocket connections over about 70 seconds — Retell's `auto_reconnect` feature reconnecting periodically.

**Root cause:** the websocket handler unconditionally ran a "greeting" turn (`run_turn(..., user_utterance=None)`) immediately after every connection, including reconnects of an already-in-progress call. On a stateful LangGraph thread, invoking a turn with no new input doesn't just re-send a greeting — it resumes the graph and lets whatever node is next execute again with **unchanged** state, generating a fresh (but near-identical, given low LLM temperature) reply completely independent of what the caller actually said in the meantime.

**Fix:** check whether the thread already has state *before* deciding to run a turn at all:

```python
existing_state = await graph.aget_state(thread_config(internal_call_id))
if not existing_state.values:
    # genuinely new call -- greet
    ...
# else: reconnect of an in-progress call -- say nothing, wait for real input
```

**Verification:** simulated the exact scenario (connect → greet → disconnect → reconnect on the same call id) against the live server and confirmed only the `config` message is sent on reconnect — no spurious re-greeting — while a real caller utterance sent afterward still produces the correct reply.

---

## Summary

| Issue | Root cause | Verified via |
|---|---|---|
| Dashboard 404s | Routes never existed | `curl` against live endpoints |
| Graph frozen at `greeting` | Non-`None` input to `ainvoke()` restarts from `START` instead of resuming | Debug script tracking `current_node`/`state.next` across turns |
| Cal.com `404`/`400` errors | Stale/incorrect param names, response shape, per-endpoint API version, `eventTypeId` type | Live book → reschedule → cancel cycle |
| HubSpot `400`/duplicate contacts | Missing custom properties; search-index propagation lag | Live contact create/update/search |
| Webhook `401` | Fictional secret concept; hand-rolled HMAC didn't match Retell's timestamped scheme | Replayed a captured real signature against the fix |
| Websocket handshake silently broken | Missing `config` message, wrong phone-number source, missing `response_type` | `TestClient` smoke test + live tunnel test |
| Permanent escalation on small talk | Overly aggressive escalation prompt + no recovery path from `escalate` | Reproduced exact failing conversation, then re-ran after fix |
| Frozen/repeating replies | Reconnects silently re-advanced graph state | Reconnect simulation against live server |

**General lesson:** almost none of these bugs were visible from reading the code in isolation — the code was well-typed, reasonably documented, and even had TODO comments flagging some of the exact risk areas ("verify against a live payload," "confirm response shape once real credentials exist"). Every one of them only surfaced by actually running the system against live traffic — a local multi-turn conversation, a real API call, a real webhook request, a real (if flaky) websocket connection — and instrumenting enough to see the actual data flowing through, rather than trusting that scaffolded/documented-pattern code was correct by construction.
