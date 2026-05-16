import type { AnalysisResult } from "../types";
import clsx from "clsx";

type Stat = { label: string; value: string | number; sub?: string; accent?: string };

export function SummaryStats({ result }: { result: AnalysisResult }) {
  const byProvider = result.components.reduce<Record<string, number>>((acc, c) => {
    acc[c.provider] = (acc[c.provider] ?? 0) + 1;
    return acc;
  }, {});
  const byTier = result.components.reduce<Record<string, number>>((acc, c) => {
    acc[c.tier] = (acc[c.tier] ?? 0) + 1;
    return acc;
  }, {});
  const findings = result.compliance_findings;
  const failures = findings.filter((f) => f.status === "fail").length;
  const warns = findings.filter((f) => f.status === "warn").length;
  const passes = findings.filter((f) => f.status === "pass").length;

  const stats: Stat[] = [
    {
      label: "Components",
      value: result.components.length,
      sub: Object.entries(byTier).slice(0, 4)
        .map(([k, v]) => `${k}:${v}`).join(" · "),
      accent: "brand",
    },
    {
      label: "Connections",
      value: result.connections.length,
      sub: `N-S ${result.flows.north_south.length} · E-W ${result.flows.east_west.length}`,
    },
    {
      label: "Trust zones",
      value: result.trust_zones.length,
      sub: result.trust_zones.map((z) => z.kind).join(" · "),
    },
    {
      label: "Compliance",
      value: `${passes}/${findings.length}`,
      sub: `${failures} fail · ${warns} warn`,
      accent: failures ? "rose" : warns ? "amber" : "emerald",
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {stats.map((s) => (
        <div key={s.label} className={clsx(
          "card p-4 relative overflow-hidden",
        )}>
          <div className={clsx(
            "absolute left-0 top-0 bottom-0 w-1",
            s.accent === "brand" && "bg-brand",
            s.accent === "rose" && "bg-rose-500",
            s.accent === "amber" && "bg-amber-500",
            s.accent === "emerald" && "bg-emerald-500",
            !s.accent && "bg-slate-200",
          )} />
          <div className="text-xs uppercase tracking-wide text-slate-500 font-medium">{s.label}</div>
          <div className="text-2xl font-semibold mt-1 text-slate-900">{s.value}</div>
          {s.sub && <div className="text-xs text-slate-500 mt-1 truncate" title={s.sub}>{s.sub}</div>}
        </div>
      ))}
    </div>
  );
}
