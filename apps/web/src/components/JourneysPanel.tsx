import clsx from "clsx";
import {
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Compass,
  Lock,
  ShieldQuestion,
  Unlock,
} from "lucide-react";
import type { AnalysisResult, Journey, JourneyHop, JourneyKind } from "../types";

const ZONE_DOT: Record<string, string> = {
  external: "bg-rose-500",
  perimeter: "bg-amber-500",
  dmz: "bg-yellow-500",
  internal: "bg-emerald-500",
  restricted: "bg-blue-500",
  management: "bg-violet-500",
};

const KIND_LABEL: Record<JourneyKind, string> = {
  auth: "Authentication",
  read: "Data read",
  write: "Data write",
  admin: "Management plane",
  integration: "Integration",
  generic: "Flow",
};

const KIND_CLS: Record<JourneyKind, string> = {
  auth: "bg-violet-50 text-violet-700 ring-1 ring-violet-200",
  read: "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
  write: "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  admin: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  integration: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  generic: "bg-slate-100 text-slate-700 ring-1 ring-slate-200",
};

type Props = {
  result: AnalysisResult;
  selectedJourneyId?: string | null;
  onSelect?: (id: string | null) => void;
};

export function JourneysPanel({ result, selectedJourneyId, onSelect }: Props) {
  const journeys = result.journeys ?? [];

  if (journeys.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-slate-500">
        <Compass className="w-8 h-8 mx-auto text-slate-300 mb-2" />
        No journeys extracted. This usually means the diagram has no
        entry actor (User/Internet) or no recognized data-tier sink.
      </div>
    );
  }

  return (
    <div className="divide-y divide-slate-100">
      {journeys.map((j) => (
        <JourneyCard
          key={j.id}
          journey={j}
          result={result}
          selected={selectedJourneyId === j.id}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

function JourneyCard({
  journey,
  result,
  selected,
  onSelect,
}: {
  journey: Journey;
  result: AnalysisResult;
  selected: boolean;
  onSelect?: (id: string | null) => void;
}) {
  const findings = result.compliance_findings.filter((f) =>
    journey.related_findings.includes(f.rule),
  );

  return (
    <div
      className={clsx(
        "p-4 cursor-pointer transition",
        selected ? "bg-brand-50/60 ring-1 ring-brand-200" : "hover:bg-slate-50",
      )}
      onClick={() => onSelect?.(selected ? null : journey.id)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={clsx("pill", KIND_CLS[journey.kind])}>
              {KIND_LABEL[journey.kind]}
            </span>
            <h3 className="font-semibold text-slate-900 truncate">
              {journey.title}
            </h3>
            <span className="text-[11px] text-slate-400 font-mono">{journey.id}</span>
          </div>
          <p className="text-sm text-slate-600 mt-1">{journey.narrative}</p>

          {/* Zone path */}
          {journey.zones_crossed.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 mt-2 text-xs">
              {journey.zones_crossed.map((z, i) => (
                <span key={i} className="inline-flex items-center gap-1.5">
                  <span className={clsx("w-1.5 h-1.5 rounded-full", ZONE_DOT[z] ?? "bg-slate-400")} />
                  <span className="text-slate-700 capitalize">{z}</span>
                  {i < journey.zones_crossed.length - 1 && (
                    <ArrowRight className="w-3 h-3 text-slate-400" />
                  )}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="shrink-0 text-right">
          <ScorePill score={journey.score} />
          <EncryptionPill journey={journey} />
        </div>
      </div>

      {/* Hop list */}
      <ol className="mt-3 pl-1 space-y-1.5">
        {journey.hops.map((h, idx) => (
          <HopRow key={idx} hop={h} step={idx + 1} />
        ))}
      </ol>

      {/* Compliance findings */}
      {findings.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-3 space-y-1.5">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
            Compliance impact on this journey
          </div>
          {findings.map((f) => (
            <div
              key={f.rule}
              className={clsx(
                "text-xs px-2 py-1.5 rounded border",
                f.status === "fail" && "bg-rose-50 border-rose-200 text-rose-800",
                f.status === "warn" && "bg-amber-50 border-amber-200 text-amber-800",
                f.status === "pass" && "bg-emerald-50 border-emerald-200 text-emerald-800",
                f.status === "not_applicable" && "bg-slate-50 border-slate-200 text-slate-700",
              )}
            >
              <div className="flex items-center gap-1.5">
                {f.status === "fail" && <AlertOctagon className="w-3 h-3" />}
                {f.status === "warn" && <AlertTriangle className="w-3 h-3" />}
                {f.status === "pass" && <CheckCircle2 className="w-3 h-3" />}
                <span className="font-mono text-[10px] opacity-70">{f.rule}</span>
                <span className="font-medium uppercase tracking-wide text-[10px]">
                  {f.status}
                </span>
              </div>
              <div className="mt-0.5">{f.message}</div>
            </div>
          ))}
        </div>
      )}

      {journey.warnings.length > 0 && (
        <div className="mt-2 text-[11px] text-amber-700 flex items-start gap-1.5">
          <ShieldQuestion className="w-3 h-3 mt-0.5" />
          <span>{journey.warnings.join(" ")}</span>
        </div>
      )}
    </div>
  );
}

function HopRow({ hop, step }: { hop: JourneyHop; step: number }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-brand-50 text-brand-700 text-[11px] font-semibold tabular-nums">
        {step}
      </span>
      <span className="font-medium text-slate-900">{hop.from_name || hop.from}</span>
      <span className="text-slate-300">·</span>
      <span className="text-xs text-slate-500 font-mono">
        {hop.protocol ?? "?"}
        {hop.port ? `:${hop.port}` : ""}
      </span>
      <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
      <span className="font-medium text-slate-900">{hop.to_name || hop.to}</span>
      <HopEncIcon enc={hop.encrypted} />
      {hop.direction_inferred && (
        <span className="text-[10px] text-amber-600 italic">(direction inferred)</span>
      )}
    </li>
  );
}

function HopEncIcon({ enc }: { enc: boolean | null | undefined }) {
  if (enc === true) {
    return <Lock className="w-3 h-3 text-emerald-600" aria-label="encrypted" />;
  }
  if (enc === false) {
    return <Unlock className="w-3 h-3 text-rose-600" aria-label="unencrypted" />;
  }
  return <Unlock className="w-3 h-3 text-slate-300" aria-label="unknown" />;
}

function ScorePill({ score }: { score: number }) {
  const tone =
    score >= 80
      ? "bg-rose-50 text-rose-700 ring-1 ring-rose-200"
      : score >= 50
      ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
      : "bg-slate-100 text-slate-700 ring-1 ring-slate-200";
  return (
    <span className={clsx("pill", tone)}>
      score {score}
    </span>
  );
}

function EncryptionPill({ journey }: { journey: Journey }) {
  if (journey.is_fully_encrypted === true) {
    return (
      <span className="pill bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 mt-1">
        <Lock className="w-3 h-3" /> end-to-end TLS
      </span>
    );
  }
  if (journey.has_unencrypted_hop) {
    return (
      <span className="pill bg-rose-50 text-rose-700 ring-1 ring-rose-200 mt-1">
        <Unlock className="w-3 h-3" /> unencrypted hop
      </span>
    );
  }
  return (
    <span className="pill bg-slate-100 text-slate-700 ring-1 ring-slate-200 mt-1">
      <ShieldQuestion className="w-3 h-3" /> encryption unknown
    </span>
  );
}
