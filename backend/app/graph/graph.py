"""Assembles the booking conversation as a LangGraph StateGraph.

Turn-taking model
------------------
Retell calls our backend once per caller utterance (see
app/routes/llm_websocket.py). Each call resumes the SAME graph run (keyed by
`thread_id=call_id` in the checkpointer) rather than starting a fresh one, so
state persists across turns.

Every node that produces caller-facing speech is listed in
`INTERRUPT_AFTER_NODES`. LangGraph pauses immediately after such a node runs
and returns control to us -- we send that message to the caller over the
websocket and wait. The *next* utterance is fed back in as new input on the
same thread, which resumes execution starting with the conditional edge
right after the interrupted node (now evaluated against state that includes
the caller's new reply), and continues -- silently running any tool-only
nodes -- until it hits the next conversational node.

Nodes that only call a tool (check_availability, book_appointment,
create_crm_contact, send_confirmation_sms, update_booking, faq_lookup,
detect_intent) are deliberately NOT in that list: they run straight through
to whatever comes next within the same turn.

Checkpointer
------------
`MemorySaver` is fine for local dev but is process-local, in-memory state --
it will not survive a Render free-tier dyno restart/redeploy, and won't work
across multiple worker processes. Before relying on multi-turn calls in
production, swap this for `langgraph.checkpoint.postgres.AsyncPostgresSaver`
pointed at the same Supabase database (see app/db/client.py). We also persist
a redundant snapshot of `graph_state` to the `sessions` table on every turn
(app/db/repository.py) purely for the dashboard/debugging -- that is not a
substitute for a real checkpointer.
"""

from functools import lru_cache

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph import edges, nodes
from app.graph.state import BookingState

INTERRUPT_AFTER_NODES = [
    "greeting",
    "clarify_intent",
    "collect_patient_info",
    "collect_appointment_prefs",
    "confirm_slot",
    "lookup_existing_appointment",
    "collect_new_time",
    "confirm_reschedule",
    "answer_faq",
    "anything_else",
    "escalate",
    "closing",
]


def build_graph() -> StateGraph:
    graph = StateGraph(BookingState)

    for name, fn in [
        ("greeting", nodes.greeting),
        ("detect_intent", nodes.detect_intent),
        ("clarify_intent", nodes.clarify_intent),
        ("collect_patient_info", nodes.collect_patient_info),
        ("collect_appointment_prefs", nodes.collect_appointment_prefs),
        ("check_availability", nodes.check_availability),
        ("confirm_slot", nodes.confirm_slot),
        ("book_appointment", nodes.book_appointment),
        ("create_crm_contact", nodes.create_crm_contact),
        ("send_confirmation_sms", nodes.send_confirmation_sms),
        ("lookup_existing_appointment", nodes.lookup_existing_appointment),
        ("collect_new_time", nodes.collect_new_time),
        ("confirm_reschedule", nodes.confirm_reschedule),
        ("update_booking", nodes.update_booking),
        ("faq_lookup", nodes.faq_lookup),
        ("answer_faq", nodes.answer_faq),
        ("anything_else", nodes.anything_else),
        ("escalate", nodes.escalate),
        ("closing", nodes.closing),
    ]:
        graph.add_node(name, fn)

    # --- Deterministic edges ---
    graph.add_edge(START, "greeting")
    graph.add_edge("greeting", "detect_intent")
    graph.add_edge("answer_faq", "anything_else")
    graph.add_edge("escalate", "closing")
    graph.add_edge("closing", END)

    # --- Conditional edges ---
    graph.add_conditional_edges(
        "detect_intent",
        edges.route_after_detect_intent,
        {
            "collect_patient_info": "collect_patient_info",
            "lookup_existing_appointment": "lookup_existing_appointment",
            "faq_lookup": "faq_lookup",
            "clarify_intent": "clarify_intent",
            "escalate": "escalate",
        },
    )
    graph.add_conditional_edges(
        "clarify_intent",
        edges.route_after_clarify_intent,
        {"detect_intent": "detect_intent", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "collect_patient_info",
        edges.route_after_collect_patient_info,
        {"collect_appointment_prefs": "collect_appointment_prefs", "collect_patient_info": "collect_patient_info", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "collect_appointment_prefs",
        edges.route_after_collect_appointment_prefs,
        {"check_availability": "check_availability", "collect_appointment_prefs": "collect_appointment_prefs", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "check_availability",
        edges.route_after_check_availability,
        {"confirm_slot": "confirm_slot", "confirm_reschedule": "confirm_reschedule", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "confirm_slot",
        edges.route_after_confirm_slot,
        {"book_appointment": "book_appointment", "confirm_slot": "confirm_slot", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "book_appointment",
        edges.route_after_book_appointment,
        {"create_crm_contact": "create_crm_contact", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "create_crm_contact",
        edges.route_after_create_crm_contact,
        {"send_confirmation_sms": "send_confirmation_sms", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "send_confirmation_sms",
        edges.route_after_send_confirmation_sms,
        {"closing": "closing", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "lookup_existing_appointment",
        edges.route_after_lookup_existing_appointment,
        {"collect_new_time": "collect_new_time", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "collect_new_time",
        edges.route_after_collect_new_time,
        {"check_availability": "check_availability", "collect_new_time": "collect_new_time", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "confirm_reschedule",
        edges.route_after_confirm_reschedule,
        {"update_booking": "update_booking", "confirm_reschedule": "confirm_reschedule", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "update_booking",
        edges.route_after_update_booking,
        {"send_confirmation_sms": "send_confirmation_sms", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "faq_lookup",
        edges.route_after_faq_lookup,
        {"answer_faq": "answer_faq", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "anything_else",
        edges.route_after_anything_else,
        {"detect_intent": "detect_intent", "closing": "closing"},
    )

    return graph


@lru_cache
def get_compiled_graph():
    """Compile once per process. Swap MemorySaver for a Postgres checkpointer
    before relying on this across restarts/multiple workers -- see module docstring.
    """
    return build_graph().compile(checkpointer=MemorySaver(), interrupt_after=INTERRUPT_AFTER_NODES)
