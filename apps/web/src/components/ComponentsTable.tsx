import clsx from "clsx";
import type { AnalysisResult } from "../types";
import { ProviderBadge } from "./ProviderBadge";

type Props = {
  result: AnalysisResult;
  highlightedId?: string | null;
  onHover?: (id: string | null) => void;
  onSelect?: (id: string) => void;
};

export function ComponentsTable({ result, highlightedId, onHover, onSelect }: Props) {
  const zoneName = (zid: string) =>
    result.trust_zones.find((z) => z.id === zid)?.name ?? zid;
  const zoneKind = (zid: string) =>
    result.trust_zones.find((z) => z.id === zid)?.kind ?? "internal";
  const ZONE_DOT: Record<string, string> = {
    external: "bg-rose-500",
    perimeter: "bg-amber-500",
    dmz: "bg-yellow-500",
    internal: "bg-emerald-500",
    restricted: "bg-blue-500",
    management: "bg-violet-500",
  };
  return (
    <div className="overflow-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-slate-600 text-left text-xs uppercase tracking-wide">
          <tr>
            <th className="px-3 py-2 font-medium">Name</th>
            <th className="px-3 py-2 font-medium">Canonical</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Provider</th>
            <th className="px-3 py-2 font-medium">Zone</th>
            <th className="px-3 py-2 font-medium">Tier</th>
            <th className="px-3 py-2 font-medium text-right">Conf</th>
          </tr>
        </thead>
        <tbody>
          {result.components.map((c) => (
            <tr
              key={c.id}
              className={clsx(
                "border-b border-slate-100 cursor-pointer hover:bg-brand-50/40",
                highlightedId === c.id && "bg-amber-50",
              )}
              onMouseEnter={() => onHover?.(c.id)}
              onMouseLeave={() => onHover?.(null)}
              onClick={() => onSelect?.(c.id)}
            >
              <td className="px-3 py-2 font-medium text-slate-900">{c.name}</td>
              <td className="px-3 py-2 text-slate-600">{c.canonical_name || "—"}</td>
              <td className="px-3 py-2 text-slate-600 font-mono text-xs">{c.service_type}</td>
              <td className="px-3 py-2"><ProviderBadge provider={c.provider} /></td>
              <td className="px-3 py-2 text-slate-600">
                <span className="inline-flex items-center gap-1.5">
                  <span className={clsx("w-1.5 h-1.5 rounded-full", ZONE_DOT[zoneKind(c.trust_zone)])} />
                  {zoneName(c.trust_zone)}
                </span>
              </td>
              <td className="px-3 py-2 text-slate-600">{c.tier}</td>
              <td className="px-3 py-2 text-slate-600 text-right tabular-nums">
                {Math.round(c.evidence.confidence * 100)}%
              </td>
            </tr>
          ))}
          {result.components.length === 0 && (
            <tr><td colSpan={7} className="px-3 py-4 text-sm text-slate-500 text-center">No components extracted.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
