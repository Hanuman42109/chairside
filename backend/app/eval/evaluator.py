"""Heuristic scoring for a call transcript against an expected outcome.

Fixture format (see app/eval/fixtures/*.json):
{
  "call_id": "...",
  "transcript": [{"role": "user" | "assistant", "content": "..."}],
  "final_state": { ...optional LangGraph state snapshot at end of call... },
  "expected": {
    "intent": "new_booking" | "reschedule" | "faq" | "escalation",
    "required_slots": {"patient_first_name": "Jane", "appointment_type": "cleaning", ...},
    "ground_truth_available_slots": ["2026-09-22T14:00:00-04:00", ...],
    "escalation_expected": false,
    "expected_outcome": "booked" | "rescheduled" | "escalated" | "faq_only" | "abandoned"
  }
}

These are deliberately simple, deterministic heuristics (substring/keyword
matching), NOT an LLM-as-judge -- that keeps the eval script free, fast, and
reproducible. The natural upgrade path is to add an optional LLM-judge pass
(reusing app.tools.llm.get_chat_model) for nuance these heuristics miss;
that's flagged inline below rather than built now, to keep this scaffold's
default cost at $0.
"""

import re
from dataclasses import dataclass, field

TIME_TOKEN_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", re.IGNORECASE)


@dataclass
class EvalResult:
    slot_filling_accuracy: float
    hallucination_score: float  # 1.0 = no detected hallucination, 0.0 = worst
    escalation_correctness: float  # 1.0 or 0.0 (binary: did it escalate iff expected)
    overall_score: float
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "slot_filling_accuracy": self.slot_filling_accuracy,
            "hallucination_score": self.hallucination_score,
            "escalation_correctness": self.escalation_correctness,
            "overall_score": self.overall_score,
            "notes": "; ".join(self.notes),
        }


def _assistant_text(transcript: list[dict]) -> str:
    return " ".join(m["content"] for m in transcript if m.get("role") == "assistant").lower()


def score_slot_filling(transcript: list[dict], final_state: dict | None, required_slots: dict) -> tuple[float, list[str]]:
    """Fraction of required_slots whose expected value shows up somewhere the
    agent could plausibly have captured it -- prefer `final_state` (the actual
    captured value) when available, else fall back to searching the transcript
    text (weaker signal: proves the value was *said*, not that it was stored).
    """
    if not required_slots:
        return 1.0, ["No required_slots specified; trivially 1.0."]

    notes = []
    hits = 0
    haystack = _assistant_text(transcript) + " " + " ".join(
        m["content"] for m in transcript if m.get("role") == "user"
    ).lower()

    for field_name, expected_value in required_slots.items():
        expected_str = str(expected_value).strip().lower()
        state_value = str((final_state or {}).get(field_name, "")).strip().lower()

        if state_value and state_value == expected_str:
            hits += 1
        elif expected_str and expected_str in haystack:
            hits += 1
            notes.append(f"{field_name}: matched via transcript text, not final_state.")
        else:
            notes.append(f"{field_name}: expected {expected_value!r} not found.")

    return hits / len(required_slots), notes


def score_hallucination(transcript: list[dict], ground_truth_available_slots: list[str] | None) -> tuple[float, list[str]]:
    """Flag when the agent states a specific time as available that isn't in
    ground_truth_available_slots. This is a coarse heuristic (regex time-token
    matching), meant to catch egregious invented availability, not to be a
    precise fact-checker.
    """
    if ground_truth_available_slots is None:
        return 1.0, ["No ground_truth_available_slots provided; skipped."]

    assistant_text = _assistant_text(transcript)
    mentioned_times = TIME_TOKEN_RE.findall(assistant_text)

    if not mentioned_times:
        return 1.0, ["No specific times mentioned by the agent."]

    # Heuristic-only: we can't reliably map "2pm" back to an ISO slot without
    # NLP date parsing, so we only check that *some* slot-like claim was made
    # when zero ground-truth slots existed (the strongest hallucination signal).
    if not ground_truth_available_slots and mentioned_times:
        return 0.0, ["Agent mentioned specific times despite zero ground-truth availability."]

    return 1.0, ["Heuristic check passed (see TODO: add LLM-judge for precise time cross-referencing)."]


def score_escalation_correctness(final_state: dict | None, escalation_expected: bool) -> tuple[float, list[str]]:
    actually_escalated = bool((final_state or {}).get("escalated"))
    if actually_escalated == escalation_expected:
        return 1.0, [f"Escalation correct (expected={escalation_expected}, actual={actually_escalated})."]
    return 0.0, [f"Escalation MISMATCH (expected={escalation_expected}, actual={actually_escalated})."]


def evaluate_call(fixture: dict) -> EvalResult:
    transcript = fixture.get("transcript", [])
    final_state = fixture.get("final_state")
    expected = fixture.get("expected", {})

    slot_score, slot_notes = score_slot_filling(transcript, final_state, expected.get("required_slots", {}))
    hallucination_score, hallucination_notes = score_hallucination(
        transcript, expected.get("ground_truth_available_slots")
    )
    escalation_score, escalation_notes = score_escalation_correctness(
        final_state, expected.get("escalation_expected", False)
    )

    overall = round((slot_score + hallucination_score + escalation_score) / 3, 3)

    return EvalResult(
        slot_filling_accuracy=round(slot_score, 3),
        hallucination_score=round(hallucination_score, 3),
        escalation_correctness=round(escalation_score, 3),
        overall_score=overall,
        notes=[*slot_notes, *hallucination_notes, *escalation_notes],
    )
