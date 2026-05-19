import { AnalysisResult, AnalysisSummary } from "@bank-arch/shared";

const BASE = "/api";

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
    throw new Error(
      `API ${res.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`,
    );
  }
  return (await res.json()) as T;
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, analysis_id: analysisId }),
    signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
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
