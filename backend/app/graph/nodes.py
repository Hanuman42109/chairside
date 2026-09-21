"""LangGraph node implementations.

Convention used throughout: a node either (a) talks to the caller ("conversational"
nodes -- append one assistant message to `messages`), or (b) calls exactly one
external tool ("tool" nodes -- calcom/hubspot/twilio/faq_kb). Nodes never decide
where to go next; that's edges.py's job, based on the state a node leaves behind.

On any tool failure or unresolvable state, a node sets `escalation_reason` instead of
raising -- edges.py checks for that and routes to `escalate` uniformly (see
`edges.route_or_escalate`), so escalation policy lives in one place.
"""

import json
from datetime import date
from typing import Any

from langchain_core.messages import SystemMessage

from app.config import get_settings
from app.graph import prompts
from app.graph.state import BookingState
from app.graph.utils import bump_retry, last_user_message, to_langchain_messages
from app.tools import calcom, faq_kb, hubspot, twilio_sms
from app.tools.llm import get_chat_model

# --- Shared helpers -----------------------------------------------------------


async def _converse(state: BookingState, system_prompt: str, node_name: str, extra_context: str | None = None) -> dict:
    """Run one LLM turn: system prompt (+ optional extra context) + history -> reply."""
    llm = get_chat_model()
    system = system_prompt if not extra_context else f"{system_prompt}\n\n{extra_context}"
    messages = [SystemMessage(content=system)] + to_langchain_messages(state)
    response = await llm.ainvoke(messages)
    return {
        "messages": [{"role": "assistant", "content": response.content}],
        "current_node": node_name,
    }


async def _extract_fields(state: BookingState, instruction: str, fields: list[str]) -> dict[str, Any]:
    """Ask the LLM to pull structured fields out of the conversation so far.

    Returns {} (or a partial dict) for whatever it isn't confident about --
    callers must treat missing keys as "still unknown", never overwrite
    existing state with blanks.
    """
    llm = get_chat_model(temperature=0)
    system = (
        f"{instruction}\n\nFrom the conversation so far, extract these fields if known: "
        f"{', '.join(fields)}. Respond with ONLY a JSON object containing keys for "
        "fields you are confident about. Omit keys you don't know -- do not guess."
    )
    messages = [SystemMessage(content=system)] + to_langchain_messages(state)
    response = await llm.ainvoke(messages)
    try:
        parsed = json.loads(response.content)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# --- Greeting / routing --------------------------------------------------------


async def greeting(state: BookingState) -> dict:
    return await _converse(state, prompts.greeting_prompt(), "greeting")


async def detect_intent(state: BookingState) -> dict:
    llm = get_chat_model(temperature=0)
    messages = [SystemMessage(content=prompts.detect_intent_prompt())] + to_langchain_messages(state)
    response = await llm.ainvoke(messages)
    label = str(response.content).strip().lower()
    intent = label if label in ("new_booking", "reschedule", "faq", "escalation") else "escalation"
    update: dict[str, Any] = {"intent": intent, "current_node": "detect_intent"}
    if intent == "escalation":
        update["escalation_reason"] = "Caller intent classified as needing escalation."
    return update


# --- New booking ----------------------------------------------------------------


async def collect_patient_info(state: BookingState) -> dict:
    reply_update = await _converse(state, prompts.collect_patient_info_prompt(), "collect_patient_info")
    fields = await _extract_fields(
        state,
        prompts.collect_patient_info_prompt(),
        ["patient_first_name", "patient_last_name", "is_new_patient", "insurance_provider"],
    )
    return {**reply_update, **fields, **bump_retry(state, "collect_patient_info")}


async def collect_appointment_prefs(state: BookingState) -> dict:
    reply_update = await _converse(state, prompts.collect_appointment_prefs_prompt(), "collect_appointment_prefs")
    fields = await _extract_fields(
        state,
        prompts.collect_appointment_prefs_prompt(),
        ["appointment_type", "preferred_date", "preferred_time_of_day"],
    )
    return {**reply_update, **fields, **bump_retry(state, "collect_appointment_prefs")}


