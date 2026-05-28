/**
 * One-line audit trail of past re-review rounds (accepted or discarded).
 * Click a chip to expand the feedback the architect gave that round.
 */
import { useState } from "react";
import { Check, ChevronDown, ChevronRight, History, X } from "lucide-react";
import clsx from "clsx";

import type { AnalysisResult } from "../types";

export function ReReviewHistoryStrip({ result }: { result: AnalysisResult }) {
  const rounds = result.re_review_history ?? [];
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  if (rounds.length === 0) return null;

  return (
    <div className="card p-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2">
        <History className="w-3.5 h-3.5" />
        Re-review history
      </div>
      <ul className="space-y-1.5">
        {rounds.map((r, i) => {
          const accepted = r.status === "accepted";
          const open = openIdx === i;
          const added =
            ((r.deltas?.components_added as string[] | undefined) ?? []).length +
            ((r.deltas?.connections_added as string[] | undefined) ?? []).length;
          const removed =
            ((r.deltas?.components_removed as string[] | undefined) ?? []).length +
            ((r.deltas?.connections_removed as string[] | undefined) ?? []).length;
          return (
            <li key={i} className="text-xs">
              <button
                onClick={() => setOpenIdx(open ? null : i)}
                className="w-full text-left flex items-center gap-2 hover:bg-slate-50 rounded px-1.5 py-1"
              >
                {open ? (
                  <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                )}
                <span className="font-mono text-slate-500">
                  Round {r.round_no}
                </span>
                <span
                  className={clsx(
                    "inline-flex items-center gap-1 pill ring-1",
                    accepted
                      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                      : "bg-slate-100 text-slate-600 ring-slate-200",
                  )}
                >
                  {accepted ? (
                    <Check className="w-3 h-3" />
                  ) : (
                    <X className="w-3 h-3" />
                  )}
                  {r.status}
                </span>
                <span className="text-slate-500 truncate">
                  {r.requested_by_name || r.requested_by_employee_id || "—"} ·{" "}
                  {new Date(r.requested_at).toLocaleString()}
                </span>
                {accepted && (added > 0 || removed > 0) && (
                  <span className="ml-auto text-slate-500 font-mono">
                    +{added} / −{removed}
                  </span>
                )}
              </button>
              {open && (
                <div className="ml-7 mt-1 p-2 rounded-md bg-slate-50 ring-1 ring-slate-200 space-y-1">
                  <div>
                    <span className="text-[11px] uppercase tracking-wider text-slate-500 mr-1">
                      Feedback:
                    </span>
                    <span className="italic">"{r.feedback}"</span>
                  </div>
                  <div className="text-[11px] text-slate-500">
                    Router chose{" "}
                    <span className="font-mono">
                      {r.decided_stages.join(" + ") || "vision_llm"}
                    </span>
                    {r.router_reason && <> — {r.router_reason}</>}
                    {" · "}
                    {Math.round(r.duration_ms / 100) / 10}s
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
