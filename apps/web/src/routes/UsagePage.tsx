import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity, AlertOctagon, CheckCircle2, Cpu, Gauge,
  RefreshCw, ShieldAlert, Sparkles, Wallet,
} from "lucide-react";
import {
  fetchUsageRecent, fetchUsageSummary,
  type UsageEvent, type UsageSummary,
} from "../lib/api";
import { useAuth } from "../lib/auth";

export default function UsagePage() {
  const { user } = useAuth();

  if (!user?.is_admin) {
    return (
      <div className="max-w-2xl mx-auto p-12 text-center">
        <ShieldAlert className="w-12 h-12 mx-auto text-rose-500 mb-4" />
        <h1 className="text-xl font-semibold text-slate-900">Restricted area</h1>
        <p className="text-slate-600 mt-2">
          AI usage & cost data is restricted to platform administrators.
        </p>
      </div>
    );
  }

  const [days, setDays] = useState(30);

  const summaryQ = useQuery({
    queryKey: ["usage-summary", days],
    queryFn: () => fetchUsageSummary(days),
    refetchInterval: 30_000,
  });
  const recentQ = useQuery({
    queryKey: ["usage-recent"],
    queryFn: () => fetchUsageRecent(50),
    refetchInterval: 30_000,
  });

  const s = summaryQ.data;
  const events = recentQ.data?.items ?? [];

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-5">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-brand font-semibold">
            Platform admin
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">AI Usage & Cost</h1>
          <p className="text-sm text-slate-600 mt-1">
            Every gpt-4o call this app makes is recorded with its token usage,
            duration, status, and the employee who triggered it. The ledger
            lives at <span className="font-mono text-xs">data/usage/usage-YYYY-MM.jsonl</span>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="text-sm border border-slate-200 rounded-md px-2 py-1.5"
          >
            <option value={1}>Last 24 hours</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last 365 days</option>
          </select>
          <button
            onClick={() => { summaryQ.refetch(); recentQ.refetch(); }}
            className="btn-secondary text-xs"
            disabled={summaryQ.isFetching || recentQ.isFetching}
          >
            <RefreshCw className={clsx("w-3.5 h-3.5",
              (summaryQ.isFetching || recentQ.isFetching) && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* Current model card */}
      <CurrentModelCard summary={s} />

      {/* Headline stats */}
      <StatsGrid summary={s} />

      {/* Breakdowns */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <BreakdownCard
          title="By call type"
          icon={Cpu}
          rows={(s?.by_kind ?? []).map((r) => ({
            label: KIND_LABEL[r.kind] ?? r.kind,
            primary: `${r.tokens.toLocaleString()} tokens`,
            secondary: `${r.calls} call${r.calls === 1 ? "" : "s"}`,
            barFraction: s?.totals.tokens ? r.tokens / s.totals.tokens : 0,
          }))}
        />
        <BreakdownCard
          title="By model"
          icon={Sparkles}
          rows={(s?.by_model ?? []).map((r) => ({
            label: r.model,
            primary: `${r.tokens.toLocaleString()} tokens`,
            secondary: "",
            barFraction: s?.totals.tokens ? r.tokens / s.totals.tokens : 0,
          }))}
        />
      </div>

      <BreakdownCard
        title="By employee"
        icon={Activity}
        rows={(s?.by_employee ?? []).map((r) => ({
          label: `${r.employee_name || r.employee_id || "anonymous"}`,
          sublabel: r.employee_id,
          primary: `${r.tokens.toLocaleString()} tokens`,
          secondary: `${r.calls} calls · $${r.cost_usd.toFixed(4)}`,
          barFraction: s?.totals.tokens ? r.tokens / s.totals.tokens : 0,
        }))}
      />

      {/* Recent events table */}
      <RecentTable events={events} />
    </div>
  );
}

// ---------------------------------------------------------------------------

const KIND_LABEL: Record<string, string> = {
  vision_llm: "Vision LLM (diagram analysis)",
  chat: "Chat bot",
  doc_intelligence: "Document Intelligence (OCR)",
};

function CurrentModelCard({ summary }: { summary?: UsageSummary }) {
  return (
    <div className="card p-5">
      <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500 font-semibold mb-2">
        Currently configured model
      </div>
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            Deployment
          </div>
          <div className="font-mono text-lg font-semibold text-brand-700">
            {summary?.current_model.deployment ?? "—"}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            Model version
          </div>
          <div className="font-mono text-lg font-semibold text-slate-900">
            {summary?.current_model.model ?? "—"}
          </div>
        </div>
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            System fingerprint
          </div>
          <div className="font-mono text-sm text-slate-600 truncate">
            {summary?.current_model.system_fingerprint ?? "—"}
          </div>
        </div>
      </div>
      <p className="text-xs text-slate-500 mt-3">
        Detected from the most recent successful Azure response. A change here
        means Microsoft rolled the deployment forward to a new snapshot.
      </p>
    </div>
  );
}

function StatsGrid({ summary }: { summary?: UsageSummary }) {
  const t = summary?.totals;
  const today = summary?.today;
  const items: Array<{
    label: string; value: string; sub?: string; accent: string; Icon: typeof Cpu;
  }> = [
    {
      label: "Calls",
      value: t?.calls?.toLocaleString() ?? "0",
      sub: `${today?.calls ?? 0} today`,
      accent: "bg-brand",
      Icon: Activity,
    },
    {
      label: "Tokens",
      value: t?.tokens?.toLocaleString() ?? "0",
      sub: `${(today?.tokens ?? 0).toLocaleString()} today`,
      accent: "bg-sky-500",
      Icon: Sparkles,
    },
    {
      label: "Estimated cost (USD)",
      value: `$${(t?.cost_usd ?? 0).toFixed(2)}`,
      sub: `$${(today?.cost_usd ?? 0).toFixed(4)} today`,
      accent: "bg-emerald-500",
      Icon: Wallet,
    },
    {
      label: "Avg latency",
      value: `${t?.avg_duration_ms ?? 0} ms`,
      sub: `${t?.errors ?? 0} error${t?.errors === 1 ? "" : "s"}`,
      accent: (t?.errors ?? 0) > 0 ? "bg-rose-500" : "bg-slate-400",
      Icon: Gauge,
    },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {items.map((s) => (
        <div key={s.label} className="card p-4 relative overflow-hidden">
          <div className={clsx("absolute left-0 top-0 bottom-0 w-1", s.accent)} />
          <div className="flex items-center justify-between">
            <div className="text-xs uppercase tracking-wide text-slate-500 font-medium">
              {s.label}
            </div>
            <s.Icon className="w-3.5 h-3.5 text-slate-300" />
          </div>
          <div className="text-2xl font-semibold mt-1 text-slate-900 tabular-nums">
            {s.value}
          </div>
          {s.sub && <div className="text-xs text-slate-500 mt-1">{s.sub}</div>}
        </div>
      ))}
    </div>
  );
}

type BreakdownRow = {
  label: string;
  sublabel?: string;
  primary: string;
  secondary?: string;
  barFraction: number;
};

function BreakdownCard({
  title,
  icon: Icon,
  rows,
}: {
  title: string;
  icon: typeof Cpu;
  rows: BreakdownRow[];
}) {
  return (
    <div className="card overflow-hidden">
      <div className="bg-slate-50/60 border-b border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 flex items-center gap-2">
        <Icon className="w-4 h-4 text-brand" /> {title}
      </div>
      <div className="divide-y divide-slate-100">
        {rows.length === 0 ? (
          <div className="p-4 text-sm text-slate-500">No data in this window.</div>
        ) : rows.map((r, i) => (
          <div key={i} className="px-4 py-2.5">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-900 truncate">{r.label}</div>
                {r.sublabel && (
                  <div className="text-[11px] text-slate-500 font-mono">{r.sublabel}</div>
                )}
              </div>
              <div className="shrink-0 text-right">
                <div className="text-sm tabular-nums text-slate-900">{r.primary}</div>
                {r.secondary && (
                  <div className="text-[11px] text-slate-500">{r.secondary}</div>
                )}
              </div>
            </div>
            <div className="mt-1.5 h-1.5 rounded bg-slate-100 overflow-hidden">
              <div
                className="h-full bg-brand"
                style={{ width: `${Math.max(2, r.barFraction * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RecentTable({ events }: { events: UsageEvent[] }) {
  return (
    <div className="card overflow-hidden">
      <div className="bg-slate-50/60 border-b border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 flex items-center gap-2">
        <Activity className="w-4 h-4 text-brand" />
        Recent calls ({events.length})
      </div>
      <div className="max-h-[60vh] overflow-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-slate-50 text-slate-600 text-left text-[10px] uppercase tracking-wide sticky top-0">
            <tr>
              <th className="px-3 py-2 font-medium">When (UTC)</th>
              <th className="px-3 py-2 font-medium">Kind</th>
              <th className="px-3 py-2 font-medium">Model</th>
              <th className="px-3 py-2 font-medium">Employee</th>
              <th className="px-3 py-2 font-medium text-right">Prompt</th>
              <th className="px-3 py-2 font-medium text-right">Completion</th>
              <th className="px-3 py-2 font-medium text-right">Total</th>
              <th className="px-3 py-2 font-medium text-right">Duration</th>
              <th className="px-3 py-2 font-medium text-right">Cost</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => (
              <tr
                key={i}
                className={clsx(
                  "border-t border-slate-100",
                  e.status !== "ok" && "bg-rose-50/40",
                )}
              >
                <td className="px-3 py-1.5 font-mono text-[11px] text-slate-600 whitespace-nowrap">
                  {e.timestamp.replace("T", " ").replace("Z", "")}
                </td>
                <td className="px-3 py-1.5 font-mono text-[11px]">{e.kind}</td>
                <td className="px-3 py-1.5 font-mono text-[11px] text-slate-700">
                  {e.model ?? "—"}
                </td>
                <td className="px-3 py-1.5 text-slate-700">
                  {e.employee_id ? (
                    <>
                      {e.employee_name || e.employee_id}
                      {e.employee_name && (
                        <span className="text-[10px] text-slate-400 ml-1 font-mono">
                          {e.employee_id}
                        </span>
                      )}
                    </>
                  ) : <span className="text-slate-300">—</span>}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{e.prompt_tokens.toLocaleString()}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{e.completion_tokens.toLocaleString()}</td>
                <td className="px-3 py-1.5 text-right tabular-nums font-medium">{e.total_tokens.toLocaleString()}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{e.duration_ms} ms</td>
                <td className="px-3 py-1.5 text-right tabular-nums">${e.cost_usd.toFixed(4)}</td>
                <td className="px-3 py-1.5">
                  {e.status === "ok" ? (
                    <span className="inline-flex items-center gap-1 text-emerald-700">
                      <CheckCircle2 className="w-3 h-3" /> ok
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-rose-700"
                          title={e.error_type ?? undefined}>
                      <AlertOctagon className="w-3 h-3" /> {e.error_type ?? "error"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {events.length === 0 && (
              <tr>
                <td colSpan={10} className="p-6 text-center text-sm text-slate-500">
                  No AI calls recorded yet. Run an analysis or send a chat message.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
