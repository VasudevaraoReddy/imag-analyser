import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { listAnalyses } from "../lib/api";
import { ProviderBadge } from "../components/ProviderBadge";
import { ReviewStatePill } from "../components/StatusPill";

export default function HistoryPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["history"],
    queryFn: listAnalyses,
  });
  const [provFilter, setProvFilter] = useState<string>("");
  const [reviewFilter, setReviewFilter] = useState<string>("");
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    return (data ?? []).filter((r) =>
      (!provFilter || r.primary_provider === provFilter) &&
      (!reviewFilter || r.review_state === reviewFilter) &&
      (!q || r.filename.toLowerCase().includes(q.toLowerCase())),
    );
  }, [data, provFilter, reviewFilter, q]);

  return (
    <div className="max-w-6xl mx-auto p-8 space-y-5">
      <div>
        <div className="text-xs uppercase tracking-wider text-brand font-semibold">
          Library
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">Past analyses</h1>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-slate-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by filename…"
            className="pl-8 pr-3 py-2 w-full text-sm rounded-md border border-slate-200 focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand"
          />
        </div>
        <select value={provFilter} onChange={(e) => setProvFilter(e.target.value)}
                className="text-sm border border-slate-200 rounded-md px-2 py-2">
          <option value="">All providers</option>
          <option value="azure">azure</option>
          <option value="aws">aws</option>
          <option value="gcp">gcp</option>
          <option value="oci">oci</option>
          <option value="multi">multi</option>
          <option value="on_prem">on_prem</option>
          <option value="unknown">unknown</option>
        </select>
        <select value={reviewFilter} onChange={(e) => setReviewFilter(e.target.value)}
                className="text-sm border border-slate-200 rounded-md px-2 py-2">
          <option value="">All review states</option>
          <option value="auto_review_recommended">auto_review_recommended</option>
          <option value="needs_human_review">needs_human_review</option>
          <option value="rejected">rejected</option>
        </select>
      </div>

      {isLoading ? (
        <div className="text-slate-500">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card p-10 text-center text-slate-500 text-sm">
          No analyses match these filters yet.
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2.5 font-medium">ARC #</th>
                <th className="px-4 py-2.5 font-medium">Title / File</th>
                <th className="px-4 py-2.5 font-medium">Submitted by</th>
                <th className="px-4 py-2.5 font-medium">Submitted</th>
                <th className="px-4 py-2.5 font-medium">Provider</th>
                <th className="px-4 py-2.5 font-medium text-right">Components</th>
                <th className="px-4 py-2.5 font-medium text-right">Confidence</th>
                <th className="px-4 py-2.5 font-medium">Review state</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.diagram_id} className="border-t border-slate-100 hover:bg-brand-50/40">
                  <td className="px-4 py-2.5 font-mono text-xs">
                    {r.arc_number ? (
                      <Link
                        to={`/results/${r.diagram_id}`}
                        className="text-brand-700 hover:underline font-semibold"
                      >
                        {r.arc_number}
                      </Link>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-slate-900">
                      {r.title || r.filename}
                    </div>
                    {r.title && (
                      <div className="text-xs text-slate-500">{r.filename}</div>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    {r.submitted_by_name || r.submitted_by_employee_id ? (
                      <div className="leading-tight">
                        <div className="text-slate-800">{r.submitted_by_name || r.submitted_by_employee_id}</div>
                        {r.submitted_by_name && r.submitted_by_employee_id && (
                          <div className="text-[11px] text-slate-500 font-mono">
                            {r.submitted_by_employee_id}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">
                    {new Date(r.submitted_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5"><ProviderBadge provider={r.primary_provider} /></td>
                  <td className="px-4 py-2.5 text-slate-700 text-right tabular-nums">{r.components_count}</td>
                  <td className="px-4 py-2.5 text-slate-700 text-right tabular-nums">
                    {Math.round(r.overall_confidence * 100)}%
                  </td>
                  <td className="px-4 py-2.5"><ReviewStatePill state={r.review_state} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
