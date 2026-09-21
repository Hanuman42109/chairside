from app.graph import edges
from app.graph.utils import bump_retry


def test_route_after_detect_intent_dispatches_by_intent():
    assert edges.route_after_detect_intent({"intent": "new_booking"}) == "collect_patient_info"
    assert edges.route_after_detect_intent({"intent": "reschedule"}) == "lookup_existing_appointment"
    assert edges.route_after_detect_intent({"intent": "faq"}) == "faq_lookup"
    assert edges.route_after_detect_intent({"intent": "escalation"}) == "escalate"
    assert edges.route_after_detect_intent({"intent": None}) == "escalate"


def test_route_after_detect_intent_respects_escalation_reason():
    assert edges.route_after_detect_intent({"intent": "new_booking", "escalation_reason": "x"}) == "escalate"


def test_route_after_detect_intent_sends_unclear_to_clarify_intent():
    assert edges.route_after_detect_intent({"intent": "unclear"}) == "clarify_intent"


def test_route_after_clarify_intent_loops_then_escalates():
    state: dict = {}
    assert edges.route_after_clarify_intent(state) == "detect_intent"

    for _ in range(edges.MAX_RETRIES):
        state.update(bump_retry(state, "clarify_intent"))
    assert edges.route_after_clarify_intent(state) == "escalate"


def test_route_after_collect_patient_info_loops_until_complete():
    incomplete = {"patient_first_name": "Jane"}  # insurance_provider missing
    assert edges.route_after_collect_patient_info(incomplete) == "collect_patient_info"

    complete = {"patient_first_name": "Jane", "insurance_provider": "Delta Dental"}
    assert edges.route_after_collect_patient_info(complete) == "collect_appointment_prefs"


def test_route_after_collect_patient_info_escalates_after_max_retries():
    state = {"patient_first_name": "Jane"}
    for _ in range(edges.MAX_RETRIES):
        state.update(bump_retry(state, "collect_patient_info"))
    assert edges.route_after_collect_patient_info(state) == "escalate"


def test_route_after_check_availability_branches_on_intent():
    assert edges.route_after_check_availability({"intent": "reschedule"}) == "confirm_reschedule"
    assert edges.route_after_check_availability({"intent": "new_booking"}) == "confirm_slot"
    assert edges.route_after_check_availability({"intent": "new_booking", "escalation_reason": "no slots"}) == "escalate"


def test_route_or_escalate_factory():
    router = edges.route_or_escalate("create_crm_contact")
    assert router({}) == "create_crm_contact"
    assert router({"escalation_reason": "booking failed"}) == "escalate"
    # Already escalated -- don't re-route into escalate again.
    assert router({"escalation_reason": "booking failed", "escalated": True}) == "create_crm_contact"


def test_retry_counts_are_isolated_per_node():
    state: dict = {}
    state.update(bump_retry(state, "collect_patient_info"))
    state.update(bump_retry(state, "collect_patient_info"))
    state.update(bump_retry(state, "confirm_slot"))

    assert state["node_visit_counts"]["collect_patient_info"] == 2
    assert state["node_visit_counts"]["confirm_slot"] == 1