async def check_availability(state: BookingState) -> dict:
    try:
        preferred = date.fromisoformat(state["preferred_date"])
    except (KeyError, ValueError):
        return {
            "escalation_reason": "Could not parse a valid preferred_date before checking availability.",
            "current_node": "check_availability",
        }

    slots = await calcom.check_availability(preferred)
    if not slots:
        return {
            "available_slots": [],
            "escalation_reason": f"No open slots found for {preferred.isoformat()}.",
            "current_node": "check_availability",
        }
    return {"available_slots": [s.model_dump() for s in slots], "current_node": "check_availability"}


async def confirm_slot(state: BookingState) -> dict:
    slots = state.get("available_slots") or []
    if not slots:
        return {"escalation_reason": "confirm_slot reached with no available_slots.", "current_node": "confirm_slot"}

    proposed = state.get("selected_slot") or slots[0]
    reply_update = await _converse(
        state, prompts.confirm_slot_prompt(), "confirm_slot", extra_context=f"Proposed slot: {proposed}"
    )
    return {**reply_update, "selected_slot": proposed, **bump_retry(state, "confirm_slot")}


async def book_appointment(state: BookingState) -> dict:
    slot = state.get("selected_slot")
    if not slot:
        return {"escalation_reason": "book_appointment reached with no selected_slot.", "current_node": "book_appointment"}

    try:
        result = await calcom.book_slot(
            slot_start=slot["start"],
            attendee_name=f"{state.get('patient_first_name', '')} {state.get('patient_last_name', '')}".strip(),
            attendee_email=state.get("patient_email", ""),
            attendee_phone=state["caller_phone"],
        )
    except calcom.CalComError as exc:
        return {"escalation_reason": f"Booking failed: {exc}", "current_node": "book_appointment"}

    return {
        "booking_uid": result.booking_uid,
        "booking_confirmed": True,
        "call_outcome": "booked",
        "current_node": "book_appointment",
    }


async def create_crm_contact(state: BookingState) -> dict:
    try:
        result = await hubspot.upsert_contact(
            phone=state["caller_phone"],
            first_name=state.get("patient_first_name", ""),
            last_name=state.get("patient_last_name", ""),
            appointment_type=state.get("appointment_type"),
            insurance_provider=state.get("insurance_provider"),
        )
    except hubspot.HubSpotError as exc:
        # Booking already succeeded -- a CRM hiccup shouldn't derail the caller's
        # experience, so we log and continue rather than escalate.
        return {"crm_contact_id": "", "current_node": "create_crm_contact", "last_tool_error": str(exc)}

    return {"crm_contact_id": result.contact_id, "current_node": "create_crm_contact"}


async def send_confirmation_sms(state: BookingState) -> dict:
    settings = get_settings()
    slot = state.get("selected_slot") or {}
    body = twilio_sms.build_booking_confirmation_text(
        patient_first_name=state.get("patient_first_name", "there"),
        appointment_start_local=slot.get("start", "your requested time"),
        office_name=settings.office_name,
    )
    try:
        await twilio_sms.send_sms(to=state["caller_phone"], body=body)
    except twilio_sms.TwilioError as exc:
        return {"sms_sent": False, "current_node": "send_confirmation_sms", "last_tool_error": str(exc)}

    return {"sms_sent": True, "current_node": "send_confirmation_sms"}


# --- Reschedule -------------------------------------------------------------------


