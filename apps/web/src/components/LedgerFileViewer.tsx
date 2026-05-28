/**
 * Raw JSONL viewer for one ledger file.
 *
 * Lists every row collapsed by default (compact JSON snippet). Click
 * a row to expand into pretty-printed JSON. Toggle "Include snapshot"
 * to request the full AnalysisResult payload for whole-review rows
 * (off by default — those snapshots are large).
 *
 * Also exposes a "Download raw .jsonl" button — pulls the file exactly
 * as it lives on disk so management can keep an offline copy.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ChevronDown,
  ChevronRight,
  Download,
  FileText,
  Loader2,
  RefreshCw,
} from "lucide-react";

import { downloadLedger, getLedgerRows } from "../lib/api";

export function LedgerFileViewer({
  name,
  defaultOpen = false,
}: {
  name: string;
  defaultOpen?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultOpen);
  const [includeSnapshot, setIncludeSnapshot] = useState(false);
  const [openRow, setOpenRow] = useState<number | null>(null);
  const [downloading, setDownloading] = useState(false);

  const q = useQuery({
    queryKey: ["ledger", name, includeSnapshot],
    queryFn: () => getLedgerRows(name, { limit: 50, includeSnapshot }),
    enabled: expanded, // only fetch when the section is opened
  });

  const triggerDownload = async () => {
    setDownloading(true);
    try {
      await downloadLedger(name);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="rounded-md ring-1 ring-slate-200 bg-white">
      {/* Header bar */}
      <div className="px-3 py-2 flex items-center gap-2 flex-wrap">
        <button
          className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-800 hover:text-brand-700"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
          )}
          <FileText className="w-3.5 h-3.5 text-slate-500" />
          <span className="font-mono text-xs">{name}</span>
        </button>
        {q.data && (
          <span className="text-[11px] text-slate-500 font-mono">
            {q.data.total_rows} rows · {fmtBytes(q.data.size_bytes)}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {expanded && (
            <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-600 cursor-pointer select-none">
              <input
                type="checkbox"
                className="rounded text-brand focus:ring-brand"
                checked={includeSnapshot}
                onChange={(e) => setIncludeSnapshot(e.target.checked)}
              />
              Include full snapshot
            </label>
          )}
          {expanded && (
            <button
              className="btn-secondary text-xs"
              onClick={() => q.refetch()}
              disabled={q.isFetching}
              title="Reload from disk"
            >
              <RefreshCw
                className={clsx(
                  "w-3.5 h-3.5",
                  q.isFetching && "animate-spin",
                )}
              />
            </button>
          )}
          <button
            className="btn-secondary text-xs"
            onClick={triggerDownload}
            disabled={downloading}
            title="Download the raw .jsonl file"
          >
            {downloading ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Download className="w-3.5 h-3.5" />
            )}
            Download
          </button>
        </div>
      </div>

      {/* Body */}
      {expanded && (
        <div className="border-t border-slate-100">
          {q.isLoading && (
            <div className="px-3 py-4 text-xs text-slate-500">Loading…</div>
          )}
          {q.error && (
            <div className="px-3 py-4 text-xs text-rose-600">
              Could not read this file: {(q.error as Error).message}
            </div>
          )}
          {q.data && q.data.items.length === 0 && (
            <div className="px-3 py-4 text-xs text-slate-500">
              File is empty.
            </div>
          )}
          {q.data && q.data.items.length > 0 && (
            <ul className="divide-y divide-slate-100">
              {q.data.items.map((row, i) => (
                <RowItem
                  key={i}
                  row={row}
                  open={openRow === i}
                  onToggle={() =>
                    setOpenRow((prev) => (prev === i ? null : i))
                  }
                />
              ))}
            </ul>
          )}
          {q.data && q.data.total_rows > q.data.items.length && (
            <div className="px-3 py-2 text-[11px] text-slate-500 bg-slate-50 border-t border-slate-100">
              Showing newest {q.data.items.length} of {q.data.total_rows} rows.
              Use the Download button for the full file.
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function RowItem({
  row,
  open,
  onToggle,
}: {
  row: Record<string, unknown>;
  open: boolean;
  onToggle: () => void;
}) {
  const decision = String(row.decision ?? "");
  const ts = String(row.timestamp ?? "");
  const arc = String(row.arc_number ?? "");
  const summary = oneLineSummary(row);
  const json = JSON.stringify(row, null, 2);

  return (
    <li>
      <button
        onClick={onToggle}
        className="w-full text-left px-3 py-2 hover:bg-slate-50 flex items-center gap-2"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        )}
        {decision && (
          <span
            className={clsx(
              "pill ring-1 text-[10px] shrink-0",
              decision === "approved"
                ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                : decision === "rejected"
                  ? "bg-rose-50 text-rose-700 ring-rose-200"
                  : "bg-slate-100 text-slate-600 ring-slate-200",
            )}
          >
            {decision}
          </span>
        )}
        {arc && (
          <span className="font-mono text-[11px] text-slate-500 shrink-0">
            {arc}
          </span>
        )}
        <span className="text-xs text-slate-700 truncate flex-1 italic">
          {summary}
        </span>
        {ts && (
          <span className="text-[11px] text-slate-400 font-mono shrink-0">
            {new Date(ts).toLocaleString()}
          </span>
        )}
      </button>
      {open && (
        <pre className="bg-slate-900 text-slate-100 text-[11px] leading-snug font-mono p-3 mx-3 mb-3 rounded-md overflow-x-auto whitespace-pre">
          {json}
        </pre>
      )}
    </li>
  );
}


function oneLineSummary(row: Record<string, unknown>): string {
  if (typeof row.message === "string" && row.message) return row.message;
  if (typeof row.comment === "string" && row.comment) return row.comment;
  if (row._snapshot_omitted) {
    const s = row._snapshot_omitted as { components?: number; connections?: number };
    return `snapshot: ${s.components ?? 0} components · ${s.connections ?? 0} connections`;
  }
  const name = row.decided_by_name || row.kind || row.finding_id;
  return name ? String(name) : "—";
}


function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
