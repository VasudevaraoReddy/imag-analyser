import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import clsx from "clsx";
import { ArrowLeft, Printer, Download, FileText } from "lucide-react";
import { YES_BANK_BLUE, YES_BANK_RED, YES_BANK_LOGO } from "../lib/brand";
import { getAnalysis, processedImageUrl } from "../lib/api";
import { ProviderBadge } from "../components/ProviderBadge";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { ReviewStatePill, StatusPill, SeverityDot } from "../components/StatusPill";
import { FlowMatrix } from "../components/FlowMatrix";
import { ImageWithOverlay } from "../components/ImageWithOverlay";
import type { AnalysisResult, ComplianceFinding } from "../types";

const RULE_TITLES: Record<string, string> = {
  WAF_BEFORE_APP: "WAF / edge guard precedes application tier",
  NO_PUBLIC_DATA_TIER: "Data tier is not in public trust zones",
  TLS_ON_EXTERNAL_EDGES: "TLS / mTLS on all external-facing edges",
  ENCRYPTION_TO_RESTRICTED: "Encryption on traffic entering restricted zones",
  PRIVATE_ENDPOINTS_FOR_PAAS: "Private endpoints for managed data services",
  IDENTITY_PRESENT: "Identity provider on external flows",
  LOGGING_PRESENT: "Logging / monitoring / SIEM is present",
  SECRETS_VAULT_PRESENT: "Secrets vault for databases / SaaS connections",
};

function execSummary(d: AnalysisResult): string {
  const failures = d.compliance_findings.filter((f) => f.status === "fail");
  const warns = d.compliance_findings.filter((f) => f.status === "warn");
  const critical = failures.filter((f) => f.severity === "critical").length;
  const high = failures.filter((f) => f.severity === "high").length;

  const cloud = d.cloud_providers.length === 0
    ? "an unknown cloud"
    : d.cloud_providers.join(" + ");

  const flowSummary = `${d.flows.north_south.length} north-south and ` +
    `${d.flows.east_west.length} east-west data flow${d.flows.east_west.length === 1 ? "" : "s"}`;

  const verdict =
    d.review_state === "rejected"
      ? "REJECTED — critical issues require remediation before deployment."
      : d.review_state === "auto_review_recommended"
      ? "The architecture meets baseline security controls. Routine review recommended."
      : "HUMAN REVIEW REQUIRED — at least one control could not be verified or has a high-severity gap.";

  return (
    `This architecture targets ${cloud}, with ${d.components.length} component(s) ` +
    `across ${d.trust_zones.length} trust zone(s). The analyzer identified ${flowSummary}. ` +
    `Of ${d.compliance_findings.length} compliance checks, ${failures.length} failed ` +
    `(${critical} critical · ${high} high), ${warns.length} produced warnings, and ` +
    `${d.compliance_findings.length - failures.length - warns.length} passed or were not applicable. ` +
    verdict
  );
}

function inventoryByGroup(d: AnalysisResult, key: "provider" | "tier" | "service_type") {
  const groups: Record<string, AnalysisResult["components"]> = {};
  for (const c of d.components) {
    const k = c[key];
    (groups[k] ||= []).push(c);
  }
  return Object.entries(groups).sort((a, b) => b[1].length - a[1].length);
}

function FindingRow({ f, d }: { f: ComplianceFinding; d: AnalysisResult }) {
  const cname = (id: string) => d.components.find((c) => c.id === id)?.name ?? id;
  const ename = (id: string) => {
    const e = d.connections.find((e) => e.id === id);
    return e ? `${cname(e.from)} → ${cname(e.to)}` : id;
  };
  const affects = [
    ...f.affected_component_ids.map(cname),
    ...f.affected_connection_ids.map(ename),
  ];
  return (
    <tr className="border-b border-slate-200 align-top">
      <td className="py-2.5 pr-3 w-6"><SeverityDot severity={f.severity as never} /></td>
      <td className="py-2.5 pr-3">
        <div className="font-medium text-slate-900">{RULE_TITLES[f.rule] ?? f.rule}</div>
        <div className="text-[11px] text-slate-400 font-mono">{f.rule}</div>
      </td>
      <td className="py-2.5 pr-3"><StatusPill status={f.status as never}>{f.status}</StatusPill></td>
      <td className="py-2.5 pr-3 text-xs capitalize text-slate-600">{f.severity}</td>
      <td className="py-2.5 pr-3 text-sm text-slate-700">
        <div>{f.message}</div>
        {affects.length > 0 && (
          <div className="text-xs text-slate-500 mt-1">Affects: {affects.join(" · ")}</div>
        )}
      </td>
    </tr>
  );
}

