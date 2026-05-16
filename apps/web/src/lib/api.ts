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

export async function uploadDiagram(file: File): Promise<AnalysisResult> {
  const fd = new FormData();
  fd.append("file", file);
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
