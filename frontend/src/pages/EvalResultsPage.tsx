import { fetchEvalScores } from "../lib/api";
import { useFetch } from "../lib/useFetch";

function scoreColor(score: number | null): string {
  if (score === null) return "text-slate-400";
  if (score >= 0.8) return "text-emerald-600";
  if (score >= 0.5) return "text-amber-600";
  return "text-red-600";
}

function ScoreCell({ score }: { score: number | null }) {
  return <span className={`font-medium ${scoreColor(score)}`}>{score === null ? "—" : score.toFixed(2)}</span>;
}

export default function EvalResultsPage() {
  const { data: scores, loading, error } = useFetch(fetchEvalScores);

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-slate-900">Eval Results</h1>
      <p className="mb-6 text-sm text-slate-500">
        Slot-filling accuracy, hallucination, and escalation-correctness scores from
        the eval framework (backend/app/eval/).
      </p>

      {loading && <p className="text-sm text-slate-500">Loading eval results&hellip;</p>}

      {error && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          Couldn&apos;t load eval results yet ({error}). The backend doesn&apos;t have a{" "}
          <code className="rounded bg-amber-100 px-1">GET /api/eval-scores</code> endpoint wired
          up yet -- this page is scaffolding, ready to connect once it does.
        </div>
      )}

      {scores && scores.length === 0 && !loading && !error && (
        <p className="text-sm text-slate-500">No eval runs yet.</p>
      )}

      {scores && scores.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Evaluated</th>
                <th className="px-4 py-3">Call</th>
                <th className="px-4 py-3">Slot Filling</th>
                <th className="px-4 py-3">Hallucination</th>
                <th className="px-4 py-3">Escalation</th>
                <th className="px-4 py-3">Overall</th>
              </tr>
            </thead>
            <tbody>
              {scores.map((score) => (
                <tr key={score.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3 text-slate-700">
                    {new Date(score.evaluated_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">{score.call_id}</td>
                  <td className="px-4 py-3">
                    <ScoreCell score={score.slot_filling_accuracy} />
                  </td>
                  <td className="px-4 py-3">
                    <ScoreCell score={score.hallucination_score} />
                  </td>
                  <td className="px-4 py-3">
                    <ScoreCell score={score.escalation_correctness} />
                  </td>
                  <td className="px-4 py-3">
                    <ScoreCell score={score.overall_score} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
