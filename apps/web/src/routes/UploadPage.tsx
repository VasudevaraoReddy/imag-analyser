import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Loader2, Rocket, UserRound } from "lucide-react";
import { DiagramUploader } from "../components/DiagramUploader";
import { uploadDiagram } from "../lib/api";
import { useAuth } from "../lib/auth";

const STAGES = [
  "Uploading file",
  "Preprocessing image",
  "Document Intelligence OCR",
  "Vision LLM extraction",
  "Normalize · classify · compliance",
];

export default function UploadPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [stage, setStage] = useState<number>(-1);

  const mutation = useMutation({
    mutationFn: async (payload: { file: File; title: string; description: string }) => {
      setStage(0);
      const interval = setInterval(() => {
        setStage((s) => (s < STAGES.length - 1 ? s + 1 : s));
      }, 700);
      try {
        return await uploadDiagram(payload.file, {
          title: payload.title,
          description: payload.description,
          submitted_by_employee_id: user?.employee_id ?? "",
          submitted_by_name: user?.name ?? "",
          submitted_by_role: user?.role ?? "",
          submitted_by_email: user?.email ?? "",
        });
      } finally {
        clearInterval(interval);
      }
    },
    onSuccess: (result) => navigate(`/results/${result.diagram_id}`),
  });

  const handleFile = (f: File) => {
    setFile(f);
    setPreviewUrl(URL.createObjectURL(f));
  };

  const canSubmit = title.trim().length > 0 && file !== null && !mutation.isPending;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !file) return;
    mutation.mutate({ file, title: title.trim(), description: description.trim() });
  };

  return (
    <div className="max-w-3xl mx-auto p-8 space-y-6">
      
      <form onSubmit={handleSubmit} className="card p-5 space-y-5">
        {user && (
          <div className="flex items-center gap-2.5 bg-brand-50 ring-1 ring-brand-100 rounded-md px-3 py-2 text-sm">
            <div className="w-7 h-7 rounded-full bg-white ring-1 ring-brand-200 flex items-center justify-center">
              <UserRound className="w-4 h-4 text-brand" />
            </div>
            <div className="leading-tight">
              <div className="text-[10px] uppercase tracking-wider text-brand-700 font-semibold">
                Submitted by
              </div>
              <div className="text-slate-800">
                <span className="font-medium">{user.name || user.employee_id}</span>
                <span className="text-slate-500 text-xs ml-2">
                  {user.employee_id}{user.role ? ` · ${user.role}` : ""}
                </span>
              </div>
            </div>
          </div>
        )}
        <div>
          <label className="block text-sm font-medium text-slate-800">
            Title <span className="text-rose-500">*</span>
          </label>
          <input
            type="text"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. eBranch Demo VNet — Prod"
            className="mt-1 w-full text-sm rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
            disabled={mutation.isPending}
          />
          <p className="text-xs text-slate-500 mt-1">
            A short, recognizable name. Required.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-800">
            Description <span className="text-slate-400 font-normal">(optional)</span>
          </label>
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Purpose of the review, scope, stakeholders, change context, …"
            className="mt-1 w-full text-sm rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
            disabled={mutation.isPending}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-800 mb-2">
            Architecture diagram <span className="text-rose-500">*</span>
          </label>
          <DiagramUploader onFile={handleFile} disabled={mutation.isPending} />
          {previewUrl && file && (
            <div className="mt-3 border border-slate-200 rounded-md p-3 bg-slate-50">
              <div className="text-xs text-slate-500 mb-2">{file.name}</div>
              {/\.pdf$|\.drawio$/i.test(file.name) ? (
                <div className="text-sm text-slate-500">No inline preview for this format.</div>
              ) : (
                <img src={previewUrl} alt={file.name} className="max-h-48 mx-auto rounded" />
              )}
            </div>
          )}
        </div>
         
          <button
            type="submit"
            disabled={!canSubmit}
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Running…</>
            ) : (
              <><Rocket className="w-4 h-4" /> Start Architecture Review</>
            )}
          </button>
      </form>

      {mutation.isPending && (
        <div className="card p-5">
          <div className="flex items-center gap-2 font-medium text-sm text-slate-700 mb-3">
            <Loader2 className="w-4 h-4 animate-spin text-brand" /> Processing analysis…
          </div>
          <ol className="text-sm space-y-2">
            {STAGES.map((s, i) => (
              <li key={s} className="flex items-center gap-2">
                {i < stage ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                ) : i === stage ? (
                  <Loader2 className="w-4 h-4 animate-spin text-brand" />
                ) : (
                  <span className="w-4 h-4 rounded-full border border-slate-300" />
                )}
                <span className={i <= stage ? "text-slate-800" : "text-slate-400"}>{s}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {mutation.isError && <ErrorPanel error={mutation.error as Error} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error panel — special-cases 422 input-validation failures with a clean,
// actionable message instead of dumping JSON. Falls back to generic message
// for any other error.
// ---------------------------------------------------------------------------

function ErrorPanel({ error }: { error: Error }) {
  // The API returns 422 with { detail: { error, reason_code, message, ... } }
  // for validation rejections. Our jsonFetch wraps it as
  // "API 422: { ... }" — parse it back.
  const parsed = tryParseValidationError(error.message);
  if (parsed) {
    return (
      <div className="bg-amber-50 border border-amber-300 text-slate-800 rounded-lg p-5 space-y-3">
        <div className="flex items-start gap-3">
          <div className="text-2xl leading-none">⚠</div>
          <div className="flex-1">
            <div className="font-semibold text-amber-900 mb-1">
              {humanTitleFor(parsed.reason_code)}
            </div>
            <p className="text-sm text-slate-700">{parsed.message}</p>
          </div>
        </div>

        {parsed.metrics && Object.keys(parsed.metrics).length > 0 && (
          <details className="mt-2 text-xs text-slate-500">
            <summary className="cursor-pointer hover:text-slate-700">
              Show technical details
            </summary>
            <pre className="mt-2 bg-white p-2 rounded font-mono text-[11px] overflow-auto">
{JSON.stringify(parsed.metrics, null, 2)}
            </pre>
          </details>
        )}

        <div className="text-xs text-slate-600 border-t border-amber-200 pt-2">
          Architecture diagrams should:
          <ul className="mt-1 list-disc list-inside space-y-0.5">
            <li>Show services/VMs/databases as boxes with arrows between them</li>
            <li>Be at least 800 pixels on the long edge</li>
            <li>Be sharp — screenshot beats phone photo of a screen</li>
          </ul>
        </div>
      </div>
    );
  }

  // Fallback for non-validation errors
  return (
    <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-lg p-4 text-sm">
      <div className="font-semibold mb-1">Analysis failed</div>
      {error.message}
    </div>
  );
}

type ValidationDetail = {
  error: string;
  reason_code: string;
  message: string;
  category?: string;
  classifier_confidence?: number;
  metrics?: Record<string, unknown>;
};

function tryParseValidationError(msg: string): ValidationDetail | null {
  // jsonFetch raises `API 422: { ... }`; pull the JSON portion.
  const m = msg.match(/^API 422:\s*(.+)$/s);
  if (!m) return null;
  try {
    const body = JSON.parse(m[1]) as { detail?: ValidationDetail };
    if (body.detail && body.detail.error === "input_validation_failed") {
      return body.detail;
    }
  } catch {
    /* fall through */
  }
  return null;
}

function humanTitleFor(code: string): string {
  switch (code) {
    case "not_an_image":
      return "This file isn't a readable image";
    case "image_too_small":
      return "Image is too small";
    case "image_too_large":
      return "Image is too large";
    case "image_too_blurred":
      return "Image is too blurred";
    case "not_an_architecture_diagram":
      return "This doesn't look like an architecture diagram";
    default:
      return "Upload rejected";
  }
}
