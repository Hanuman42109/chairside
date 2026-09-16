import json
from pathlib import Path

from app.eval.evaluator import evaluate_call

FIXTURES_DIR = Path(__file__).parent.parent / "app" / "eval" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_new_booking_fixture_scores_perfectly():
    result = evaluate_call(_load("sample_new_booking.json"))
    assert result.slot_filling_accuracy == 1.0
    assert result.escalation_correctness == 1.0
    assert result.overall_score == 1.0


def test_escalation_fixture_scores_perfectly():
    result = evaluate_call(_load("sample_escalation.json"))
    assert result.escalation_correctness == 1.0
    assert result.overall_score == 1.0


def test_missing_required_slot_lowers_score():
    fixture = _load("sample_new_booking.json")
    fixture["expected"]["required_slots"]["patient_first_name"] = "Someone Else Entirely"
    result = evaluate_call(fixture)
    assert result.slot_filling_accuracy < 1.0


def test_escalation_mismatch_is_penalized():
    fixture = _load("sample_new_booking.json")
    fixture["expected"]["escalation_expected"] = True
    result = evaluate_call(fixture)
    assert result.escalation_correctness == 0.0
