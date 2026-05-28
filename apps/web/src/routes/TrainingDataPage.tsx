/**
 * Admin-only page: Training Data dashboard.
 *
 * Purpose: show management what the learning loop has captured — without
 * exposing any code. Three sections:
 *
 *   1. KPI cards — totals (analyses, approved, findings, re-reviews)
 *   2. Approved reviews table — each row is one training example
 *   3. Recent capture events — newest decisions across both ledgers
 *   4. Storage footprint — what's on disk, where, in what shape
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import clsx from "clsx";
import {
  AlertOctagon,
  BarChart3,
  CheckCircle2,
  Database,
  FileJson,
  History,
  RefreshCw,
  ShieldCheck,
  ThumbsUp,
} from "lucide-react";

import { useAuth } from "../lib/auth";
import {
  getTrainingDataSummary,
  listApprovedReviews,
  listRecentTrainingEvents,
  type ApprovedReviewRow,
  type TrainingEvent,
} from "../lib/api";
import { LedgerFileViewer } from "../components/LedgerFileViewer";

export default function TrainingDataPage() {
  const { user } = useAuth();

  // Belt-and-braces — backend enforces admin too.
  if (!user?.is_admin) {
    return (
      <div className="max-w-3xl mx-auto p-8">
        <div className="card p-6 text-slate-600">
          <h1 className="text-xl font-semibold mb-2">Restricted</h1>
          <p className="text-sm">
            The Training Data dashboard is available only to platform
            administrators.
          </p>
        </div>
      </div>
    );
  }

  const summary = useQuery({
    queryKey: ["training-summary"],
    queryFn: getTrainingDataSummary,
  });

  return (
    <div className="max-w-7xl mx-auto p-8 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-wider text-brand font-semibold">
            Learning loop · Platform admin
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Training data</h1>
          <p className="text-sm text-slate-600 max-w-2xl mt-1">
            Every architect Approve / Reject — both per-finding and
            whole-review — is captured on disk as a labelled training row.
            This page shows what's been collected so far.
          </p>
        </div>
        <button
          className="btn-secondary text-xs"
          onClick={() => summary.refetch()}
          disabled={summary.isFetching}
        >
          <RefreshCw
            className={clsx(
              "w-3.5 h-3.5",
              summary.isFetching && "animate-spin",
            )}
          />
          Refresh
        </button>
      </div>

      {summary.isLoading && (
        <div className="card p-6 text-slate-500">Loading…</div>
      )}

      {summary.data && (
        <>
          <KpiGrid totals={summary.data.totals} />
          <StorageCard
            ledgers={summary.data.ledgers}
            captureSchema={summary.data.capture_schema}
            dataDir={summary.data.data_dir}
          />
        </>
      )}

      <ApprovedReviewsSection />
      <RecentEventsSection />
    </div>
  );
}


// ---------------------------------------------------------------------------
// KPI cards
// ---------------------------------------------------------------------------

function KpiGrid({
  totals,
}: {
  totals: NonNullable<ReturnType<typeof getTrainingDataSummary> extends Promise<infer T> ? T : never>["totals"];
}) {
  const reviewsDecided = totals.reviews_approved + totals.reviews_rejected;
  const findingsDecided =
    totals.critic_findings_architect_approved +
    totals.critic_findings_architect_rejected;
  return (
    <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
      <KpiCard
        title="Whole-review verdicts"
        Icon={ShieldCheck}
        primary={`${reviewsDecided} decided`}
        breakdown={[
          { label: "Approved", value: totals.reviews_approved, tone: "good" },
          { label: "Rejected", value: totals.reviews_rejected, tone: "bad" },
          { label: "Pending", value: totals.reviews_pending, tone: "muted" },
        ]}
      />
      <KpiCard
        title="Critic findings"
        Icon={BarChart3}
        primary={`${totals.critic_findings_total} total`}
        breakdown={[
          {
            label: "Auto-applied",
            value: totals.critic_findings_auto_applied,
            tone: "good",
          },
          {
            label: "Approved",
            value: totals.critic_findings_architect_approved,
            tone: "good",
          },
          {
            label: "Rejected",
            value: totals.critic_findings_architect_rejected,
            tone: "bad",
          },
        ]}
      />
      <KpiCard
        title="Re-review rounds"
        Icon={History}
        primary={`${totals.re_review_rounds} runs`}
        breakdown={[
          {
            label: "Accepted",
            value: totals.re_review_accepted,
            tone: "good",
          },
          {
            label: "Discarded",
            value: totals.re_review_discarded,
            tone: "muted",
          },
        ]}
      />
      <KpiCard
        title="Labelled examples"
        Icon={Database}
        primary={`${reviewsDecided + findingsDecided}`}
        breakdown={[
          { label: "Total decisions", value: reviewsDecided + findingsDecided, tone: "good" },
          { label: "Reviews", value: reviewsDecided, tone: "muted" },
          { label: "Findings", value: findingsDecided, tone: "muted" },
        ]}
      />
    </div>
  );
}

function KpiCard({
  title,
  primary,
  breakdown,
  Icon,
}: {
  title: string;
  primary: string;
  breakdown: { label: string; value: number; tone: "good" | "bad" | "muted" }[];
  Icon: typeof ShieldCheck;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-start gap-2">
        <div className="rounded-md p-1.5 bg-brand-50 text-brand-700 ring-1 ring-brand-100 shrink-0">
          <Icon className="w-4 h-4" />
        </div>
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
            {title}
          </div>
          <div className="text-2xl font-semibold text-slate-900 mt-0.5 leading-none">
            {primary}
          </div>
        </div>
      </div>
      <ul className="mt-3 space-y-0.5 text-xs">
        {breakdown.map((b) => (
          <li key={b.label} className="flex justify-between items-center">
            <span className="text-slate-500">{b.label}</span>
            <span
              className={clsx(
                "font-mono tabular-nums font-medium",
                b.tone === "good" && "text-emerald-700",
                b.tone === "bad" && "text-rose-700",
                b.tone === "muted" && "text-slate-700",
              )}
            >
              {b.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Approved reviews table
// ---------------------------------------------------------------------------

function ApprovedReviewsSection() {
  const [filter, setFilter] = useState<"approved" | "rejected" | "all">("approved");
  const q = useQuery({
    queryKey: ["approved-reviews", filter],
    queryFn: () => listApprovedReviews(filter),
  });

  return (
    <div className="card">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-sm font-semibold text-slate-900">
            Architect verdicts on whole reviews
          </div>
          <div className="text-xs text-slate-500">
            Each row is one labelled (extraction, verdict) training pair.
          </div>
        </div>
        <div className="inline-flex rounded-md ring-1 ring-slate-200 overflow-hidden text-xs">
          {(["approved", "rejected", "all"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={clsx(
                "px-3 py-1.5 capitalize",
                filter === k
                  ? "bg-brand-50 text-brand-700"
                  : "text-slate-600 hover:bg-slate-50",
              )}
            >
              {k}
            </button>
          ))}
        </div>
      </div>

      {q.isLoading ? (
        <div className="p-6 text-slate-500 text-sm">Loading…</div>
      ) : !q.data || q.data.items.length === 0 ? (
        <div className="p-8 text-center text-slate-500 text-sm">
          No {filter === "all" ? "decided" : filter} reviews yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left text-xs uppercase tracking-wide">
              <tr>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">ARC #</th>
                <th className="px-3 py-2.5 font-medium">Title</th>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">Decision</th>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">Decided by</th>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">Decided at</th>
                <th className="px-3 py-2.5 font-medium text-right whitespace-nowrap">Comps</th>
                <th className="px-3 py-2.5 font-medium text-right whitespace-nowrap">Rounds</th>
                <th className="px-3 py-2.5 font-medium">Comment</th>
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((r) => (
                <ApprovedRow key={r.diagram_id} row={r} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ApprovedRow({ row }: { row: ApprovedReviewRow }) {
  const isApproved = row.decision.status === "approved";
  return (
    <tr className="border-t border-slate-100 hover:bg-brand-50/40">
      <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">
        {row.arc_number ? (
          <Link
            to={`/results/${row.diagram_id}`}
            className="text-brand-700 hover:underline font-semibold"
          >
            {row.arc_number}
          </Link>
        ) : (
          <span className="text-slate-400">—</span>
        )}
      </td>
      <td className="px-3 py-2.5 max-w-[260px]">
        <div className="font-medium text-slate-900 truncate" title={row.title || row.filename}>
          {row.title || row.filename}
        </div>
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        <span
          className={clsx(
            "pill ring-1 inline-flex items-center gap-1",
            isApproved
              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
              : "bg-rose-50 text-rose-700 ring-rose-200",
          )}
        >
          {isApproved ? (
            <ThumbsUp className="w-3 h-3" />
          ) : (
            <AlertOctagon className="w-3 h-3" />
          )}
          {row.decision.status}
        </span>
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        <div className="leading-tight">
          <div className="text-slate-800">{row.decision.decided_by_name || "—"}</div>
          <div className="text-[11px] text-slate-500 font-mono">
            {row.decision.decided_by_employee_id}
          </div>
        </div>
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap text-xs text-slate-600">
        {row.decision.decided_at
          ? new Date(row.decision.decided_at).toLocaleString()
          : "—"}
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums">{row.components}</td>
      <td className="px-3 py-2.5 text-right tabular-nums">
        {row.re_review_rounds}
      </td>
      <td className="px-3 py-2.5 max-w-[300px]">
        {row.decision.comment ? (
          <div className="text-xs text-slate-700 italic truncate" title={row.decision.comment}>
            "{row.decision.comment}"
          </div>
        ) : (
          <span className="text-slate-400 text-xs">—</span>
        )}
      </td>
    </tr>
  );
}


// ---------------------------------------------------------------------------
// Recent capture events
// ---------------------------------------------------------------------------

function RecentEventsSection() {
  const q = useQuery({
    queryKey: ["training-recent-events"],
    queryFn: () => listRecentTrainingEvents(50),
  });

  return (
    <div className="card">
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="text-sm font-semibold text-slate-900">
          Recent capture events
        </div>
        <div className="text-xs text-slate-500">
          Newest first · 50 most recent rows across both ledgers.
        </div>
      </div>

      {q.isLoading ? (
        <div className="p-6 text-slate-500 text-sm">Loading…</div>
      ) : !q.data || q.data.items.length === 0 ? (
        <div className="p-8 text-center text-slate-500 text-sm">
          No events captured yet — once architects start clicking Approve /
          Reject, rows will appear here.
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {q.data.items.map((e, i) => (
            <EventRow key={i} event={e} />
          ))}
        </ul>
      )}
    </div>
  );
}

function EventRow({ event }: { event: TrainingEvent }) {
  const isReview = event.type === "review_decision";
  return (
    <li className="px-4 py-2.5 flex items-start gap-3 text-sm">
      <div
        className={clsx(
          "rounded-md p-1.5 shrink-0 ring-1",
          isReview
            ? "bg-violet-50 text-violet-700 ring-violet-200"
            : "bg-sky-50 text-sky-700 ring-sky-200",
        )}
        title={isReview ? "Whole-review verdict" : "Per-finding decision"}
      >
        {isReview ? (
          <ShieldCheck className="w-4 h-4" />
        ) : (
          <CheckCircle2 className="w-4 h-4" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 items-baseline">
          <span
            className={clsx(
              "font-mono text-[11px] uppercase tracking-wider font-semibold",
              isReview ? "text-violet-700" : "text-sky-700",
            )}
          >
            {isReview ? "REVIEW" : event.kind || "FINDING"}
          </span>
          <span
            className={clsx(
              "pill ring-1 text-[11px]",
              event.decision === "approved"
                ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                : "bg-rose-50 text-rose-700 ring-rose-200",
            )}
          >
            {event.decision}
          </span>
          {event.arc_number && (
            <Link
              to={`/results/${event.diagram_id}`}
              className="font-mono text-xs text-brand-700 hover:underline"
            >
              {event.arc_number}
            </Link>
          )}
          <span className="text-xs text-slate-400 ml-auto whitespace-nowrap">
            {new Date(event.timestamp).toLocaleString()}
          </span>
        </div>
        {(event.message || event.comment) && (
          <div className="text-xs text-slate-600 mt-0.5 italic">
            "{event.message || event.comment}"
          </div>
        )}
        <div className="text-[11px] text-slate-500 mt-0.5">
          {event.decided_by_name && (
            <>By {event.decided_by_name} · </>
          )}
          {isReview && event.snapshot_components !== undefined && (
            <>
              snapshot: {event.snapshot_components} components ·{" "}
              {event.snapshot_connections} connections
            </>
          )}
          {!isReview && event.confidence !== undefined && (
            <>critic confidence: {Math.round(event.confidence * 100)}%</>
          )}
        </div>
      </div>
    </li>
  );
}


// ---------------------------------------------------------------------------
// Storage / schema card
// ---------------------------------------------------------------------------

function StorageCard({
  ledgers,
  captureSchema,
  dataDir,
}: {
  ledgers: NonNullable<Awaited<ReturnType<typeof getTrainingDataSummary>>["ledgers"]>;
  captureSchema: NonNullable<Awaited<ReturnType<typeof getTrainingDataSummary>>["capture_schema"]>;
  dataDir: string;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 mb-3">
        <FileJson className="w-4 h-4 text-slate-500" />
        <div className="text-sm font-semibold text-slate-900">
          Storage & capture schema
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-3 mb-3">
        <LedgerPanel
          title="Per-finding ledger"
          subtitle="One row per critic finding Approve / Reject"
          stats={ledgers.per_finding}
          fields={captureSchema.per_finding_event}
        />
        <LedgerPanel
          title="Whole-review ledger"
          subtitle="One row per architect Approve / Reject of a full analysis"
          stats={ledgers.whole_review}
          fields={captureSchema.whole_review_event}
        />
      </div>
    </div>
  );
}

function LedgerPanel({
  title,
  subtitle,
  stats,
  fields,
}: {
  title: string;
  subtitle: string;
  stats: { files: { name: string; size_bytes: number; rows: number }[]; total_bytes: number; total_rows: number };
  fields: string[];
}) {
  return (
    <div className="rounded-md ring-1 ring-slate-200 bg-white p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-sm font-medium text-slate-900">{title}</div>
        <div className="text-[11px] text-slate-500 font-mono">
          {stats.total_rows} rows · {fmtBytes(stats.total_bytes)}
        </div>
      </div>
      <div className="text-xs text-slate-500">{subtitle}</div>

      <div className="mt-2 text-[11px] text-slate-500">
        Per-row fields:
      </div>
      <div className="flex flex-wrap gap-1 mt-1">
        {fields.map((f) => (
          <span
            key={f}
            className="font-mono text-[10px] rounded bg-slate-100 ring-1 ring-slate-200 text-slate-700 px-1.5 py-0.5"
          >
            {f}
          </span>
        ))}
      </div>

      {stats.files.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-1.5">
            Files on disk — click a file to preview its rows
          </div>
          <ul className="space-y-2">
            {stats.files.map((f) => (
              <li key={f.name}>
                <LedgerFileViewer name={f.name} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
