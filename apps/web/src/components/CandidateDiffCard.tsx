/**
 * Renders the staged Re-review candidate at the top of ResultsPage.
 *
 * The architect sees a one-glance summary of what changed (+N components,
 * M flows flipped, …) plus the router's reason for picking which stage(s)
 * to re-run. Two buttons: Accept this version / Discard and keep original.
 *
 * Mounted only when ``result.candidate != null``.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  Trash2,
} from "lucide-react";
import clsx from "clsx";

import type { AnalysisResult, Component, Connection, TrustZone } from "../types";
import {
  acceptReReviewCandidate,
  discardReReviewCandidate,
} from "../lib/api";

export function CandidateDiffCard({ result }: { result: AnalysisResult }) {
  const cand = result.candidate;
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const acceptMut = useMutation({
    mutationFn: () => acceptReReviewCandidate(result.diagram_id),
    onSuccess: (updated) => {
      qc.setQueryData(["analysis", result.diagram_id], updated);
      qc.invalidateQueries({ queryKey: ["analyses"] });
    },
    onError: (e: Error) =>
      setError(e.message || "Could not accept the candidate"),
  });
  const discardMut = useMutation({
    mutationFn: () => discardReReviewCandidate(result.diagram_id),
    onSuccess: (updated) => {
      qc.setQueryData(["analysis", result.diagram_id], updated);
    },
    onError: (e: Error) =>
      setError(e.message || "Could not discard the candidate"),
  });
  const busy = acceptMut.isPending || discardMut.isPending;

  if (!cand) return null;

  const deltas = cand.deltas || ({} as Record<string, unknown>);
  const added = (deltas.components_added as string[] | undefined) ?? [];
  const removed = (deltas.components_removed as string[] | undefined) ?? [];
  const cAdded = (deltas.connections_added as string[] | undefined) ?? [];
  const cRemoved = (deltas.connections_removed as string[] | undefined) ?? [];
  const flipped = (deltas.connections_flipped as string[] | undefined) ?? [];
  const journeysBefore = (deltas.journeys_before as number | undefined) ?? 0;
  const journeysAfter = (deltas.journeys_after as number | undefined) ?? 0;
  const confBefore = (deltas.confidence_before as number | undefined) ?? 0;
  const confAfter = (deltas.confidence_after as number | undefined) ?? 0;

  const totalChanges =
    added.length + removed.length + cAdded.length + cRemoved.length +
    flipped.length + (journeysBefore !== journeysAfter ? 1 : 0);

  return (
    <div className="card p-4 border-l-4 border-violet-500 bg-violet-50/40">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <div className="rounded-md p-2 bg-violet-100 text-violet-700 ring-1 ring-violet-200 shrink-0">
            <RefreshCw className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wider text-violet-700 font-semibold">
              Re-review · Round {cand.round_no} · pending your decision
            </div>
            <div className="text-base font-semibold text-slate-900 mt-0.5">
              {totalChanges === 0
                ? "No structural changes detected"
                : `${added.length + cAdded.length} added · ${removed.length + cRemoved.length} removed · ${flipped.length} flipped`}
            </div>
            <div className="text-xs text-slate-600 mt-1 max-w-2xl">
              <span className="font-medium text-slate-700">Your feedback:</span>{" "}
              <span className="italic">"{cand.feedback}"</span>
            </div>
            <div className="text-[11px] text-slate-500 mt-1">
              Router re-ran{" "}
              <span className="font-mono">
                {cand.decided_stages.join(" + ") || "vision_llm"}
              </span>
              {cand.router_reason && (
                <> — <span className="italic">"{cand.router_reason}"</span></>
              )}
              {" · "}
              {Math.round(cand.duration_ms / 100) / 10}s
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="btn-primary !bg-emerald-600 hover:!bg-emerald-700"
            onClick={() => acceptMut.mutate()}
            disabled={busy}
          >
            {acceptMut.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Check className="w-4 h-4" />
            )}
            Accept this version
          </button>
          <button
            className="btn-secondary"
            onClick={() => discardMut.mutate()}
            disabled={busy}
          >
            {discardMut.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Trash2 className="w-4 h-4" />
            )}
            Discard
          </button>
        </div>
      </div>

      {error && (
        <div className="text-xs text-rose-600 mt-2 inline-flex items-center gap-1">
          <AlertTriangle className="w-3.5 h-3.5" /> {error}
        </div>
      )}

      <button
        className="mt-3 text-xs text-violet-700 hover:underline inline-flex items-center gap-1"
        onClick={() => setExpanded((e) => !e)}
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" />
        )}
        {expanded ? "Hide details" : "Show full diff"}
      </button>

      {expanded && (
        <div className="mt-3 grid lg:grid-cols-2 gap-3 text-xs text-slate-700">
          <ComponentDiffPanel
            title="Components added"
            tone="add"
            ids={added}
            // Newly-added components live on the CANDIDATE, not on the result
            componentsSource={cand.components}
            zonesSource={cand.trust_zones}
          />
          <ComponentDiffPanel
            title="Components removed"
            tone="remove"
            ids={removed}
            // Removed components exist on the LIVE result (they're about to go)
            componentsSource={result.components}
            zonesSource={result.trust_zones}
          />
          <ConnectionDiffPanel
            title="Connections added"
            tone="add"
            ids={cAdded}
            connectionsSource={cand.connections}
            componentsSource={cand.components}
          />
          <ConnectionDiffPanel
            title="Connections removed"
            tone="remove"
            ids={cRemoved}
            connectionsSource={result.connections}
            componentsSource={result.components}
          />
          <ConnectionDiffPanel
            title="Connections flipped"
            tone="neutral"
            ids={flipped}
            connectionsSource={cand.connections}
            componentsSource={cand.components}
          />
          <div className="bg-white ring-1 ring-slate-200 rounded-md px-3 py-2">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
              Other
            </div>
            <div className="mt-1 space-y-0.5">
              <div>
                Journeys: <span className="font-mono">{journeysBefore}</span> →{" "}
                <span className="font-mono">{journeysAfter}</span>
              </div>
              <div>
                Confidence:{" "}
                <span className="font-mono">{Math.round(confBefore * 100)}%</span>{" "}
                → <span className="font-mono">{Math.round(confAfter * 100)}%</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Rich panels — show name, service type, trust zone, endpoints. An
// architect cannot judge "c-critic-11 added" but they can judge
// "Murex DB (database_relational) added in Interfacing Applications".
// ---------------------------------------------------------------------------

type Tone = "add" | "remove" | "neutral";

const TONE_BG: Record<Tone, string> = {
  add: "bg-emerald-50 ring-emerald-200",
  remove: "bg-rose-50 ring-rose-200",
  neutral: "bg-slate-50 ring-slate-200",
};
const TONE_TEXT: Record<Tone, string> = {
  add: "text-emerald-800",
  remove: "text-rose-800",
  neutral: "text-slate-700",
};

function EmptyPanel({ title }: { title: string }) {
  return (
    <div className="bg-white ring-1 ring-slate-200 rounded-md px-3 py-2 text-slate-400">
      <div className="text-[11px] uppercase tracking-wider font-semibold">
        {title}
      </div>
      <div className="mt-1">—</div>
    </div>
  );
}

function PanelHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
      {title} ({count})
    </div>
  );
}

function ComponentDiffPanel({
  title,
  tone,
  ids,
  componentsSource,
  zonesSource,
}: {
  title: string;
  tone: Tone;
  ids: string[];
  componentsSource: Component[];
  zonesSource: TrustZone[];
}) {
  if (ids.length === 0) return <EmptyPanel title={title} />;
  const byId = new Map(componentsSource.map((c) => [c.id, c]));
  const zoneById = new Map(zonesSource.map((z) => [z.id, z]));
  return (
    <div className="bg-white ring-1 ring-slate-200 rounded-md px-3 py-2">
      <PanelHeader title={title} count={ids.length} />
      <ul className="mt-1.5 space-y-1.5">
        {ids.map((id) => {
          const c = byId.get(id);
          if (!c) {
            return (
              <li
                key={id}
                className={clsx(
                  "rounded px-2 py-1 ring-1 font-mono text-[11px]",
                  TONE_BG[tone],
                  TONE_TEXT[tone],
                )}
                title="Couldn't resolve this id — extraction may be stale"
              >
                {id}
              </li>
            );
          }
          const zone = c.trust_zone ? zoneById.get(c.trust_zone) : undefined;
          return (
            <li
              key={id}
              className={clsx(
                "rounded px-2 py-1.5 ring-1 flex items-start gap-2",
                TONE_BG[tone],
              )}
            >
              <span className={clsx("font-medium truncate", TONE_TEXT[tone])}>
                {c.name || c.canonical_name || c.id}
              </span>
              <span className="ml-auto flex flex-wrap gap-1 justify-end">
                <span className="text-[10px] font-mono rounded bg-white/70 ring-1 ring-slate-200 text-slate-600 px-1.5 py-0.5">
                  {c.service_type}
                </span>
                {zone && (
                  <span
                    className="text-[10px] rounded bg-white/70 ring-1 ring-slate-200 text-slate-600 px-1.5 py-0.5"
                    title={`Trust zone: ${zone.kind}`}
                  >
                    {zone.name}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ConnectionDiffPanel({
  title,
  tone,
  ids,
  connectionsSource,
  componentsSource,
}: {
  title: string;
  tone: Tone;
  ids: string[];
  connectionsSource: Connection[];
  componentsSource: Component[];
}) {
  if (ids.length === 0) return <EmptyPanel title={title} />;
  const connById = new Map(connectionsSource.map((e) => [e.id, e]));
  const compById = new Map(componentsSource.map((c) => [c.id, c]));
  const nameOf = (cid: string) =>
    compById.get(cid)?.name || compById.get(cid)?.canonical_name || cid;
  return (
    <div className="bg-white ring-1 ring-slate-200 rounded-md px-3 py-2">
      <PanelHeader title={title} count={ids.length} />
      <ul className="mt-1.5 space-y-1.5">
        {ids.map((id) => {
          const e = connById.get(id);
          if (!e) {
            return (
              <li
                key={id}
                className={clsx(
                  "rounded px-2 py-1 ring-1 font-mono text-[11px]",
                  TONE_BG[tone],
                  TONE_TEXT[tone],
                )}
              >
                {id}
              </li>
            );
          }
          const protoLabel =
            e.protocol || e.label || (e.port ? `:${e.port}` : "");
          return (
            <li
              key={id}
              className={clsx(
                "rounded px-2 py-1.5 ring-1 flex flex-wrap items-center gap-1.5",
                TONE_BG[tone],
              )}
            >
              <span className={clsx("font-medium truncate", TONE_TEXT[tone])}>
                {nameOf(e.from)}
              </span>
              <ArrowRight className="w-3 h-3 text-slate-400 shrink-0" />
              <span className={clsx("font-medium truncate", TONE_TEXT[tone])}>
                {nameOf(e.to)}
              </span>
              {protoLabel && (
                <span className="ml-auto text-[10px] font-mono rounded bg-white/70 ring-1 ring-slate-200 text-slate-600 px-1.5 py-0.5">
                  {protoLabel}
                </span>
              )}
              {e.encrypted === false && (
                <span
                  className="text-[10px] rounded bg-amber-50 ring-1 ring-amber-200 text-amber-800 px-1.5 py-0.5"
                  title="No encryption on this connection"
                >
                  unencrypted
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}


// Legacy plain-id renderer — no longer used directly, retained in case
// we want a compact fallback variant later.
function _UnusedDiffList({
  title,
  ids,
  tone,
}: {
  title: string;
  ids: string[];
  tone: Tone;
}) {
  if (ids.length === 0) {
    return (
      <div className="bg-white ring-1 ring-slate-200 rounded-md px-3 py-2 text-slate-400">
        <div className="text-[11px] uppercase tracking-wider font-semibold">
          {title}
        </div>
        <div className="mt-1">—</div>
      </div>
    );
  }
  return (
    <div className="bg-white ring-1 ring-slate-200 rounded-md px-3 py-2">
      <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
        {title} ({ids.length})
      </div>
      <ul className="mt-1 flex flex-wrap gap-1">
        {ids.map((id) => (
          <li
            key={id}
            className={clsx(
              "font-mono text-[11px] rounded px-1.5 py-0.5 ring-1",
              tone === "add" && "bg-emerald-50 text-emerald-700 ring-emerald-200",
              tone === "remove" && "bg-rose-50 text-rose-700 ring-rose-200",
              tone === "neutral" && "bg-slate-100 text-slate-700 ring-slate-200",
            )}
          >
            {id}
          </li>
        ))}
      </ul>
    </div>
  );
}