export default function ReportPage() {
  const { id } = useParams();
  const { data: d, isLoading, error } = useQuery({
    queryKey: ["analysis", id],
    queryFn: () => getAnalysis(id!),
    enabled: !!id,
  });

  if (isLoading) return <div className="p-6 text-slate-500">Loading report…</div>;
  if (error || !d) return <div className="p-6 text-rose-600">Could not load report.</div>;

  const findingsOrdered = [...d.compliance_findings].sort((a, b) => {
    const sev = ["critical", "high", "medium", "low", "info"];
    const sa = sev.indexOf(a.severity);
    const sb = sev.indexOf(b.severity);
    if (sa !== sb) return sa - sb;
    return a.rule.localeCompare(b.rule);
  });

  const inventoryProv = inventoryByGroup(d, "provider");
  const inventoryTier = inventoryByGroup(d, "tier");

  return (
    // The global body has overflow:hidden so the app-shell layout stays
    // pinned. The report needs its own scroll context — h-screen +
    // overflow-y-auto here. In print mode we drop both so the browser's
    // pagination can flow naturally across pages.
    <div className="bg-slate-100 h-screen overflow-y-auto print:h-auto print:overflow-visible">
      {/* Toolbar (hidden on print) */}
      <div className="no-print text-white sticky top-0 z-10" style={{ backgroundColor: YES_BANK_BLUE }}>
        <div className="max-w-4xl mx-auto px-8 py-3 flex items-center justify-between">
          <Link to={`/results/${d.diagram_id}`} className="inline-flex items-center gap-1 text-sm text-white/85 hover:text-white">
            <ArrowLeft className="w-4 h-4" /> Back to analysis
          </Link>
          <div className="flex gap-2">
            <button onClick={() => window.print()} className="btn bg-white/15 text-white hover:bg-white/25">
              <Printer className="w-4 h-4" /> Print / Save as PDF
            </button>
            <button
              onClick={() => {
                const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url; a.download = `${d.filename}.analysis.json`; a.click();
                URL.revokeObjectURL(url);
              }}
              className="btn bg-white/15 text-white hover:bg-white/25"
            >
              <Download className="w-4 h-4" /> JSON
            </button>
          </div>
        </div>
      </div>

      {/* Page sheet */}
      <div className="max-w-4xl mx-auto bg-white shadow-elev my-6 print:my-0 print:shadow-none">
        {/* Cover */}
        <header className="text-white px-10 py-10 print:py-8 relative" style={{ backgroundColor: YES_BANK_BLUE }}>
          <div className="absolute top-0 left-0 right-0 h-1" style={{ backgroundColor: YES_BANK_RED }} />
          <div className="flex items-center gap-3">
            <div className="bg-white rounded-md p-1.5 shadow-sm">
              <img src={YES_BANK_LOGO} alt="YES BANK" className="h-9 w-auto" />
            </div>
            <div className="border-l border-white/30 pl-3">
              <div className="flex items-center gap-2 text-white/85 text-xs uppercase tracking-[0.2em]">
                <FileText className="w-4 h-4" /> Architecture Security Review
              </div>
              <div className="text-[11px] text-white/65 mt-0.5">YES BANK · Internal use only</div>
            </div>
          </div>
          {d.arc_number && (
            <div className="inline-block mt-5 px-2.5 py-1 rounded bg-white/15 text-white text-xs font-mono ring-1 ring-white/25">
              {d.arc_number}
            </div>
          )}
          <h1 className="text-3xl font-semibold tracking-tight mt-2">
            {d.title || d.filename}
          </h1>
          {d.description && (
            <p className="text-white/85 text-sm mt-2 max-w-2xl">{d.description}</p>
          )}
          <div className="text-white/80 text-sm mt-3">
            Source file: <span className="font-mono">{d.filename}</span>
          </div>
          <div className="text-white/80 text-sm">
            Generated: {new Date(d.submitted_at).toLocaleString()}
          </div>
          {(d.submitted_by?.name || d.submitted_by?.employee_id) && (
            <div className="text-white/80 text-sm">
              Submitted by:{" "}
              <span className="text-white font-medium">
                {d.submitted_by.name || d.submitted_by.employee_id}
              </span>
              {d.submitted_by.name && d.submitted_by.employee_id && (
                <span className="ml-1 font-mono">({d.submitted_by.employee_id})</span>
              )}
              {d.submitted_by.role && (
                <span className="ml-1 text-white/70">· {d.submitted_by.role}</span>
              )}
            </div>
          )}
          <div className="flex flex-wrap gap-2 mt-5">
            <ProviderBadge provider={d.primary_provider} />
            {d.cloud_providers.length > 1 && d.cloud_providers.map((p) => (
              <ProviderBadge key={p} provider={p} />
            ))}
            <ConfidenceBadge value={d.overall_confidence} />
            <ReviewStatePill state={d.review_state} />
            <span className="pill bg-white/15 text-white ring-1 ring-white/25">
              {d.diagram_style.replaceAll("_", " ")}
            </span>
          </div>
        </header>

        <div className="px-10 py-8 space-y-10 text-slate-800">
          {/* 1. Executive summary */}
          <section>
            <SectionTitle n={1} title="Executive summary" />
            <p className="text-[15px] leading-relaxed">{execSummary(d)}</p>
            <KeyStats d={d} />
          </section>

          {/* 2. Diagram */}
          <section>
            <SectionTitle n={2} title="Analyzed diagram" />
            <ImageWithOverlay result={d} imageUrl={processedImageUrl(d.diagram_id)} variant="processed" />
            <div className="text-xs text-slate-500 mt-2">
              Bounding boxes are colored by trust zone; orange arrows are north-south flows, blue are east-west.
              Solid lines are data flows, dashed lines are management/dependency relations.
            </div>
          </section>

          {/* 3. Compliance */}
          <section>
            <SectionTitle n={3} title="Compliance findings" />
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-300">
                <tr>
                  <th className="py-2 pr-3"></th>
                  <th className="py-2 pr-3 font-medium">Rule</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Severity</th>
                  <th className="py-2 pr-3 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {findingsOrdered.map((f) => <FindingRow key={f.rule} f={f} d={d} />)}
              </tbody>
            </table>
          </section>

          {/* 4. Inventory */}
          <section>
            <SectionTitle n={4} title="Component inventory" />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <InventoryCard title="By provider" rows={inventoryProv} />
              <InventoryCard title="By tier" rows={inventoryTier} />
            </div>
            <div className="mt-6 overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-300">
                  <tr>
                    <th className="py-2 pr-3 font-medium">#</th>
                    <th className="py-2 pr-3 font-medium">Name</th>
                    <th className="py-2 pr-3 font-medium">Canonical</th>
                    <th className="py-2 pr-3 font-medium">Type</th>
                    <th className="py-2 pr-3 font-medium">Provider</th>
                    <th className="py-2 pr-3 font-medium">Zone</th>
                    <th className="py-2 pr-3 font-medium">Tier</th>
                  </tr>
                </thead>
                <tbody>
                  {d.components.map((c, i) => (
                    <tr key={c.id} className="border-b border-slate-100 align-top">
                      <td className="py-1.5 pr-3 text-slate-400 tabular-nums">{i + 1}</td>
                      <td className="py-1.5 pr-3 font-medium text-slate-900">{c.name}</td>
                      <td className="py-1.5 pr-3 text-slate-600">{c.canonical_name || "—"}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs text-slate-600">{c.service_type}</td>
                      <td className="py-1.5 pr-3 text-slate-600">{c.provider}</td>
                      <td className="py-1.5 pr-3 text-slate-600">
                        {d.trust_zones.find((z) => z.id === c.trust_zone)?.name ?? c.trust_zone}
                      </td>
                      <td className="py-1.5 pr-3 text-slate-600">{c.tier}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* 5. Trust zones */}
          <section>
            <SectionTitle n={5} title="Trust zones" />
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-300">
                <tr>
                  <th className="py-2 pr-3 font-medium">Name</th>
                  <th className="py-2 pr-3 font-medium">Kind</th>
                  <th className="py-2 pr-3 font-medium">Members</th>
                </tr>
              </thead>
              <tbody>
                {d.trust_zones.map((z) => {
                  const members = d.components.filter((c) => c.trust_zone === z.id);
                  return (
                    <tr key={z.id} className="border-b border-slate-100 align-top">
                      <td className="py-1.5 pr-3 font-medium">{z.name}</td>
                      <td className="py-1.5 pr-3">
                        <span className={clsx("pill bg-slate-100 text-slate-700 ring-1 ring-slate-200")}>
                          <span className={clsx("w-1.5 h-1.5 rounded-full", `bg-zone-${z.kind}`)} />
                          {z.kind}
                        </span>
                      </td>
                      <td className="py-1.5 pr-3 text-slate-600">
                        {members.length === 0 ? "—" : members.map((m) => m.name).join(" · ")}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          {/* 6. Flows */}
          <section>
            <SectionTitle n={6} title="Data flows" />
            <h3 className="text-sm font-semibold text-slate-700 mt-2 mb-2">Zone-to-zone matrix</h3>
            <FlowMatrix result={d} />

            <h3 className="text-sm font-semibold text-slate-700 mt-6 mb-2">
              North-South ({d.flows.north_south.length})
            </h3>
            <FlowList ids={d.flows.north_south} d={d} />

            <h3 className="text-sm font-semibold text-slate-700 mt-4 mb-2">
              East-West ({d.flows.east_west.length})
            </h3>
            <FlowList ids={d.flows.east_west} d={d} />
          </section>

          {/* 7. Parsing warnings */}
          {d.parsing_warnings.length > 0 && (
            <section>
              <SectionTitle n={7} title="Parsing warnings" />
              <ul className="space-y-2">
                {d.parsing_warnings.map((w, i) => (
                  <li key={i} className="border-l-4 border-amber-400 bg-amber-50 p-2.5 text-sm">
                    <div className="font-mono text-[11px] text-amber-700 uppercase">{w.kind}</div>
                    <div className="text-slate-700">{w.message}</div>
                    {w.affected_ids.length > 0 && (
                      <div className="text-xs text-slate-500 mt-0.5">IDs: {w.affected_ids.join(", ")}</div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* 8. Processing telemetry */}
          <section>
            <SectionTitle n={d.parsing_warnings.length > 0 ? 8 : 7} title="Processing telemetry" />
            <table className="w-full text-sm">
              <tbody>
                {[
                  ["Image preprocessing", d.processing_ms.image_prep],
                  ["Document Intelligence (OCR)", d.processing_ms.doc_intelligence],
                  ["Vision LLM extraction", d.processing_ms.vision_llm],
                  ["Post-processing & rules", d.processing_ms.post_process],
                  ["Total", d.processing_ms.total],
                ].map(([label, ms]) => (
                  <tr key={label as string} className="border-b border-slate-100">
                    <td className="py-1.5 pr-3 text-slate-600">{label as string}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {(ms as number).toLocaleString()} ms
                    </td>
                  </tr>
                ))}
                <tr>
                  <td className="py-1.5 pr-3 text-slate-600">Tiles processed</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{d.tiles_processed}</td>
                </tr>
                <tr>
                  <td className="py-1.5 pr-3 text-slate-600">Source format</td>
                  <td className="py-1.5 pr-3 text-right">{d.input_format}</td>
                </tr>
                <tr>
                  <td className="py-1.5 pr-3 text-slate-600">Source dimensions</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {d.image_dimensions.width} × {d.image_dimensions.height}
                  </td>
                </tr>
              </tbody>
            </table>
          </section>

          <footer className="pt-6 border-t border-slate-200 text-xs text-slate-500">
            <div>This report is generated automatically. It does not replace human security review.</div>
            <div className="mt-1">Confidence: {Math.round(d.overall_confidence * 100)}% · Review state: {d.review_state}</div>
          </footer>
        </div>
      </div>
    </div>
  );
}

function SectionTitle({ n, title }: { n: number; title: string }) {
  return (
    <div className="flex items-center gap-3 mb-4 pb-2 border-b border-slate-200">
      <div className="w-7 h-7 rounded-md bg-brand text-white flex items-center justify-center text-sm font-semibold">
        {n}
      </div>
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">{title}</h2>
    </div>
  );
}

function KeyStats({ d }: { d: AnalysisResult }) {
  const stats = [
    { label: "Components", value: d.components.length },
    { label: "Connections", value: d.connections.length },
    { label: "Trust zones", value: d.trust_zones.length },
    { label: "N-S flows", value: d.flows.north_south.length },
    { label: "E-W flows", value: d.flows.east_west.length },
    { label: "Confidence", value: `${Math.round(d.overall_confidence * 100)}%` },
  ];
  return (
    <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mt-4">
      {stats.map((s) => (
        <div key={s.label} className="border border-slate-200 rounded-md p-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">{s.label}</div>
          <div className="text-xl font-semibold tabular-nums">{s.value}</div>
        </div>
      ))}
    </div>
  );
}

function InventoryCard({ title, rows }: { title: string; rows: [string, AnalysisResult["components"]][] }) {
  return (
    <div className="border border-slate-200 rounded-md p-4">
      <div className="text-xs uppercase tracking-wider text-slate-500 font-medium mb-2">{title}</div>
      <ul className="space-y-1.5">
        {rows.map(([k, v]) => (
          <li key={k} className="flex items-center justify-between text-sm">
            <span className="text-slate-700">{k}</span>
            <span className="tabular-nums text-slate-900 font-medium">{v.length}</span>
          </li>
        ))}
        {rows.length === 0 && <li className="text-sm text-slate-400">No data.</li>}
      </ul>
    </div>
  );
}

function FlowList({ ids, d }: { ids: string[]; d: AnalysisResult }) {
  const cname = (id: string) => d.components.find((c) => c.id === id)?.name ?? id;
  if (ids.length === 0) {
    return <div className="text-sm text-slate-500">None.</div>;
  }
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-200">
        <tr>
          <th className="py-1.5 pr-3 font-medium">From</th>
          <th className="py-1.5 pr-3 font-medium">To</th>
          <th className="py-1.5 pr-3 font-medium">Protocol</th>
          <th className="py-1.5 pr-3 font-medium">Port</th>
          <th className="py-1.5 pr-3 font-medium">Encrypted</th>
        </tr>
      </thead>
      <tbody>
        {ids.map((id) => {
          const e = d.connections.find((c) => c.id === id);
          if (!e) return null;
          return (
            <tr key={id} className="border-b border-slate-100">
              <td className="py-1.5 pr-3 text-slate-900">{cname(e.from)}</td>
              <td className="py-1.5 pr-3 text-slate-900">{cname(e.to)}</td>
              <td className="py-1.5 pr-3 font-mono text-xs">{e.protocol ?? "—"}</td>
              <td className="py-1.5 pr-3 tabular-nums">{e.port ?? "—"}</td>
              <td className="py-1.5 pr-3">
                {e.encrypted === true ? "yes" : e.encrypted === false ? "no" : "unknown"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
