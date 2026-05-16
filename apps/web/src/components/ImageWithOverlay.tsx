import { useEffect, useRef, useState } from "react";
import type { AnalysisResult } from "../types";

type Props = {
  result: AnalysisResult;
  imageUrl: string;
  variant?: "original" | "processed";
  highlightedComponentId?: string | null;
  onSelectComponent?: (id: string) => void;
  showOverlay?: boolean;
};

const ZONE_COLORS: Record<string, string> = {
  external: "#ef4444",
  perimeter: "#f59e0b",
  dmz: "#eab308",
  internal: "#22c55e",
  restricted: "#3b82f6",
  management: "#a855f7",
};

export function ImageWithOverlay({
  result,
  imageUrl,
  variant = "processed",
  highlightedComponentId,
  onSelectComponent,
  showOverlay = true,
}: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);

  // Re-measure whenever URL changes or the window resizes
  useEffect(() => {
    const update = () => {
      const img = imgRef.current;
      if (!img || img.naturalWidth === 0) return;
      setDims({ w: img.clientWidth, h: img.clientHeight });
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [imageUrl, result.diagram_id]);

  const scale = dims
    ? {
        x: dims.w / result.image_dimensions.width,
        y: dims.h / result.image_dimensions.height,
      }
    : null;

  const componentZoneKind = (compId: string): string => {
    const c = result.components.find((c) => c.id === compId);
    if (!c) return "internal";
    return result.trust_zones.find((z) => z.id === c.trust_zone)?.kind ?? "internal";
  };

  const componentCenter = (compId: string): [number, number] | null => {
    const c = result.components.find((c) => c.id === compId);
    if (!c || !scale) return null;
    const [x1, y1, x2, y2] = c.evidence.bbox;
    return [((x1 + x2) / 2) * scale.x, ((y1 + y2) / 2) * scale.y];
  };

  const nsIds = new Set(result.flows.north_south);
  const ewIds = new Set(result.flows.east_west);

  // Cache-bust the URL so the toggle is always a fresh fetch (some browsers
  // hold the same <img> element if only one byte differs).
  const src = imageUrl.includes("?") ? imageUrl : `${imageUrl}?v=${variant}`;

  return (
    <div className="flex justify-center">
      <div className="relative inline-block max-w-full">
      <img
        key={src}
        ref={imgRef}
        src={src}
        alt={result.filename}
        className="block max-h-[60vh] max-w-full w-auto h-auto rounded-md border border-slate-200"
        onLoad={() => {
          const img = imgRef.current;
          if (img && img.naturalWidth) {
            setDims({ w: img.clientWidth, h: img.clientHeight });
          }
        }}
      />
      <div className="absolute top-2 left-2 pill bg-slate-900/75 text-white backdrop-blur-sm">
        {variant === "original" ? "Original" : "Processed"} ·{" "}
        {result.image_dimensions.width}×{result.image_dimensions.height}
      </div>
      {showOverlay && scale && dims && (
        <svg
          className="absolute inset-0"
          width={dims.w}
          height={dims.h}
          viewBox={`0 0 ${dims.w} ${dims.h}`}
          style={{ pointerEvents: "none" }}
        >
          <defs>
            <marker id="arrow-ns" viewBox="0 0 10 10" refX="9" refY="5"
                    markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#f97316" />
            </marker>
            <marker id="arrow-ew" viewBox="0 0 10 10" refX="9" refY="5"
                    markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#0ea5e9" />
            </marker>
          </defs>
          {result.components.map((c) => {
            const [x1, y1, x2, y2] = c.evidence.bbox;
            const color = ZONE_COLORS[componentZoneKind(c.id)] ?? "#22c55e";
            const isHi = c.id === highlightedComponentId;
            return (
              <g key={c.id} style={{ pointerEvents: "auto" }}>
                <rect
                  x={x1 * scale.x}
                  y={y1 * scale.y}
                  width={(x2 - x1) * scale.x}
                  height={(y2 - y1) * scale.y}
                  fill={isHi ? `${color}22` : "transparent"}
                  stroke={color}
                  strokeWidth={isHi ? 3 : 1.5}
                  opacity={isHi ? 1 : 0.85}
                  className="cursor-pointer"
                  onClick={() => onSelectComponent?.(c.id)}
                />
              </g>
            );
          })}
          {result.connections.map((e) => {
            const from = componentCenter(e.from);
            const to = componentCenter(e.to);
            if (!from || !to) return null;
            const isNs = nsIds.has(e.id);
            const isEw = ewIds.has(e.id);
            const color = isNs ? "#f97316" : isEw ? "#0ea5e9" : "#94a3b8";
            return (
              <line
                key={e.id}
                x1={from[0]}
                y1={from[1]}
                x2={to[0]}
                y2={to[1]}
                stroke={color}
                strokeWidth={1.5}
                strokeDasharray={e.is_data_flow ? "0" : "4 4"}
                markerEnd={isNs ? "url(#arrow-ns)" : isEw ? "url(#arrow-ew)" : undefined}
                opacity={0.8}
              />
            );
          })}
        </svg>
      )}
      </div>
    </div>
  );
}
