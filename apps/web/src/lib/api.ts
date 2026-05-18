import { AnalysisResult, AnalysisSummary } from "@bank-arch/shared";

const BASE = "/api";

async function jsonFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
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
  token: string;
};

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