async def lookup_existing_appointment(state: BookingState) -> dict:
    """Look up the caller's most recent confirmed booking by phone number
    (local `calls`/`sessions` history -- no Cal.com round-trip needed)."""
    from app.db import repository  # local import: keeps this module's top-level imports tool/LLM-only

    match = await repository.find_latest_booked_call(
        state["caller_phone"], exclude_call_id=state.get("call_id")
    )
    if match is None or not match["graph_state"].get("booking_uid"):
        return {
            "escalation_reason": "No existing booking found on file for this phone number.",
            "current_node": "lookup_existing_appointment",
        }

    found_state = match["graph_state"]
    slot = found_state.get("selected_slot") or {}
    reply_update = await _converse(
        state,
        "Tell the caller you found their existing appointment and confirm it's the "
        "one they mean before asking what new time they'd like.",
        "lookup_existing_appointment",
        extra_context=(
            f"Existing appointment on file: {found_state.get('appointment_type', 'appointment')} "
            f"at {slot.get('start', 'an unknown time')}."
        ),
    )
    return {
        **reply_update,
        "existing_booking_uid": found_state["booking_uid"],
        "appointment_type": found_state.get("appointment_type", ""),
        "current_node": "lookup_existing_appointment",
    }


async def collect_new_time(state: BookingState) -> dict:
    reply_update = await _converse(state, prompts.collect_new_time_prompt(), "collect_new_time")
    fields = await _extract_fields(
        state, prompts.collect_new_time_prompt(), ["preferred_date", "preferred_time_of_day"]
    )
    return {**reply_update, **fields, **bump_retry(state, "collect_new_time")}


async def confirm_reschedule(state: BookingState) -> dict:
    slots = state.get("available_slots") or []
    if not slots:
        return {"escalation_reason": "confirm_reschedule reached with no available_slots.", "current_node": "confirm_reschedule"}

    proposed = state.get("selected_slot") or slots[0]
    reply_update = await _converse(
        state, prompts.confirm_reschedule_prompt(), "confirm_reschedule", extra_context=f"Proposed new slot: {proposed}"
    )
    return {**reply_update, "selected_slot": proposed, **bump_retry(state, "confirm_reschedule")}


async def update_booking(state: BookingState) -> dict:
    slot = state.get("selected_slot")
    booking_uid = state.get("existing_booking_uid")
    if not slot or not booking_uid:
        return {"escalation_reason": "update_booking reached without a slot/booking_uid.", "current_node": "update_booking"}

    try:
        result = await calcom.reschedule_booking(booking_uid, slot["start"])
    except calcom.CalComError as exc:
        return {"escalation_reason": f"Reschedule failed: {exc}", "current_node": "update_booking"}

    return {
        "booking_uid": result.booking_uid,
        "booking_confirmed": True,
        "call_outcome": "rescheduled",
        "current_node": "update_booking",
    }


# --- FAQ ---------------------------------------------------------------------------


async def faq_lookup(state: BookingState) -> dict:
    question = state.get("faq_question") or last_user_message(state)
    result = faq_kb.query_faq(question)
    if result is None:
        return {"escalation_reason": f"No confident FAQ match for: {question!r}", "current_node": "faq_lookup"}
    return {"faq_answer": result.answer, "current_node": "faq_lookup"}


async def answer_faq(state: BookingState) -> dict:
    if not state.get("faq_answer"):
        return {"escalation_reason": "answer_faq reached with no faq_answer.", "current_node": "answer_faq"}
    reply_update = await _converse(state, prompts.answer_faq_prompt(state["faq_answer"]), "answer_faq")
    return {**reply_update, "call_outcome": "faq_only"}


async def anything_else(state: BookingState) -> dict:
    return await _converse(
        state, "Ask the caller if there's anything else you can help with today.", "anything_else"
    )


# --- Escalation / closing -----------------------------------------------------------


async def escalate(state: BookingState) -> dict:
    reason = state.get("escalation_reason") or "Unspecified -- caller needs human follow-up."
    reply_update = await _converse(state, prompts.escalation_prompt(reason), "escalate")
    return {**reply_update, "escalated": True, "call_outcome": state.get("call_outcome") or "escalated"}


async def closing(state: BookingState) -> dict:
    return await _converse(state, prompts.closing_prompt(), "closing")
