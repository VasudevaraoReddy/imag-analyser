import { useCallback, useState } from "react";
import { Upload } from "lucide-react";

export const ACCEPTED = ".png,.jpg,.jpeg,.webp,.bmp,.gif,.svg,.pdf,.drawio";

export function DiagramUploader({
  onFile,
  disabled,
}: {
  onFile: (file: File) => void;
  disabled?: boolean;
}) {
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLLabelElement>) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const f = e.dataTransfer.files?.[0];
      if (f) onFile(f);
    },
    [disabled, onFile],
  );

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={[
        "flex flex-col items-center justify-center gap-3 border-2 border-dashed rounded-xl p-12 cursor-pointer transition",
        dragOver ? "border-sky-500 bg-sky-50" : "border-slate-300 bg-white",
        disabled ? "opacity-50 cursor-not-allowed" : "hover:border-sky-400",
      ].join(" ")}
    >
      <Upload className="w-8 h-8 text-slate-500" />
      <div className="text-slate-700 font-medium">
        Drop a diagram here, or click to select
      </div>
      <div className="text-xs text-slate-500">
        PNG · JPG · WEBP · BMP · GIF · SVG · PDF · .drawio (export as PNG/PDF)
      </div>
      <input
        type="file"
        accept={ACCEPTED}
        className="hidden"
        disabled={disabled}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
        }}
      />
    </label>
  );
}
