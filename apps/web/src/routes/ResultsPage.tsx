import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import clsx from "clsx";
import { Download, FileText, Layers, ChevronLeft, MessageSquare } from "lucide-react";
import { getAnalysis, processedImageUrl, imageUrl } from "../lib/api";
import { ComponentsTable } from "../components/ComponentsTable";
import { FlowsTable } from "../components/FlowsTable";
import { JsonViewer } from "../components/JsonViewer";
import { ImageWithOverlay } from "../components/ImageWithOverlay";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { ProviderBadge } from "../components/ProviderBadge";
import { ReviewStatePill } from "../components/StatusPill";
import { SummaryStats } from "../components/Summary";
import { FlowMatrix } from "../components/FlowMatrix";
import { ComplianceChecklist } from "../components/ComplianceChecklist";
import { JourneysPanel } from "../components/JourneysPanel";

type Tab =
  | "journeys"
  | "components"
  | "trust_zones"
  | "network_view"   // flow matrix + N-S + E-W rolled into one secondary tab
  | "compliance"
  | "warnings"
  | "raw";

export default function ResultsPage() {
  const { id } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis", id],
    queryFn: () => getAnalysis(id!),
    enabled: !!id,
  });

  const [tab, setTab] = useState<Tab>("journeys");
  const [highlight, setHighlight] = useState<string | null>(null);
  const [highlightedJourney, setHighlightedJourney] = useState<string | null>(null);
  const [variant, setVariant] = useState<"original" | "processed">("processed");
  const [showOverlay, setShowOverlay] = useState(true);

  if (isLoading) return <div className="p-6 text-slate-500">Loading analysis…</div>;
  if (error || !data) return <div className="p-6 text-rose-600">Could not load analysis.</div>;

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "journeys", label: "Journeys", count: data.journeys?.length ?? 0 },
    { key: "components", label: "Components", count: data.components.length },
    { key: "trust_zones", label: "Trust zones", count: data.trust_zones.length },
    { key: "network_view", label: "Network view" },
    { key: "compliance", label: "Compliance", count: data.compliance_findings.length },
    { key: "warnings", label: "Warnings", count: data.parsing_warnings.length },
    { key: "raw", label: "Raw JSON" },
  ];

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.filename}.analysis.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const liveImageUrl = variant === "original"
    ? imageUrl(data.diagram_id)
    : processedImageUrl(data.diagram_id);

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center justify-between gap-3">
        <Link to="/reviews" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
          <ChevronLeft className="w-4 h-4" /> Back to Arc Reviews
        </Link>
        <div className="flex gap-2">
          <Link to={`/chat?analysis_id=${data.diagram_id}`} className="btn-secondary">
            <MessageSquare className="w-4 h-4" /> Ask the bot
          </Link>
          <Link to={`/results/${data.diagram_id}/report`} className="btn-primary">
            <FileText className="w-4 h-4" /> View report
          </Link>
          <button onClick={exportJson} className="btn-secondary">
            <Download className="w-4 h-4" /> JSON
          </button>
        </div>
      </div>

      {/* Header card */}
      <div className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {data.arc_number && (
                <span className="pill bg-brand-50 text-brand-700 ring-1 ring-brand-200 font-mono">
                  {data.arc_number}
                </span>
              )}
              <div className="text-xs uppercase tracking-wider text-slate-500">Architecture Review</div>
            </div>
            <h1 className="text-xl font-semibold tracking-tight text-slate-900 truncate mt-1">
              {data.title || data.filename}
            </h1>
            {data.description && (
              <p className="text-sm text-slate-600 mt-1 line-clamp-2">{data.description}</p>
            )}
            <div className="text-xs text-slate-500 mt-1">
              {data.filename} · {new Date(data.submitted_at).toLocaleString()}
              {data.submitted_by?.name || data.submitted_by?.employee_id ? (
                <>
                  {" · "}Submitted by{" "}
                  <span className="text-slate-700 font-medium">
                    {data.submitted_by.name || data.submitted_by.employee_id}
                  </span>
                  {data.submitted_by.name && data.submitted_by.employee_id && (
                    <span className="ml-1 font-mono">({data.submitted_by.employee_id})</span>
                  )}
                </>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ProviderBadge provider={data.primary_provider} />
            {data.cloud_providers.length > 1 && data.cloud_providers.map((p) => (
              <ProviderBadge key={p} provider={p} />
            ))}
            <span className="pill bg-slate-100 text-slate-700 ring-1 ring-slate-200">
              {data.diagram_style.replaceAll("_", " ")}
            </span>
            <ConfidenceBadge value={data.overall_confidence} />
            <ReviewStatePill state={data.review_state} />
          </div>
        </div>
      </div>

      {/* Stats */}
      <SummaryStats result={data} />

      {/* Diagram (full width) */}
      <div className="space-y-4">
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-brand" />
              <div className="text-sm font-medium text-slate-700">Diagram</div>
            </div>
            <div className="flex items-center gap-1">
              <div className="inline-flex rounded-md border border-slate-200 bg-slate-100 p-0.5 text-xs">
                <button
                  className={clsx("px-2 py-1 rounded", variant === "processed" ? "bg-white shadow-sm text-brand" : "text-slate-500")}
                  onClick={() => setVariant("processed")}
                >Processed</button>
                <button
                  className={clsx("px-2 py-1 rounded", variant === "original" ? "bg-white shadow-sm text-brand" : "text-slate-500")}
                  onClick={() => setVariant("original")}
                >Original</button>
              </div>
              <label className="ml-2 inline-flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showOverlay}
                  onChange={(e) => setShowOverlay(e.target.checked)}
                  className="accent-brand"
                /> Overlay
              </label>
            </div>
          </div>
          <ImageWithOverlay
            result={data}
            imageUrl={liveImageUrl}
            variant={variant}
            highlightedComponentId={highlight}
            onSelectComponent={(id) => setHighlight(id)}
            showOverlay={showOverlay}
            highlightedJourneyId={highlightedJourney}
          />
          {highlightedJourney && (
            <div className="flex items-center justify-between text-xs bg-brand-50 ring-1 ring-brand-100 rounded-md px-3 py-1.5">
              <span className="text-brand-700">
                Highlighting journey:{" "}
                <span className="font-semibold">
                  {data.journeys?.find((j) => j.id === highlightedJourney)?.title}
                </span>
              </span>
              <button
                className="text-brand-700 hover:underline"
                onClick={() => setHighlightedJourney(null)}
              >
                Clear
              </button>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 pt-1">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-4 h-0.5 bg-flow-ns" /> north-south
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-4 h-0.5 bg-flow-ew" /> east-west
            </span>
            <span className="text-slate-300">|</span>
            {(["external","perimeter","internal","restricted","management"] as const).map((k) => (
              <span key={k} className="inline-flex items-center gap-1.5">
                <span className={clsx("inline-block w-3 h-3 rounded border", `border-zone-${k}`)} /> {k}
              </span>
            ))}
          </div>
        </div>

        <div className="card overflow-hidden">
          <div className="border-b border-slate-200 flex overflow-x-auto bg-slate-50/60">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={clsx(
                  "px-3 py-2.5 text-sm whitespace-nowrap inline-flex items-center gap-1.5 border-b-2",
                  tab === t.key
                    ? "border-brand text-brand font-medium bg-white"
                    : "border-transparent text-slate-500 hover:text-slate-800",
                )}
              >
                {t.label}
                {typeof t.count === "number" && (
                  <span className={clsx(
                    "px-1.5 rounded text-xs",
                    tab === t.key ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-500",
                  )}>{t.count}</span>
                )}
              </button>
            ))}
          </div>
          <div className="max-h-[900px] overflow-auto">
            {tab === "journeys" && (
              <JourneysPanel
                result={data}
                selectedJourneyId={highlightedJourney}
                onSelect={setHighlightedJourney}
              />
            )}
            {tab === "components" && (
              <ComponentsTable
                result={data}
                highlightedId={highlight}
                onHover={setHighlight}
                onSelect={setHighlight}
              />
            )}
            {tab === "trust_zones" && (
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-slate-600 text-left text-xs uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-2 font-medium">Name</th>
                    <th className="px-3 py-2 font-medium">Kind</th>
                    <th className="px-3 py-2 font-medium">Members</th>
                  </tr>
                </thead>
                <tbody>
                  {data.trust_zones.map((z) => {
                    const members = data.components.filter((c) => c.trust_zone === z.id);
                    return (
                      <tr key={z.id} className="border-b border-slate-100">
                        <td className="px-3 py-2 font-medium text-slate-900">{z.name}</td>
                        <td className="px-3 py-2">
                          <span className={clsx("pill", `bg-zone-${z.kind}/10 text-zone-${z.kind}`)}
                                style={{ background: `var(--tw-bg, transparent)` }}>
                            <span className={clsx("w-1.5 h-1.5 rounded-full", `bg-zone-${z.kind}`)} />
                            {z.kind}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-slate-600 text-xs">
                          {members.map((m) => m.name).join(" · ") || "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {tab === "network_view" && (
              <div className="p-4 space-y-6">
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2">
                    Zone-to-zone matrix
                  </div>
                  <FlowMatrix result={data} />
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2">
                    North-South flows ({data.flows.north_south.length})
                  </div>
                  <FlowsTable result={data} kind="north_south" />
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2">
                    East-West flows ({data.flows.east_west.length})
                  </div>
                  <FlowsTable result={data} kind="east_west" />
                </div>
              </div>
            )}
            {tab === "compliance" && (
              <div className="p-2">
                <ComplianceChecklist result={data} compact />
              </div>
            )}
            {tab === "warnings" && (
              <div className="space-y-2 p-3">
                {data.parsing_warnings.length === 0 ? (
                  <div className="text-slate-500 text-sm">No warnings.</div>
                ) : data.parsing_warnings.map((w, i) => (
                  <div key={i} className="bg-amber-50 border border-amber-200 rounded p-2 text-sm">
                    <div className="font-medium text-amber-900">{w.kind}</div>
                    <div className="text-slate-700">{w.message}</div>
                  </div>
                ))}
              </div>
            )}
            {tab === "raw" && <div className="p-3"><JsonViewer value={data} /></div>}
          </div>
        </div>
      </div>
    </div>
  );
}
