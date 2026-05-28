import { AnalysisResult, AnalysisSummary } from "@bank-arch/shared";
import { clearAuth, markSessionExpired } from "./auth";

// Backend URL — baked at build time from VITE_API_BASE env var.
// In Azure: workflow sets VITE_API_BASE to the BE App Service hostname.
// Local dev: env var is empty, falls back to "/api" which Vite proxies to localhost:8000.
//
// The `as any` cast keeps the build green even on TS configs that lack
// Vite's client types — Vite still substitutes the value at build time.
const BASE: string =
  (import.meta as any).env?.VITE_API_BASE || "/api";

// Read the cached auth user (set by routes/LoginPage on sign-in) and
// attach `Authorization: Bearer <token>` to every request. Keeping this
// inside api.ts avoids importing React (auth.ts has a hook).
function authHeader(): Record<string, string> {
  try {
    const raw = localStorage.getItem("bank-arch.auth.user");
    if (!raw) return {};
    const u = JSON.parse(raw) as { token?: string };
    return u.token ? { Authorization: `Bearer ${u.token}` } : {};
  } catch {
    return {};
  }
}

/** True for endpoints where a 401 means "bad credentials", NOT "session
 *  expired" — we should NOT force-logout on these. */
function isLoginRequest(input: RequestInfo): boolean {
  const url = typeof input === "string" ? input : (input as Request).url;
  return /\/auth\/login(\?|$)/.test(url);
}

async function jsonFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...(authHeader()),
    ...((init?.headers as Record<string, string>) || {}),
  };
  const res = await fetch(input, { ...init, headers });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text();
    }
    // ─── Force-logout on 401 from any non-login endpoint ──────────────
    if (res.status === 401 && !isLoginRequest(input)) {
      const reason = readAuthFailureReason(detail);
      if (reason === "session_expired") {
        markSessionExpired();
      } else {
        // Token revoked / never valid / server restart. Treat as logout
        // too — there's nothing the user can do but sign in again.
        clearAuth();
      }
    }
    throw new Error(
      `API ${res.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`,
    );
  }
  return (await res.json()) as T;
}

/** Pull the structured ``error`` discriminator out of a 401 response body.
 *  Server shape: ``{ detail: { error: "session_expired" | "not_authenticated", message: "…" } }``
 *  or (legacy) ``{ detail: "Not authenticated" }``. */
function readAuthFailureReason(
  detail: unknown,
): "session_expired" | "not_authenticated" | "unknown" {
  if (detail && typeof detail === "object" && "detail" in detail) {
    const inner = (detail as { detail: unknown }).detail;
    if (inner && typeof inner === "object" && "error" in inner) {
      const e = (inner as { error: unknown }).error;
      if (e === "session_expired") return "session_expired";
      if (e === "not_authenticated") return "not_authenticated";
    }
  }
  return "unknown";
}

export async function uploadDiagram(
  file: File,
  fields: {
    title: string;
    description?: string;
    submitted_by_employee_id?: string;
    submitted_by_name?: string;
    submitted_by_role?: string;
    submitted_by_email?: string;
  },
): Promise<AnalysisResult> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("title", fields.title);
  fd.append("description", fields.description ?? "");
  fd.append("submitted_by_employee_id", fields.submitted_by_employee_id ?? "");
  fd.append("submitted_by_name", fields.submitted_by_name ?? "");
  fd.append("submitted_by_role", fields.submitted_by_role ?? "");
  fd.append("submitted_by_email", fields.submitted_by_email ?? "");
  return jsonFetch<AnalysisResult>(`${BASE}/analyze`, {
    method: "POST",
    body: fd,
  });
}

export async function listAnalyses(): Promise<AnalysisSummary[]> {
  return jsonFetch<AnalysisSummary[]>(`${BASE}/analyses`);
}

