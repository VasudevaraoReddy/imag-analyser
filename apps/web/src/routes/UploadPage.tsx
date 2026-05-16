import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Loader2 } from "lucide-react";
import { DiagramUploader } from "../components/DiagramUploader";
import { uploadDiagram } from "../lib/api";

const STAGES = [
  "Uploading file",
  "Preprocessing image",
  "Document Intelligence OCR",
  "Vision LLM extraction",
  "Normalize · classify · compliance",
];

export default function UploadPage() {
  const navigate = useNavigate();
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [filename, setFilename] = useState<string>("");
  const [stage, setStage] = useState<number>(-1);

  const mutation = useMutation({
    mutationFn: async (file: File) => {
      setStage(0);
      const interval = setInterval(() => {
        setStage((s) => (s < STAGES.length - 1 ? s + 1 : s));
      }, 700);
      try {
        return await uploadDiagram(file);
      } finally {
        clearInterval(interval);
      }
    },
    onSuccess: (result) => navigate(`/results/${result.diagram_id}`),
  });

  const handleFile = (file: File) => {
    setFilename(file.name);
    setPreviewUrl(URL.createObjectURL(file));
    mutation.mutate(file);
  };

  return (
    <div className="max-w-3xl mx-auto p-8 space-y-6">
      <div>
        <div className="text-xs uppercase tracking-wider text-brand font-semibold">
          New analysis
        </div>
        <h1 className="text-2xl font-semibold tracking-tight mt-1">
          Analyze an architecture diagram
        </h1>
        <p className="text-slate-600 text-sm mt-1">
          Drop a cloud architecture diagram. The analyzer will extract components,
          classify north-south and east-west flows, and run compliance checks
          against the bank's reference controls.
        </p>
      </div>

      <DiagramUploader onFile={handleFile} disabled={mutation.isPending} />

      {previewUrl && (
        <div className="card p-4">
          <div className="text-xs text-slate-500 mb-2">{filename}</div>
          {/\.pdf$|\.drawio$/i.test(filename) ? (
            <div className="text-sm text-slate-500">No inline preview for this format.</div>
          ) : (
            <img src={previewUrl} alt={filename} className="max-h-64 mx-auto rounded" />
          )}
        </div>
      )}

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

      {mutation.isError && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-lg p-4 text-sm">
          <div className="font-semibold mb-1">Analysis failed</div>
          {(mutation.error as Error).message}
        </div>
      )}
    </div>
  );
}
