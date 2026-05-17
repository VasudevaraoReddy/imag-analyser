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
  fields: { title: string; description?: string },
): Promise<AnalysisResult> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("title", fields.title);
  fd.append("description", fields.description ?? "");
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
