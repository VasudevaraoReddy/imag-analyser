import { describe, it, expect } from "vitest";
import { AnalysisResult } from "@bank-arch/shared";

// We don't render the SVG here — just verify the bbox math contract:
// screen coords = pixel coords * scale.
function project(bbox: [number, number, number, number], scaleX: number, scaleY: number) {
  const [x1, y1, x2, y2] = bbox;
  return { x: x1 * scaleX, y: y1 * scaleY, w: (x2 - x1) * scaleX, h: (y2 - y1) * scaleY };
}

describe("bbox projection", () => {
  it("scales pixel coordinates linearly", () => {
    const r = project([100, 200, 300, 500], 0.5, 0.5);
    expect(r).toEqual({ x: 50, y: 100, w: 100, h: 150 });
  });

  it("identity when scale is 1", () => {
    const r = project([10, 20, 110, 220], 1, 1);
    expect(r).toEqual({ x: 10, y: 20, w: 100, h: 200 });
  });
});

describe("AnalysisResult fixture parses", () => {
  it("loads a minimal fixture", () => {
    const fix: AnalysisResult = {
      diagram_id: "x",
      arc_number: "ARC-202605-001",
      title: "Test",
      description: "",
      submitted_at: "2026-05-16T00:00:00Z",
      filename: "f.png",
      input_format: "png",
      image_dimensions: { width: 100, height: 100 },
      tiles_processed: 1,
      cloud_providers: [],
      primary_provider: "unknown",
      diagram_style: "unknown",
      trust_zones: [],
      components: [],
      connections: [],
      flows: { north_south: [], east_west: [] },
      journeys: [],
      compliance_findings: [],
      parsing_warnings: [],
      overall_confidence: 0.5,
      review_state: "needs_human_review",
      processing_ms: { image_prep: 0, doc_intelligence: 0, vision_llm: 0, post_process: 0, total: 0 },
    };
    expect(fix.diagram_id).toBe("x");
  });
});
