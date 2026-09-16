// Mirrors the backend schema (backend/app/db/migrations/0001_init.sql).

export type CallStatus = "in_progress" | "completed" | "failed";

export type CallOutcome = "booked" | "rescheduled" | "escalated" | "abandoned" | "faq_only" | null;

export interface Call {
  id: string;
  retell_call_id: string;
  caller_phone: string;
  started_at: string;
  ended_at: string | null;
  status: CallStatus;
  outcome: CallOutcome;
  recording_url: string | null;
}

export interface EvalScore {
  id: string;
  call_id: string;
  slot_filling_accuracy: number | null;
  hallucination_score: number | null;
  escalation_correctness: number | null;
  overall_score: number | null;
  notes: string | null;
  evaluated_at: string;
}