export async function getAnalysis(id: string): Promise<AnalysisResult> {
  return jsonFetch<AnalysisResult>(`${BASE}/analyses/${id}`);
}

export function imageUrl(id: string): string {
  return `${BASE}/analyses/${id}/image`;
}

export function processedImageUrl(id: string): string {
  return `${BASE}/analyses/${id}/image/processed`;
}

export type ChatMessage = { role: "user" | "assistant" | "system"; content: string };

export type LoginResponse = {
  employee_id: string;
  name: string;
  role: string;
  email: string;
  is_admin: boolean;
  token: string;
};

// ---------------------------------------------------------------------------
// Admin: logs viewer
// ---------------------------------------------------------------------------

export type LogEntry = Record<string, unknown> & {
  timestamp?: string;
  level?: string;
  event?: string;
  request_id?: string;
  employee_id?: string;
  logger?: string;
};

export type LogsQuery = {
  date?: string;
  employee_id?: string;
  request_id?: string;
  event?: string;
  level?: string;
  text?: string;
  limit?: number;
  offset?: number;
  order?: "asc" | "desc";
};

export type LogsResponse = {
  date: string;
  files: string[];
  total: number;
  items: LogEntry[];
  limit: number;
  offset: number;
  order: "asc" | "desc";
};

export async function fetchLogs(q: LogsQuery = {}): Promise<LogsResponse> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v !== undefined && v !== "" && v !== null) {
      params.set(k, String(v));
    }
  }
  return jsonFetch<LogsResponse>(`${BASE}/admin/logs?${params.toString()}`);
}

export async function listLogFiles(): Promise<{ files: { name: string; size_bytes: number; modified_at: string }[] }> {
  return jsonFetch(`${BASE}/admin/logs/files`);
}

// ---------------------------------------------------------------------------
// Admin: usage / token dashboard
// ---------------------------------------------------------------------------

export type UsageSummary = {
  window_days: number;
  totals: {
    calls: number;
    tokens: number;
    prompt_tokens: number;
    completion_tokens: number;
    cost_usd: number;
    errors: number;
    avg_duration_ms: number;
  };
  today: { calls: number; tokens: number; cost_usd: number };
  by_kind: { kind: string; calls: number; tokens: number }[];
  by_model: { model: string; tokens: number }[];
  by_employee: {
    employee_id: string;
    employee_name: string;
    calls: number;
    tokens: number;
    cost_usd: number;
  }[];
  by_status: { status: string; calls: number }[];
  current_model: {
    deployment: string;
    model: string | null;
    system_fingerprint: string | null;
  };
};

export type UsageEvent = {
  timestamp: string;
  kind: string;
  deployment: string;
  model: string | null;
  system_fingerprint: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  duration_ms: number;
  status: string;
  error_type: string | null;
  request_id: string | null;
  employee_id: string | null;
  employee_name: string | null;
  analysis_id: string | null;
  cost_usd: number;
};

export async function fetchUsageSummary(days = 30): Promise<UsageSummary> {
  return jsonFetch<UsageSummary>(`${BASE}/admin/usage/summary?days=${days}`);
}

export async function fetchUsageRecent(limit = 100): Promise<{ items: UsageEvent[] }> {
  return jsonFetch(`${BASE}/admin/usage/recent?limit=${limit}`);
}

export async function login(
  employee_id: string,
  password: string,
): Promise<LoginResponse> {
  return jsonFetch<LoginResponse>(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ employee_id, password }),
  });
}

// ---------------------------------------------------------------------------
// AI Self-Review — architect decisions on critic findings (Sprint 3)
// ---------------------------------------------------------------------------

