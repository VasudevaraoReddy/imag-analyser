import type { AnalysisResult } from "../types";
import clsx from "clsx";

const ZONE_ORDER = ["external", "perimeter", "dmz", "internal", "restricted", "management"];

export function FlowMatrix({ result }: { result: AnalysisResult }) {
  const zoneIdToKind: Record<string, string> = {};
  for (const z of result.trust_zones) zoneIdToKind[z.id] = z.kind;
  const compZone: Record<string, string> = {};
  for (const c of result.components) compZone[c.id] = zoneIdToKind[c.trust_zone] ?? "internal";

  const matrix: Record<string, Record<string, number>> = {};
  for (const k of ZONE_ORDER) {
    matrix[k] = {};
    for (const k2 of ZONE_ORDER) matrix[k][k2] = 0;
  }
  for (const c of result.connections) {
    if (!c.is_data_flow) continue;
    const from = compZone[c.from] ?? "internal";
    const to = compZone[c.to] ?? "internal";
    if (!ZONE_ORDER.includes(from) || !ZONE_ORDER.includes(to)) continue;
    matrix[from][to] += 1;
  }
  const present = ZONE_ORDER.filter((k) => {
    return ZONE_ORDER.some((k2) => matrix[k][k2] > 0 || matrix[k2][k] > 0);
  });
  if (present.length === 0) {
    return <div className="text-sm text-slate-500 p-3">No data flows to chart.</div>;
  }

  return (
    <div className="overflow-auto">
      <table className="text-sm border-collapse">
        <thead>
          <tr>
            <th className="text-left text-xs font-semibold uppercase text-slate-500 px-2 py-2">
              From → To
            </th>
            {present.map((k) => (
              <th key={k} className="px-2 py-2 text-xs font-semibold text-slate-600 capitalize">
                {k}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {present.map((from) => (
            <tr key={from}>
              <td className="text-xs font-semibold text-slate-600 capitalize px-2 py-1.5">{from}</td>
              {present.map((to) => {
                const n = matrix[from][to];
                const same = from === to;
                return (
                  <td key={to} className="px-1 py-1">
                    <div className={clsx(
                      "w-12 h-9 rounded flex items-center justify-center text-sm font-medium border",
                      n === 0 ? "bg-slate-50 text-slate-300 border-slate-100" :
                      same ? "bg-sky-50 text-sky-700 border-sky-200" :
                      "bg-orange-50 text-orange-700 border-orange-200",
                    )}>
                      {n || "·"}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 text-xs text-slate-500 flex gap-4">
        <span><span className="inline-block w-3 h-3 align-middle bg-orange-100 border border-orange-200" /> cross-zone (north-south)</span>
        <span><span className="inline-block w-3 h-3 align-middle bg-sky-100 border border-sky-200" /> intra-zone (east-west)</span>
      </div>
    </div>
  );
}
