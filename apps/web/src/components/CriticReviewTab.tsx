/**
 * AI Self-Review tab — surfaces every CriticFinding the second-pass agent
 * produced, with Approve / Reject buttons that POST to the decision
 * endpoint. The architect's clicks become training data for the eventual
 * fine-tune (Sprint 3 — Feedback capture).
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  AlertTriangle,
  Bot,
  Check,
  CheckCircle2,
  Loader2,
  ShieldCheck,
  X,
  XCircle,
} from "lucide-react";

import type {
  AnalysisResult,
  CriticFinding,
  CriticFindingKind,
  CriticStatus,
} from "../types";
import { submitCriticDecision } from "../lib/api";

const KIND_LABELS: Record<CriticFindingKind, string> = {
  missed_component:   "Missed component",
  spurious_component: "Spurious component",
  wrong_label:        "Wrong label",
  wrong_service_type: "Wrong service type",
  reversed_flow:      "Reversed flow direction",
  missed_connection:  "Missed connection",
  questionable_journey: "Questionable journey",
};

const STATUS_STYLES: Record<CriticStatus, string> = {
  auto_applied: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  pending:      "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
  approved:     "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
  rejected:     "bg-slate-100 text-slate-600 ring-1 ring-slate-200",
};

const STATUS_LABELS: Record<CriticStatus, string> = {
  auto_applied: "Auto-applied",
  pending:      "Pending review",
  approved:     "Approved",
  rejected:     "Rejected",
};

export function CriticReviewTab({ result }: { result: AnalysisResult }) {
  const review = result.critic_review;
  const qc = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorId, setErrorId] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: async (v: {
      findingId: string;
      decision: "approved" | "rejected";
    }) => submitCriticDecision(result.diagram_id, v.findingId, v.decision),
    onSuccess: (updated) => {
      qc.setQueryData(["analysis", result.diagram_id], updated);
      qc.invalidateQueries({ queryKey: ["analyses"] });
    },
  });

  if (!review || !review.ran) {
    return (
      <div className="p-6 text-sm text-slate-500">
        <div className="inline-flex items-center gap-2">
          <Bot className="w-4 h-4" />
          AI Self-Critique was not run for this analysis.
        </div>
        {review?.overall_assessment && (
          <div className="text-xs text-slate-500 mt-1">
            {review.overall_assessment}
          </div>
        )}
      </div>
    );
  }

  const findings = [...review.findings].sort((a, b) => {
    const order: Record<CriticStatus, number> = {
      pending: 0, auto_applied: 1, approved: 2, rejected: 3,
    };
    if (order[a.status] !== order[b.status]) return order[a.status] - order[b.status];
    return b.confidence - a.confidence;
  });

  const summary = review.summary || {};
  const pendingCount = summary.pending ?? 0;
  const autoCount    = summary.auto_applied ?? 0;
  const approvedCnt  = summary.approved ?? 0;
  const rejectedCnt  = summary.rejected ?? 0;

  const decide = async (f: CriticFinding, d: "approved" | "rejected") => {
    setBusyId(f.id);
    setErrorId(null);
    try {
      await mut.mutateAsync({ findingId: f.id, decision: d });
    } catch (e) {
      console.error("decision_failed", e);
      setErrorId(f.id);
    } finally {
      setBusyId(null);
    }
  };

  const compName = (id: string) =>
    result.components.find((c) => c.id === id)?.name ?? id;
  const connDescr = (id: string) => {
    const c = result.connections.find((c) => c.id === id);
    if (!c) return id;
    return `${compName(c.from)} → ${compName(c.to)}`;
  };

  return (
    <div className="p-4 space-y-4">
      {/* Header strip */}
      <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <div className="rounded-md bg-brand-50 text-brand-700 ring-1 ring-brand-200 p-2">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-slate-900">
                AI Self-Critique
              </div>
              <div className="text-xs text-slate-600 mt-0.5">
                {review.overall_assessment ||
                  "Second-pass review by a senior cloud-security model."}
              </div>
              <div className="text-[11px] text-slate-500 mt-1">
                model: <span className="font-mono">{review.model ?? "unknown"}</span>
                {" · "}duration: {review.duration_ms} ms
                {" · "}confidence: {(review.critique_confidence * 100).toFixed(0)}%
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Chip className={STATUS_STYLES.pending} count={pendingCount}>Pending</Chip>
            <Chip className={STATUS_STYLES.auto_applied} count={autoCount}>Auto-applied</Chip>
            <Chip className={STATUS_STYLES.approved} count={approvedCnt}>Approved</Chip>
            <Chip className={STATUS_STYLES.rejected} count={rejectedCnt}>Rejected</Chip>
          </div>
        </div>
      </div>

      {findings.length === 0 ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 inline-flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" />
          The critic found nothing to flag. The extraction looks consistent
          with the diagram.
        </div>
      ) : (
        <ul className="space-y-3">
          {findings.map((f) => (
            <li
              key={f.id}
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900">
                      {KIND_LABELS[f.kind] ?? f.kind}
                    </span>
                    <span className={clsx("pill", STATUS_STYLES[f.status])}>
                      {STATUS_LABELS[f.status]}
                    </span>
                    <span className="text-[11px] uppercase tracking-wider text-slate-500">
                      confidence: {(f.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="text-sm text-slate-800 mt-1.5">{f.message}</div>
                  {f.reason && (
                    <div className="text-xs text-slate-500 mt-1">
                      <span className="font-medium text-slate-600">Why: </span>
                      {f.reason}
                    </div>
                  )}
                  <SuggestionBlock
                    finding={f}
                    compName={compName}
                    connDescr={connDescr}
                  />

                  {(f.affected_component_ids.length +
                    f.affected_connection_ids.length +
                    f.affected_journey_ids.length) > 0 && (
                    <div className="text-xs text-slate-500 mt-1.5">
                      <span className="font-medium">Affects: </span>
                      {[
                        ...f.affected_component_ids.map(compName),
                        ...f.affected_connection_ids.map(connDescr),
                      ].join(" · ") || "—"}
                    </div>
                  )}

                  {(f.status === "approved" || f.status === "rejected") &&
                    (f.decided_by_name || f.decided_by_employee_id) && (
                      <div className="text-[11px] text-slate-500 mt-1.5">
                        Decided by{" "}
                        <span className="font-medium text-slate-700">
                          {f.decided_by_name || f.decided_by_employee_id}
                        </span>
                        {f.decided_at && (
                          <> on {new Date(f.decided_at).toLocaleString()}</>
                        )}
                      </div>
                    )}

                  {errorId === f.id && (
                    <div className="text-xs text-rose-600 mt-1.5 inline-flex items-center gap-1">
                      <AlertTriangle className="w-3.5 h-3.5" />
                      Could not record decision — try again.
                    </div>
                  )}
                </div>

                <div className="flex flex-col gap-2 shrink-0">
                  {f.status === "pending" ? (
                    <>
                      <button
                        className="btn-primary text-xs"
                        disabled={busyId === f.id}
                        onClick={() => decide(f, "approved")}
                      >
                        {busyId === f.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Check className="w-3.5 h-3.5" />
                        )}
                        Approve
                      </button>
                      <button
                        className="btn-secondary text-xs"
                        disabled={busyId === f.id}
                        onClick={() => decide(f, "rejected")}
                      >
                        {busyId === f.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <X className="w-3.5 h-3.5" />
                        )}
                        Reject
                      </button>
                    </>
                  ) : (
                    <span className="text-[11px] text-slate-400 inline-flex items-center gap-1">
                      {f.status === "rejected" ? (
                        <XCircle className="w-3.5 h-3.5" />
                      ) : (
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      )}
                      decided
                    </span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="text-[11px] text-slate-400 italic pt-1">
        Every Approve / Reject is appended to the feedback ledger and used
        to train future model versions.
      </div>
    </div>
  );
}

function Chip({
  children,
  count,
  className,
}: {
  children: React.ReactNode;
  count: number;
  className: string;
}) {
  return (
    <span className={clsx("pill", className)}>
      {children}
      <span className="ml-1 font-semibold">{count}</span>
    </span>
  );
}

function SuggestionBlock({
  finding,
  compName,
  connDescr,
}: {
  finding: CriticFinding;
  compName: (id: string) => string;
  connDescr: (id: string) => string;
}) {
  const s = finding.suggestion as Record<string, unknown>;
  if (!s || Object.keys(s).length === 0) return null;

  const row = (label: string, value: React.ReactNode) => (
    <div className="flex gap-2 text-xs">
      <span className="text-slate-500 w-28 shrink-0">{label}</span>
      <span className="text-slate-800">{value}</span>
    </div>
  );

  const content: React.ReactNode[] = [];
  switch (finding.kind) {
    case "wrong_label":
      content.push(
        row("Component", compName(String(s.component_id ?? ""))),
        row("Current name", String(s.current ?? "")),
        row("Suggested name", <strong>{String(s.suggested ?? "")}</strong>),
      );
      break;
    case "wrong_service_type":
      content.push(
        row("Component", compName(String(s.component_id ?? ""))),
        row("Current type", <code>{String(s.current ?? "")}</code>),
        row("Suggested type", <strong><code>{String(s.suggested ?? "")}</code></strong>),
      );
      break;
    case "reversed_flow":
      content.push(
        row("Connection", connDescr(String(s.connection_id ?? ""))),
        row("Action", <em>Flip from / to</em>),
      );
      break;
    case "missed_component":
      content.push(
        row("Add component", <strong>{String(s.name ?? "")}</strong>),
        row("Service type", <code>{String(s.suggested_service_type ?? "unknown")}</code>),
      );
      break;
    case "missed_connection":
      content.push(
        row(
          "Add connection",
          <strong>
            {compName(String(s.from_component_id ?? ""))} →{" "}
            {compName(String(s.to_component_id ?? ""))}
          </strong>,
        ),
        row("Protocol", String(s.protocol ?? "—")),
      );
      break;
    case "spurious_component":
      content.push(
        row("Remove component", <strong>{compName(String(s.component_id ?? ""))}</strong>),
      );
      break;
    case "questionable_journey":
      content.push(
        row("Journey", String(s.journey_id ?? "")),
        row("Issue", String(s.issue ?? "")),
      );
      break;
  }

  if (!content.length) return null;
  return (
    <div className="mt-2 bg-slate-50 ring-1 ring-slate-200 rounded-md p-2 space-y-0.5">
      {content}
    </div>
  );
}