export async function submitCriticDecision(
  diagramId: string,
  findingId: string,
  decision: "approved" | "rejected",
): Promise<AnalysisResult> {
  return jsonFetch<AnalysisResult>(`${BASE}/analyses/${diagramId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ finding_id: findingId, decision }),
  });
}

/** Architect-driven re-extraction. Long-running (~30–90s in prod) —
 *  the response carries the staged candidate which the architect
 *  then accepts or discards. */
export async function requestReReview(
  diagramId: string,
  feedback: string,
): Promise<AnalysisResult> {
  return jsonFetch<AnalysisResult>(`${BASE}/analyses/${diagramId}/re-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
}

export async function acceptReReviewCandidate(
  diagramId: string,
): Promise<AnalysisResult> {
  return jsonFetch<AnalysisResult>(
    `${BASE}/analyses/${diagramId}/re-review/accept`,
    { method: "POST" },
  );
}

export async function discardReReviewCandidate(
  diagramId: string,
): Promise<AnalysisResult> {
  return jsonFetch<AnalysisResult>(
    `${BASE}/analyses/${diagramId}/re-review/discard`,
    { method: "POST" },
  );
}

/** Architect's overall Approve / Reject verdict on the whole review.
 *  Persists on the analysis JSON and writes a full training-snapshot
 *  row to data/feedback/reviews-YYYY-MM.jsonl on the server. */
export async function submitReviewDecision(
  diagramId: string,
  decision: "approved" | "rejected",
  comment: string,
): Promise<AnalysisResult> {
  return jsonFetch<AnalysisResult>(
    `${BASE}/analyses/${diagramId}/review-decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, comment }),
    },
  );
}

export async function sendChat(
  messages: ChatMessage[],
  analysisId: string | null,
): Promise<{ reply: string; analysis_id: string | null }> {
  return jsonFetch<{ reply: string; analysis_id: string | null }>(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, analysis_id: analysisId }),
  });
}

/**
 * Stream a chat response token-by-token via SSE.
 *
 * Calls `onDelta(text)` for each incoming chunk and resolves when the stream
 * ends. Pass an AbortSignal to cancel mid-stream.
 */
export async function streamChat(
  messages: ChatMessage[],
  analysisId: string | null,
  onDelta: (delta: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ messages, analysis_id: analysisId }),
    signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    if (res.status === 401) {
      // Same force-logout policy as jsonFetch.
      let parsed: unknown = text;
      try { parsed = JSON.parse(text); } catch { /* keep raw */ }
      if (readAuthFailureReason(parsed) === "session_expired") {
        markSessionExpired();
      } else {
        clearAuth();
      }
    }
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE events are delimited by a blank line (\n\n).
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const event = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);

      // An event may have multiple "field: value" lines; we only use `data:`.
      for (const line of event.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (data === "[DONE]") return;
        try {
          const parsed = JSON.parse(data) as { delta?: string; error?: string };
          if (parsed.error) throw new Error(parsed.error);
          if (parsed.delta) onDelta(parsed.delta);
        } catch (e) {
          if ((e as Error).message?.startsWith("[stream") ||
              (e as Error).name === "SyntaxError") {
            // Ignore malformed lines; SSE keep-alives etc.
            continue;
          }
          throw e;
        }
      }
    }
  }
}


// ---------------------------------------------------------------------------
// Admin · Training-data dashboard
// ---------------------------------------------------------------------------

export type TrainingDataSummary = {
  totals: {
    analyses: number;
    reviews_approved: number;
    reviews_rejected: number;
    reviews_pending: number;
    critic_findings_total: number;
    critic_findings_auto_applied: number;
    critic_findings_architect_approved: number;
    critic_findings_architect_rejected: number;
    re_review_rounds: number;
    re_review_accepted: number;
    re_review_discarded: number;
  };
  ledgers: {
    per_finding: { files: LedgerFile[]; total_bytes: number; total_rows: number };
    whole_review: { files: LedgerFile[]; total_bytes: number; total_rows: number };
  };
  capture_schema: {
    per_finding_event: string[];
    whole_review_event: string[];
  };
  data_dir: string;
};

export type LedgerFile = {
  name: string;
  size_bytes: number;
  rows: number;
  modified_at: string;
};

export type ApprovedReviewRow = {
  diagram_id: string;
  arc_number: string;
  title: string;
  filename: string;
  components: number;
  connections: number;
  journeys: number;
  primary_provider: string;
  confidence: number;
  review_state: string;
  submitted_at: string;
  decision: {
    status: "approved" | "rejected";
    decided_at: string | null;
    decided_by_employee_id: string;
    decided_by_name: string;
    decided_by_role: string;
    comment: string;
  };
  re_review_rounds: number;
};

export type TrainingEvent = {
  type: "finding_decision" | "review_decision";
  timestamp: string;
  diagram_id: string;
  arc_number?: string;
  decision: string;
  // finding_decision fields
  finding_id?: string;
  kind?: string;
  confidence?: number;
  message?: string;
  // review_decision fields
  comment?: string;
  decided_by_employee_id?: string;
  decided_by_name?: string;
  decided_by_role?: string;
  snapshot_components?: number;
  snapshot_connections?: number;
};

export async function getTrainingDataSummary(): Promise<TrainingDataSummary> {
  return jsonFetch<TrainingDataSummary>(
    `${BASE}/admin/training-data/summary`,
  );
}

export async function listApprovedReviews(
  decision: "approved" | "rejected" | "all" = "approved",
): Promise<{ items: ApprovedReviewRow[]; total: number }> {
  return jsonFetch(
    `${BASE}/admin/training-data/approved-reviews?decision=${decision}`,
  );
}

export async function listRecentTrainingEvents(
  limit = 50,
): Promise<{ items: TrainingEvent[]; total: number }> {
  return jsonFetch(
    `${BASE}/admin/training-data/recent-events?limit=${limit}`,
  );
}


// ---------------------------------------------------------------------------
// Admin · Raw ledger viewer
// ---------------------------------------------------------------------------

export type LedgerRowsResponse = {
  name: string;
  size_bytes: number;
  total_rows: number;
  items: Record<string, unknown>[];
  limit: number;
  offset: number;
  order: "asc" | "desc";
  include_snapshot: boolean;
};

export async function getLedgerRows(
  name: string,
  opts: { limit?: number; offset?: number; includeSnapshot?: boolean } = {},
): Promise<LedgerRowsResponse> {
  const qs = new URLSearchParams();
  qs.set("limit", String(opts.limit ?? 50));
  qs.set("offset", String(opts.offset ?? 0));
  qs.set("include_snapshot", String(opts.includeSnapshot ?? false));
  return jsonFetch<LedgerRowsResponse>(
    `${BASE}/admin/training-data/ledger/${name}?${qs.toString()}`,
  );
}

/** Returns the absolute URL for the raw .jsonl download. The browser
 *  will follow this with the same Bearer token via a normal anchor +
 *  fetch dance. We use authedDownloadUrl below so the token is sent. */
export function ledgerDownloadUrl(name: string): string {
  return `${BASE}/admin/training-data/ledger/${name}/download`;
}

/** Trigger an auth'd file download from the browser. Anchor downloads
 *  can't carry an Authorization header, so we fetch the file as a Blob
 *  and synthesise a download link. */
export async function downloadLedger(name: string): Promise<void> {
  const res = await fetch(ledgerDownloadUrl(name), { headers: authHeader() });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}


// ---------------------------------------------------------------------------
// Admin · Delete review (hard-delete an analysis + every artifact)
// ---------------------------------------------------------------------------

export type DeleteReviewResponse = {
  diagram_id: string;
  arc_number?: string;
  artifacts: Record<string, boolean>;
  ledger_rows_purged: { per_finding: number; whole_review: number };
};

export async function deleteAnalysis(diagramId: string): Promise<DeleteReviewResponse> {
  return jsonFetch<DeleteReviewResponse>(`${BASE}/analyses/${diagramId}`, {
    method: "DELETE",
  });
}
