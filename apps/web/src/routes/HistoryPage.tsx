import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search, Trash2 } from "lucide-react";
import clsx from "clsx";
import { listAnalyses, deleteAnalysis, type DeleteReviewResponse } from "../lib/api";
import { ProviderBadge } from "../components/ProviderBadge";
import { ReviewStatePill } from "../components/StatusPill";
import { DeleteConfirmDialog } from "../components/DeleteConfirmDialog";
import { useAuth } from "../lib/auth";
import type { AnalysisSummary } from "@bank-arch/shared";

export default function HistoryPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["history"],
    queryFn: listAnalyses,
  });
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.is_admin ?? false;

  const [provFilter, setProvFilter] = useState<string>("");
  const [reviewFilter, setReviewFilter] = useState<string>("");
  const [q, setQ] = useState("");

  // Delete dialog state
  const [deleteTarget, setDeleteTarget] = useState<AnalysisSummary | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteResult, setDeleteResult] = useState<DeleteReviewResponse | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function openDelete(row: AnalysisSummary) {
    setDeleteTarget(row);
    setDeleteResult(null);
    setDeleteError(null);
  }

  function closeDelete() {
    setDeleteTarget(null);
    setDeleteResult(null);
    setDeleteError(null);
    setIsDeleting(false);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      const res = await deleteAnalysis(deleteTarget.diagram_id);
      setDeleteResult(res);
      // Invalidate the history list so the row disappears
      queryClient.invalidateQueries({ queryKey: ["history"] });
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setIsDeleting(false);
    }
  }

  const rows = useMemo(() => {
    return (data ?? []).filter((r) =>
      (!provFilter || r.primary_provider === provFilter) &&
      (!reviewFilter || r.review_state === reviewFilter) &&
      (!q || r.filename.toLowerCase().includes(q.toLowerCase())),
    );
  }, [data, provFilter, reviewFilter, q]);

  return (
    <div className="max-w-7xl mx-auto p-8 space-y-5">
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
        <div className="card overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left text-xs uppercase tracking-wide">
              <tr>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">ARC #</th>
                <th className="px-3 py-2.5 font-medium">Title / File</th>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">Submitted by</th>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">Submitted</th>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">Provider</th>
                <th className="px-3 py-2.5 font-medium text-right whitespace-nowrap">Comps</th>
                <th className="px-3 py-2.5 font-medium text-right whitespace-nowrap">Conf</th>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">Review state</th>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">Architect</th>
                {isAdmin && (
                  <th className="px-3 py-2.5 font-medium whitespace-nowrap w-10" aria-label="Delete" />
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.diagram_id} className="border-t border-slate-100 hover:bg-brand-50/40">
                  <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">
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
                  <td className="px-3 py-2.5 max-w-[260px]">
                    <div className="font-medium text-slate-900 truncate" title={r.title || r.filename}>
                      {r.title || r.filename}
                    </div>
                    {r.title && (
                      <div className="text-xs text-slate-500 truncate" title={r.filename}>
                        {r.filename}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
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
                  <td className="px-3 py-2.5 text-slate-600 whitespace-nowrap text-xs leading-tight">
                    <div>{new Date(r.submitted_at).toLocaleDateString()}</div>
                    <div className="text-slate-400">
                      {new Date(r.submitted_at).toLocaleTimeString([], {
                        hour: "2-digit", minute: "2-digit",
                      })}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap"><ProviderBadge provider={r.primary_provider} /></td>
                  <td className="px-3 py-2.5 text-slate-700 text-right tabular-nums">{r.components_count}</td>
                  <td className="px-3 py-2.5 text-slate-700 text-right tabular-nums">
                    {Math.round(r.overall_confidence * 100)}%
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap"><ReviewStatePill state={r.review_state} compact /></td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    <span
                      className={clsx(
                        "pill ring-1",
                        r.architect_decision_status === "approved" &&
                          "bg-emerald-50 text-emerald-700 ring-emerald-200",
                        r.architect_decision_status === "rejected" &&
                          "bg-rose-50 text-rose-700 ring-rose-200",
                        r.architect_decision_status === "pending" &&
                          "bg-slate-100 text-slate-500 ring-slate-200",
                      )}
                    >
                      {r.architect_decision_status}
                    </span>
                  </td>
                  {isAdmin && (
                    <td className="px-2 py-2.5 text-center">
                      <button
                        onClick={(e) => { e.stopPropagation(); openDelete(r); }}
                        className="p-1.5 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                        title={`Delete ${r.arc_number || r.diagram_id}`}
                        aria-label={`Delete ${r.arc_number || r.diagram_id}`}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete confirmation dialog */}
      <DeleteConfirmDialog
        open={deleteTarget !== null}
        onClose={closeDelete}
        onConfirm={confirmDelete}
        arcNumber={deleteTarget?.arc_number}
        title={deleteTarget?.title || deleteTarget?.filename}
        isDeleting={isDeleting}
        result={deleteResult}
        error={deleteError}
      />
    </div>
  );
}
