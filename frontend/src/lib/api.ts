import type { Call, EvalScore } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/**
 * TODO: the backend doesn't have these read endpoints yet -- only the
 * Retell-facing webhook/websocket/function routes exist so far (see
 * backend/app/routes/). Add `GET /api/calls` and `GET /api/eval-scores`
 * (reading from app/db/repository.py) once the dashboard is ready to show
 * real data. Until then these will reject and callers should show the
 * empty/error state, which is intentional for this scaffold.
 */

export async function fetchCalls(): Promise<Call[]> {
  const response = await fetch(`${API_BASE_URL}/api/calls`);
  if (!response.ok) {
    throw new Error(`Failed to fetch calls: ${response.status}`);
  }
  return response.json();
}

export async function fetchEvalScores(): Promise<EvalScore[]> {
  const response = await fetch(`${API_BASE_URL}/api/eval-scores`);
  if (!response.ok) {
    throw new Error(`Failed to fetch eval scores: ${response.status}`);
  }
  return response.json();
}
