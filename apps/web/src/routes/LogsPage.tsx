import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { RefreshCw, Search, ShieldAlert, Download } from "lucide-react";
import { fetchLogs, type LogEntry, type LogsQuery } from "../lib/api";
import { useAuth } from "../lib/auth";

const LEVEL_PILL: Record<string, string> = {
  info: "bg-slate-100 text-slate-700",
  warning: "bg-amber-100 text-amber-700",
  error: "bg-rose-100 text-rose-700",
  debug: "bg-slate-50 text-slate-500",
};

export default function LogsPage() {
  const { user } = useAuth();

  // Belt-and-braces — backend already enforces is_admin, but we don't even
  // render the screen for non-admins so the link can't be linked to.
  if (!user?.is_admin) {
    return (
      <div className="max-w-2xl mx-auto p-12 text-center">
        <ShieldAlert className="w-12 h-12 mx-auto text-rose-500 mb-4" />
        <h1 className="text-xl font-semibold text-slate-900">Restricted area</h1>
        <p className="text-slate-600 mt-2">
          The system logs viewer is available only to platform administrators.
          Contact the platform team if you need access.
        </p>
      </div>
    );
  }

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const [date, setDate] = useState(today);
  const [employeeId, setEmployeeId] = useState("");
  const [requestId, setRequestId] = useState("");
  const [event, setEvent] = useState("");
  const [level, setLevel] = useState("");
  const [text, setText] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);

  const query: LogsQuery = {
    date,
    employee_id: employeeId.trim() || undefined,
    request_id: requestId.trim() || undefined,
    event: event.trim() || undefined,
    level: level.trim() || undefined,
    text: text.trim() || undefined,
    limit: 500,
    order: "desc",
  };

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["logs", query],
    queryFn: () => fetchLogs(query),
    refetchInterval: autoRefresh ? 5_000 : false,
  });

  const exportJsonl = () => {
    if (!data) return;
    const blob = new Blob(
      data.items.map((i) => JSON.stringify(i) + "\n"),
      { type: "application/x-ndjson" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `logs-${date}-${Date.now()}.jsonl`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-4">
      <div>
        <div className="text-xs uppercase tracking-wider text-brand font-semibold">
          Platform admin
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">System logs</h1>
        <p className="text-sm text-slate-600 mt-1">
          Every API call, OCR call, LLM call, and service step. Logs are written
          as JSON lines to <span className="font-mono text-xs">apps/api/data/logs/</span>
          and rotated daily. Each entry carries the request_id and employee_id
          that produced it.
        </p>
      </div>

      {/* Filters */}
      <div className="card p-4 grid grid-cols-1 md:grid-cols-6 gap-3">
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
            Date (UTC)
          </label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full text-sm rounded-md border border-slate-300 px-2 py-1.5"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
            Employee ID
          </label>
          <input
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
            placeholder="e.g. VRC2106734"
            className="w-full text-sm rounded-md border border-slate-300 px-2 py-1.5"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
            Request ID
          </label>
          <input
            value={requestId}
            onChange={(e) => setRequestId(e.target.value)}
            placeholder="hex"
            className="w-full text-sm rounded-md border border-slate-300 px-2 py-1.5 font-mono"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
            Event contains
          </label>
          <input
            value={event}
            onChange={(e) => setEvent(e.target.value)}
            placeholder="vision_llm"
            className="w-full text-sm rounded-md border border-slate-300 px-2 py-1.5 font-mono"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
            Level
          </label>
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            className="w-full text-sm rounded-md border border-slate-300 px-2 py-1.5"
          >
            <option value="">All</option>
            <option value="info">info</option>
            <option value="warning">warning</option>
            <option value="error">error</option>
          </select>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
            Free-text
          </label>
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2 top-2 text-slate-400" />
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="anywhere in the line"
              className="pl-7 w-full text-sm rounded-md border border-slate-300 px-2 py-1.5"
            />
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between text-sm">
        <div className="text-slate-500">
          {data ? (
            <>
              <span className="font-medium text-slate-800">{data.total}</span> entries ·
              files: <span className="font-mono text-xs">{data.files.join(", ") || "—"}</span>
            </>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-600 inline-flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="accent-brand"
            />
            Auto-refresh (5s)
          </label>
          <button
            onClick={() => refetch()}
            className="btn-secondary text-xs"
            disabled={isFetching}
          >
            <RefreshCw className={clsx("w-3.5 h-3.5", isFetching && "animate-spin")} />
            Refresh
          </button>
          <button onClick={exportJsonl} className="btn-secondary text-xs">
            <Download className="w-3.5 h-3.5" /> Export .jsonl
          </button>
        </div>
      </div>

      {/* Log table */}
      <div className="card overflow-hidden">
        <div className="max-h-[70vh] overflow-auto">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 text-slate-600 text-left text-[10px] uppercase tracking-wide sticky top-0">
              <tr>
                <th className="px-3 py-2 font-medium w-44">Timestamp (UTC)</th>
                <th className="px-3 py-2 font-medium">Level</th>
                <th className="px-3 py-2 font-medium">Event</th>
                <th className="px-3 py-2 font-medium">Employee</th>
                <th className="px-3 py-2 font-medium">Logger</th>
                <th className="px-3 py-2 font-medium">Duration</th>
                <th className="px-3 py-2 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((entry, i) => (
                <LogRow key={i} entry={entry} />
              ))}
              {data && data.items.length === 0 && (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-slate-500">
                    No log entries match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function LogRow({ entry }: { entry: LogEntry }) {
  const [open, setOpen] = useState(false);

  const ts = entry.timestamp ? String(entry.timestamp).replace("T", " ").replace("Z", "") : "";
  const level = String(entry.level || "info");
  const event = String(entry.event || "—");
  const employeeId = entry.employee_id ? String(entry.employee_id) : "";
  const employeeName = (entry as { employee_name?: string }).employee_name ?? "";
  const logger = entry.logger ? String(entry.logger) : "—";
  const duration = (entry as { duration_ms?: number }).duration_ms;

  // Pick a short detail line from common high-value fields
  const detail = [
    (entry as { path?: string }).path,
    (entry as { status?: number }).status !== undefined ? `→ ${(entry as { status?: number }).status}` : null,
    (entry as { error?: string }).error,
    (entry as { response_preview?: string }).response_preview,
    (entry as { prompt_tokens?: number }).prompt_tokens !== undefined
      ? `tokens=${(entry as { prompt_tokens?: number; completion_tokens?: number }).prompt_tokens}/${(entry as { completion_tokens?: number }).completion_tokens ?? "?"}`
      : null,
  ]
    .filter(Boolean)
    .slice(0, 3)
    .join(" · ");

  return (
    <>
      <tr
        className={clsx(
          "border-t border-slate-100 cursor-pointer hover:bg-slate-50 align-top",
          level === "error" && "bg-rose-50/40",
          level === "warning" && "bg-amber-50/40",
        )}
        onClick={() => setOpen((v) => !v)}
      >
        <td className="px-3 py-1.5 font-mono text-[11px] text-slate-600 whitespace-nowrap">
          {ts}
        </td>
        <td className="px-3 py-1.5">
          <span className={clsx("inline-block px-1.5 py-0.5 rounded uppercase tracking-wide font-semibold", LEVEL_PILL[level] ?? LEVEL_PILL.info)}>
            {level}
          </span>
        </td>
        <td className="px-3 py-1.5 font-mono text-[11px] text-slate-800">
          {event}
        </td>
        <td className="px-3 py-1.5 text-slate-700">
          {employeeId ? (
            <>
              <span className="font-mono text-[11px]">{employeeId}</span>
              {employeeName && (
                <div className="text-[10px] text-slate-500">{employeeName}</div>
              )}
            </>
          ) : (
            <span className="text-slate-300">—</span>
          )}
        </td>
        <td className="px-3 py-1.5 text-slate-600 font-mono text-[11px]">{logger}</td>
        <td className="px-3 py-1.5 text-slate-600 font-mono text-[11px] tabular-nums">
          {duration !== undefined ? `${duration} ms` : "—"}
        </td>
        <td className="px-3 py-1.5 text-slate-600 truncate max-w-md">{detail}</td>
      </tr>
      {open && (
        <tr className="border-t border-slate-100 bg-slate-900 text-slate-100">
          <td colSpan={7} className="p-3">
            <pre className="text-[11px] overflow-auto">
              {JSON.stringify(entry, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}
