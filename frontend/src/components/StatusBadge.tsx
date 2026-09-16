const COLORS: Record<string, string> = {
  booked: "bg-emerald-100 text-emerald-800",
  rescheduled: "bg-blue-100 text-blue-800",
  escalated: "bg-amber-100 text-amber-800",
  abandoned: "bg-slate-100 text-slate-600",
  faq_only: "bg-violet-100 text-violet-800",
  completed: "bg-emerald-100 text-emerald-800",
  in_progress: "bg-blue-100 text-blue-800",
  failed: "bg-red-100 text-red-800",
};

export default function StatusBadge({ value }: { value: string | null }) {
  if (!value) {
    return <span className="text-sm text-slate-400">&mdash;</span>;
  }
  const classes = COLORS[value] ?? "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${classes}`}>
      {value.replace("_", " ")}
    </span>
  );
}
