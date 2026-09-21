"""Conditional edge (routing) functions.

Nodes act; edges decide what happens next. Keeping routing here (rather than
inline in nodes.py) means the whole flow's control logic can be read in one
file, next to graph.py where it's wired up.

Two small pieces of routing logic need a yes/no read on the caller's last
reply (confirming a slot, or "anything else?"). Rather than have every
conversational node parse its own answer, that classification lives here as
a tiny dedicated LLM call -- cheap (temperature=0, short output) and keeps
nodes.py focused on "what to say / which tool to call".
"""

from typing import Literal

from langchain_core.messages import SystemMessage

from app.graph.state import BookingState
from app.graph.utils import retry_count_for, to_langchain_messages
from app.tools.llm import get_chat_model

MAX_RETRIES = 3


def route_or_escalate(next_node: str):
    """Factory: if the node we just ran flagged an escalation_reason, go to
    `escalate`; otherwise continue to `next_node`. Used after every tool-calling
    node so failure handling is uniform and defined in exactly one place.
    """

    def _route(state: BookingState) -> str:
        if state.get("escalation_reason") and not state.get("escalated"):
            return "escalate"
        return next_node

    return _route


def _loop_or_escalate(state: BookingState, self_node: str) -> str:
    """Re-ask via `self_node` until its own retry budget (MAX_RETRIES) is
    exhausted, then escalate -- guards against an unresolvable back-and-forth
    with the caller at a single step."""
    if state.get("escalation_reason"):
        return "escalate"
    if retry_count_for(state, self_node) >= MAX_RETRIES:
        return "escalate"
    return self_node


async def _classify_yes_no(state: BookingState, question: str) -> Literal["yes", "no", "unclear"]:
    llm = get_chat_model(temperature=0)
    system = (
        f"{question} Based on the caller's most recent message, respond with exactly "
        "one word: 'yes', 'no', or 'unclear'."
    )
    messages = [SystemMessage(content=system)] + to_langchain_messages(state)
    response = await llm.ainvoke(messages)
    label = str(response.content).strip().lower()
    return label if label in ("yes", "no", "unclear") else "unclear"


# --- Routers, one per node with a conditional edge -----------------------------------


def route_after_detect_intent(state: BookingState) -> str:
    if state.get("escalation_reason"):
        return "escalate"
    return {
        "new_booking": "collect_patient_info",
        "reschedule": "lookup_existing_appointment",
        "faq": "faq_lookup",
        "unclear": "clarify_intent",
    }.get(state.get("intent"), "escalate")


def route_after_clarify_intent(state: BookingState) -> str:
    if retry_count_for(state, "clarify_intent") >= MAX_RETRIES:
        return "escalate"
    return "detect_intent"


def route_after_collect_patient_info(state: BookingState) -> str:
    have_all = bool(state.get("patient_first_name") and state.get("insurance_provider") is not None)
    return "collect_appointment_prefs" if have_all else _loop_or_escalate(state, "collect_patient_info")


def route_after_collect_appointment_prefs(state: BookingState) -> str:
    have_all = bool(state.get("appointment_type") and state.get("preferred_date"))
    return "check_availability" if have_all else _loop_or_escalate(state, "collect_appointment_prefs")


def route_after_check_availability(state: BookingState) -> str:
    if state.get("escalation_reason"):
        return "escalate"
    return "confirm_reschedule" if state.get("intent") == "reschedule" else "confirm_slot"


async def route_after_confirm_slot(state: BookingState) -> str:
    if state.get("escalation_reason"):
        return "escalate"
    answer = await _classify_yes_no(state, "Did the caller confirm the proposed appointment time?")
    if answer == "yes":
        return "book_appointment"
    return _loop_or_escalate(state, "confirm_slot")


route_after_book_appointment = route_or_escalate("create_crm_contact")
route_after_create_crm_contact = route_or_escalate("send_confirmation_sms")
route_after_send_confirmation_sms = route_or_escalate("closing")

route_after_lookup_existing_appointment = route_or_escalate("collect_new_time")


def route_after_collect_new_time(state: BookingState) -> str:
    have_all = bool(state.get("preferred_date"))
    return "check_availability" if have_all else _loop_or_escalate(state, "collect_new_time")


async def route_after_confirm_reschedule(state: BookingState) -> str:
    if state.get("escalation_reason"):
        return "escalate"
    answer = await _classify_yes_no(state, "Did the caller confirm the proposed new appointment time?")
    if answer == "yes":
        return "update_booking"
    return _loop_or_escalate(state, "confirm_reschedule")


route_after_update_booking = route_or_escalate("send_confirmation_sms")
route_after_faq_lookup = route_or_escalate("answer_faq")


async def route_after_anything_else(state: BookingState) -> str:
    answer = await _classify_yes_no(state, "Does the caller want help with anything else?")
    return "detect_intent" if answer == "yes" else "closing"
