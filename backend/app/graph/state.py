"""LangGraph state schema for the booking conversation.

This TypedDict is the single source of truth for what the graph tracks
across turns. It is also what gets persisted to the `sessions.graph_state`
JSONB column (see app/db/repository.py) so a call can be inspected or
resumed after the fact.
"""

from operator import add
from typing import Annotated, Literal, TypedDict

Intent = Literal["new_booking", "reschedule", "faq", "escalation", None]

ConversationMessage = dict[str, str]  # {"role": "user" | "assistant", "content": "..."}


class BookingState(TypedDict, total=False):
    # --- Call identity ---
    call_id: str
    caller_phone: str

    # --- Conversation ---
    # `add` reducer: nodes append messages rather than overwrite the list.
    messages: Annotated[list[ConversationMessage], add]
    current_node: str
    # Per-node re-ask counters (e.g. {"collect_patient_info": 2}), so a caller
    # struggling at one step doesn't burn through the retry budget of another.
    node_visit_counts: dict[str, int]

    # --- Intent routing ---
    intent: Intent

    # --- Patient / slot-filling fields ---
    patient_first_name: str
    patient_last_name: str
    patient_email: str
    is_new_patient: bool
    insurance_provider: str
    appointment_type: str  # e.g. "cleaning", "emergency", "checkup"
    preferred_date: str  # ISO date, as understood from caller speech
    preferred_time_of_day: str  # "morning" | "afternoon" | "evening" | free text

    # --- Availability / booking ---
    available_slots: list[dict]  # serialized TimeSlot
    selected_slot: dict | None  # serialized TimeSlot
    booking_uid: str  # Cal.com booking id once confirmed
    booking_confirmed: bool

    # --- Reschedule-specific ---
    existing_booking_uid: str

    # --- FAQ ---
    faq_question: str
    faq_answer: str

    # --- Post-booking side effects ---
    crm_contact_id: str
    sms_sent: bool
    # Set by a node whose tool call failed but which chose to continue rather
    # than escalate (e.g. CRM upsert or SMS send after a successful booking).
    last_tool_error: str

    # --- Escalation ---
    escalation_reason: str
    escalated: bool

    # --- Terminal ---
    call_outcome: Literal[
        "booked", "rescheduled", "escalated", "faq_only", "abandoned", None
    ]


def new_state(call_id: str, caller_phone: str) -> BookingState:
    """Construct the initial state for a fresh call."""
    return BookingState(
        call_id=call_id,
        caller_phone=caller_phone,
        messages=[],
        current_node="greeting",
        node_visit_counts={},
        intent=None,
        booking_confirmed=False,
        sms_sent=False,
        escalated=False,
        call_outcome=None,
    )
