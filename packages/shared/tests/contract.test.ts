import { describe, it, expect } from "vitest";
import { AnalysisResult } from "../src/schema.js";

const fixture = {
  diagram_id: "11111111-1111-1111-1111-111111111111",
  submitted_at: "2026-05-16T12:00:00Z",
  filename: "azure_3_tier_clean.png",
  input_format: "png",
  image_dimensions: { width: 1600, height: 900 },
  tiles_processed: 1,
  cloud_providers: ["azure"],
  primary_provider: "azure",
  diagram_style: "official_stencil",
  trust_zones: [
    { id: "tz-external", name: "Internet", kind: "external" },
    { id: "tz-perimeter", name: "Front Door / WAF", kind: "perimeter" },
    { id: "tz-internal", name: "App VNet", kind: "internal" },
    { id: "tz-restricted", name: "Data Subnet", kind: "restricted" },
  ],
  components: [
    {
      id: "c-user",
      name: "User",
      canonical_name: "User",
      service_type: "user_actor",
      provider: "other",
      trust_zone: "tz-external",
      tier: "edge",
      redundancy: "unknown",
      evidence: { bbox: [10, 10, 100, 60], confidence: 0.95 },
    },
    {
      id: "c-fd",
      name: "Azure Front Door",
      canonical_name: "Azure Front Door",
      service_type: "edge_waf",
      provider: "azure",
      trust_zone: "tz-perimeter",
      tier: "edge",
      redundancy: "multi_region",
      evidence: { bbox: [150, 10, 320, 60], confidence: 0.92 },
    },
  ],
  connections: [
    {
      id: "e-1",
      from: "c-user",
      to: "c-fd",
      label: "HTTPS",
      protocol: "HTTPS",
      port: 443,
      encrypted: true,
      bidirectional: false,
      is_data_flow: true,
    },
  ],
  flows: { north_south: ["e-1"], east_west: [] },
  compliance_findings: [],
  parsing_warnings: [],
  overall_confidence: 0.93,
  review_state: "auto_review_recommended",
  processing_ms: {
    image_prep: 12,
    doc_intelligence: 100,
    vision_llm: 800,
    post_process: 5,
    total: 917,
  },
};

describe("AnalysisResult schema", () => {
  it("round-trips a fixture", () => {
    const parsed = AnalysisResult.parse(fixture);
    const serialized = JSON.parse(JSON.stringify(parsed));
    const reparsed = AnalysisResult.parse(serialized);
    expect(reparsed).toEqual(parsed);
  });

  it("rejects an invalid review_state", () => {
    expect(() =>
      AnalysisResult.parse({ ...fixture, review_state: "bogus" }),
    ).toThrow();
  });

  it("rejects a confidence outside [0,1]", () => {
    expect(() =>
      AnalysisResult.parse({ ...fixture, overall_confidence: 1.5 }),
    ).toThrow();
  });
});
