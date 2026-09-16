import StatusBadge from "../components/StatusBadge";
import { fetchCalls } from "../lib/api";
import { useFetch } from "../lib/useFetch";

export default function CallsListPage() {
  const { data: calls, loading, error } = useFetch(fetchCalls);

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-slate-900">Calls</h1>
      <p className="mb-6 text-sm text-slate-500">
        Recent calls handled by the Chairside voice agent.
      </p>

      {loading && <p className="text-sm text-slate-500">Loading calls&hellip;</p>}

      {error && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          Couldn&apos;t load calls yet ({error}). The backend doesn&apos;t have a{" "}
          <code className="rounded bg-amber-100 px-1">GET /api/calls</code> endpoint wired up yet
          -- this page is scaffolding, ready to connect once it does.
        </div>
      )}

      {calls && calls.length === 0 && !loading && !error && (
        <p className="text-sm text-slate-500">No calls yet.</p>
      )}

      {calls && calls.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Started</th>
                <th className="px-4 py-3">Caller</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((call) => (
                <tr key={call.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3 text-slate-700">
                    {new Date(call.started_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-slate-700">{call.caller_phone}</td>
                  <td className="px-4 py-3">
                    <StatusBadge value={call.status} />
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge value={call.outcome} />
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
