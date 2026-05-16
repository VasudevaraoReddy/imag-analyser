import type { AnalysisResult } from "../types";
import { Lock, Unlock, HelpCircle } from "lucide-react";

type Props = {
  result: AnalysisResult;
  kind: "north_south" | "east_west";
};

export function FlowsTable({ result, kind }: Props) {
  const ids = new Set(result.flows[kind]);
  const rows = result.connections.filter((c) => ids.has(c.id));
  const cname = (id: string) =>
    result.components.find((c) => c.id === id)?.name ?? id;

  if (rows.length === 0) {
    return <div className="text-slate-500 text-sm p-3">No flows in this category.</div>;
  }

  return (
    <div className="overflow-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-slate-600 text-left text-xs uppercase tracking-wide">
          <tr>
            <th className="px-3 py-2 font-medium">From</th>
            <th className="px-3 py-2 font-medium">To</th>
            <th className="px-3 py-2 font-medium">Label</th>
            <th className="px-3 py-2 font-medium">Protocol</th>
            <th className="px-3 py-2 font-medium">Port</th>
            <th className="px-3 py-2 font-medium">Encrypted</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id} className="border-b border-slate-100">
              <td className="px-3 py-2 text-slate-900">{cname(c.from)}</td>
              <td className="px-3 py-2 text-slate-900">{cname(c.to)}</td>
              <td className="px-3 py-2 text-slate-600">{c.label ?? "—"}</td>
              <td className="px-3 py-2 text-slate-600 font-mono text-xs">{c.protocol ?? "—"}</td>
              <td className="px-3 py-2 text-slate-600 tabular-nums">{c.port ?? "—"}</td>
              <td className="px-3 py-2">
                {c.encrypted === true ? (
                  <span className="inline-flex items-center gap-1 text-emerald-700"><Lock className="w-3 h-3"/> yes</span>
                ) : c.encrypted === false ? (
                  <span className="inline-flex items-center gap-1 text-rose-700"><Unlock className="w-3 h-3"/> no</span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-slate-400"><HelpCircle className="w-3 h-3"/> unknown</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
