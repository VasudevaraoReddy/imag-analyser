import clsx from "clsx";
import type { AnalysisResult, ComplianceFinding } from "../types";
import { StatusPill, SeverityDot } from "./StatusPill";

const RULE_TITLES: Record<string, string> = {
  WAF_BEFORE_APP: "WAF/Edge guard precedes app tier",
  NO_PUBLIC_DATA_TIER: "Data tier not in public zones",
  TLS_ON_EXTERNAL_EDGES: "TLS on external-facing edges",
  ENCRYPTION_TO_RESTRICTED: "Encryption into restricted zones",
  PRIVATE_ENDPOINTS_FOR_PAAS: "Private endpoints for PaaS data services",
  IDENTITY_PRESENT: "Identity provider on external flows",
  LOGGING_PRESENT: "Logging / monitoring / SIEM present",
  SECRETS_VAULT_PRESENT: "Secrets vault for databases / SaaS",
};

export function ComplianceChecklist({
  result,
  compact = false,
}: {
  result: AnalysisResult;
  compact?: boolean;
}) {
  const findings = result.compliance_findings;
  const order = ["critical", "high", "medium", "low", "info"] as const;
  const sorted = [...findings].sort((a, b) => {
    const sa = order.indexOf(a.severity as typeof order[number]);
    const sb = order.indexOf(b.severity as typeof order[number]);
    if (sa !== sb) return sa - sb;
    return a.rule.localeCompare(b.rule);
  });

  const compName = (id: string) =>
    result.components.find((c) => c.id === id)?.name ?? id;
  const connName = (id: string) => {
    const c = result.connections.find((c) => c.id === id);
    if (!c) return id;
    return `${compName(c.from)} → ${compName(c.to)}`;
  };

  return (
    <ul className={clsx("divide-y divide-slate-100", compact ? "" : "border border-slate-200 rounded-lg bg-white")}>
      {sorted.map((f) => (
        <li key={f.rule} className="p-3 flex gap-3 items-start">
          <div className="pt-1"><SeverityDot severity={f.severity as never} /></div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-medium text-slate-900">
                {RULE_TITLES[f.rule] ?? f.rule}
              </div>
              <span className="font-mono text-[11px] text-slate-400">{f.rule}</span>
              <StatusPill status={f.status as never}>{f.status}</StatusPill>
              <span className="text-[11px] uppercase tracking-wide text-slate-500">
                severity: {f.severity}
              </span>
            </div>
            <div className="text-sm text-slate-700 mt-1">{f.message}</div>
            {(f.affected_component_ids.length + f.affected_connection_ids.length) > 0 && (
              <div className="text-xs text-slate-500 mt-1.5">
                <span className="font-medium">Affects: </span>
                {[
                  ...f.affected_component_ids.map(compName),
                  ...f.affected_connection_ids.map(connName),
                ].join(" · ")}
              </div>
            )}
          </div>
        </li>
      ))}
      {sorted.length === 0 && (
        <li className="p-3 text-sm text-slate-500">No compliance findings.</li>
      )}
    </ul>
  );
}
