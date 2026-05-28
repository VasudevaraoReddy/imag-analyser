import { z } from "zod";

export const BBox = z.tuple([z.number(), z.number(), z.number(), z.number()]);
export type BBox = z.infer<typeof BBox>;

export const Provider = z.enum([
  "azure",
  "aws",
  "gcp",
  "oci",
  "on_prem",
  "kubernetes",
  "other",
]);
export type Provider = z.infer<typeof Provider>;

export const PrimaryProvider = z.enum([
  "azure",
  "aws",
  "gcp",
  "oci",
  "multi",
  "on_prem",
  "unknown",
]);
export type PrimaryProvider = z.infer<typeof PrimaryProvider>;

export const InputFormat = z.enum([
  "png",
  "jpg",
  "svg",
  "pdf",
  "drawio",
  "visio",
  "unknown",
]);
export type InputFormat = z.infer<typeof InputFormat>;

export const DiagramStyle = z.enum([
  "official_stencil",
  "hand_drawn",
  "whiteboard",
  "mixed",
  "unknown",
]);
export type DiagramStyle = z.infer<typeof DiagramStyle>;

export const TrustZoneKind = z.enum([
  "external",
  "perimeter",
  "dmz",
  "internal",
  "restricted",
  "management",
]);
export type TrustZoneKind = z.infer<typeof TrustZoneKind>;

export const ServiceType = z.enum([
  "edge_waf",
  "cdn",
  "api_gateway",
  "load_balancer",
  "dns",
  "compute_vm",
  "compute_serverless",
  "compute_container",
  "compute_k8s",
  "storage_object",
  "storage_file",
  "storage_block",
  "database_relational",
  "database_nosql",
  "database_cache",
  "database_warehouse",
  "messaging_queue",
  "messaging_pubsub",
  "messaging_event_stream",
  "identity",
  "secrets_vault",
  "key_management",
  "monitoring",
  "logging",
  "siem",
  "networking_vnet",
  "networking_subnet",
  "networking_firewall",
  "networking_private_endpoint",
  "networking_peering",
  "networking_vpn",
  "networking_express_route",
  "networking_nat",
  "ai_ml",
  "search",
  "integration_service",
  "workflow_orchestrator",
  "backup",
  "dr",
  "mainframe",
  "on_prem_app",
  "third_party_saas",
  "user_actor",
  "unknown",
]);
export type ServiceType = z.infer<typeof ServiceType>;

export const Tier = z.enum([
  "edge",
  "web",
  "app",
  "data",
  "integration",
  "management",
  "unknown",
]);
export type Tier = z.infer<typeof Tier>;

export const Redundancy = z.enum([
  "single",
  "multi_az",
  "multi_region",
  "unknown",
]);
export type Redundancy = z.infer<typeof Redundancy>;

export const TrustZone = z.object({
  id: z.string(),
  name: z.string(),
  kind: TrustZoneKind,
  bbox: BBox.optional(),
  evidence: z.string().optional(),
});
export type TrustZone = z.infer<typeof TrustZone>;

export const ComponentEvidence = z.object({
  ocr_text: z.string().optional(),
  bbox: BBox,
  icon_hint: z.string().optional(),
  confidence: z.number().min(0).max(1),
});
export type ComponentEvidence = z.infer<typeof ComponentEvidence>;

export const Component = z.object({
  id: z.string(),
  name: z.string(),
  canonical_name: z.string(),
  service_type: ServiceType,
  provider: Provider,
  trust_zone: z.string(),
  tier: Tier,
  redundancy: Redundancy,
  evidence: ComponentEvidence,
});
export type Component = z.infer<typeof Component>;

export const Connection = z.object({
  id: z.string(),
  from: z.string(),
  to: z.string(),
  label: z.string().optional().nullable(),
  protocol: z.string().optional().nullable(),
  port: z.number().optional().nullable(),
  encrypted: z.boolean().optional().nullable(),
  bidirectional: z.boolean(),
  is_data_flow: z.boolean(),
  evidence: z.string().optional().nullable(),
});
export type Connection = z.infer<typeof Connection>;

export const Flows = z.object({
  north_south: z.array(z.string()),
  east_west: z.array(z.string()),
});
export type Flows = z.infer<typeof Flows>;

export const JourneyKind = z.enum([
  "auth", "read", "write", "admin", "integration", "generic",
]);
export type JourneyKind = z.infer<typeof JourneyKind>;

export const JourneyHop = z.object({
  from: z.string(),
  to: z.string(),
  from_name: z.string().default(""),
  to_name: z.string().default(""),
  label: z.string().nullable().optional(),
  protocol: z.string().nullable().optional(),
  port: z.number().nullable().optional(),
  encrypted: z.boolean().nullable().optional(),
  from_zone_kind: z.string().default(""),
  to_zone_kind: z.string().default(""),
  connection_id: z.string().nullable().optional(),
  direction_inferred: z.boolean().default(false),
});
export type JourneyHop = z.infer<typeof JourneyHop>;

export const Journey = z.object({
  id: z.string(),
  title: z.string(),
  kind: JourneyKind.default("generic"),
  hops: z.array(JourneyHop).default([]),
  component_ids: z.array(z.string()).default([]),
  connection_ids: z.array(z.string()).default([]),
  zones_crossed: z.array(z.string()).default([]),
  protocols: z.array(z.string()).default([]),
  is_fully_encrypted: z.boolean().nullable().optional(),
  has_unencrypted_hop: z.boolean().default(false),
  enters_restricted: z.boolean().default(false),
  starts_external: z.boolean().default(false),
  related_findings: z.array(z.string()).default([]),
  score: z.number().int().default(0),
  narrative: z.string().default(""),
  warnings: z.array(z.string()).default([]),
});
export type Journey = z.infer<typeof Journey>;

// ---------------------------------------------------------------------------
// AI Self-Critique — Sprint 2b
// ---------------------------------------------------------------------------

export const CriticFindingKind = z.enum([
  "missed_component",
  "spurious_component",
  "wrong_label",
  "wrong_service_type",
  "reversed_flow",
  "missed_connection",
  "questionable_journey",
]);
export type CriticFindingKind = z.infer<typeof CriticFindingKind>;

export const CriticStatus = z.enum([
  "auto_applied",
  "pending",
  "approved",
  "rejected",
]);
export type CriticStatus = z.infer<typeof CriticStatus>;

export const CriticFinding = z.object({
  id: z.string(),
  kind: CriticFindingKind,
  status: CriticStatus.default("pending"),
  confidence: z.number().min(0).max(1).default(0.5),
  message: z.string(),
  reason: z.string().default(""),
  suggestion: z.record(z.unknown()).default({}),
  affected_component_ids: z.array(z.string()).default([]),
  affected_connection_ids: z.array(z.string()).default([]),
  affected_journey_ids: z.array(z.string()).default([]),
  decided_at: z.string().nullable().optional(),
  decided_by_employee_id: z.string().nullable().optional(),
  decided_by_name: z.string().nullable().optional(),
});
export type CriticFinding = z.infer<typeof CriticFinding>;

export const CriticReview = z.object({
  ran: z.boolean().default(false),
  model: z.string().nullable().optional(),
  duration_ms: z.number().default(0),
  overall_assessment: z.string().default(""),
  critique_confidence: z.number().min(0).max(1).default(0),
  findings: z.array(CriticFinding).default([]),
  summary: z.record(z.number()).default({}),
});
export type CriticReview = z.infer<typeof CriticReview>;

export const ComplianceStatus = z.enum(["pass", "fail", "warn", "not_applicable"]);
export const Severity = z.enum(["info", "low", "medium", "high", "critical"]);

export const ComplianceFinding = z.object({
  rule: z.string(),
  status: ComplianceStatus,
  severity: Severity,
  message: z.string(),
  affected_component_ids: z.array(z.string()),
  affected_connection_ids: z.array(z.string()),
});
export type ComplianceFinding = z.infer<typeof ComplianceFinding>;

export const ParsingWarningKind = z.enum([
  "low_confidence_component",
  "ambiguous_edge",
  "unreadable_label",
  "unknown_icon",
  "overlapping_bboxes",
  "missing_trust_zone",
]);

export const ParsingWarning = z.object({
  kind: ParsingWarningKind,
  message: z.string(),
  affected_ids: z.array(z.string()),
});
export type ParsingWarning = z.infer<typeof ParsingWarning>;

export const ReviewState = z.enum([
  "auto_review_recommended",
  "needs_human_review",
  "rejected",
]);
export type ReviewState = z.infer<typeof ReviewState>;

export const ArchitectDecision = z.object({
  status: z.enum(["approved", "rejected"]),
  decided_at: z.string(),
  decided_by_employee_id: z.string().default(""),
  decided_by_name: z.string().default(""),
  decided_by_role: z.string().default(""),
  comment: z.string().default(""),
});
export type ArchitectDecision = z.infer<typeof ArchitectDecision>;

export const ReReviewStage = z.enum(["doc_intelligence", "vision_llm"]);
export type ReReviewStage = z.infer<typeof ReReviewStage>;

export const ReReviewRound = z.object({
  round_no: z.number().int(),
  status: z.enum(["accepted", "discarded"]),
  requested_at: z.string(),
  requested_by_employee_id: z.string().default(""),
  requested_by_name: z.string().default(""),
  requested_by_role: z.string().default(""),
  feedback: z.string(),
  decided_stages: z.array(ReReviewStage).default([]),
  router_reason: z.string().default(""),
  deltas: z.record(z.unknown()).default({}),
  duration_ms: z.number().default(0),
});
export type ReReviewRound = z.infer<typeof ReReviewRound>;

export const CandidateExtraction = z.object({
  round_no: z.number().int(),
  requested_at: z.string(),
  requested_by_employee_id: z.string().default(""),
  requested_by_name: z.string().default(""),
  requested_by_role: z.string().default(""),
  feedback: z.string(),
  decided_stages: z.array(ReReviewStage).default([]),
  router_reason: z.string().default(""),
  duration_ms: z.number().default(0),
  deltas: z.record(z.unknown()).default({}),

  cloud_providers: z.array(Provider).default([]),
  primary_provider: PrimaryProvider.default("unknown"),
  diagram_style: DiagramStyle.default("unknown"),
  trust_zones: z.array(TrustZone).default([]),
  components: z.array(Component).default([]),
  connections: z.array(Connection).default([]),
  flows: Flows.default({ north_south: [], east_west: [] }),
  journeys: z.array(Journey).default([]),
  compliance_findings: z.array(ComplianceFinding).default([]),
  parsing_warnings: z.array(ParsingWarning).default([]),
  critic_review: CriticReview.default({
    ran: false, duration_ms: 0, overall_assessment: "",
    critique_confidence: 0, findings: [], summary: {},
  }),
  overall_confidence: z.number().min(0).max(1).default(0),
  review_state: ReviewState.default("needs_human_review"),
});
export type CandidateExtraction = z.infer<typeof CandidateExtraction>;

export const ProcessingMs = z.object({
  image_prep: z.number(),
  doc_intelligence: z.number(),
  vision_llm: z.number(),
  post_process: z.number(),
  critic: z.number().default(0),
  total: z.number(),
});
export type ProcessingMs = z.infer<typeof ProcessingMs>;

export const ImageDimensions = z.object({
  width: z.number().int(),
  height: z.number().int(),
});
export type ImageDimensions = z.infer<typeof ImageDimensions>;

export const Submitter = z.object({
  employee_id: z.string().default(""),
  name: z.string().default(""),
  role: z.string().default(""),
  email: z.string().default(""),
});
export type Submitter = z.infer<typeof Submitter>;

export const AnalysisResult = z.object({
  diagram_id: z.string(),
  arc_number: z.string().default(""),
  title: z.string().default(""),
  description: z.string().default(""),
  submitted_by: Submitter.nullable().optional(),
  submitted_at: z.string(),
  filename: z.string(),
  input_format: InputFormat,
  image_dimensions: ImageDimensions,
  tiles_processed: z.number().int(),
  cloud_providers: z.array(Provider),
  primary_provider: PrimaryProvider,
  diagram_style: DiagramStyle,
  trust_zones: z.array(TrustZone),
  components: z.array(Component),
  connections: z.array(Connection),
  flows: Flows,
  journeys: z.array(Journey).default([]),
  critic_review: CriticReview.default({
    ran: false, duration_ms: 0, overall_assessment: "",
    critique_confidence: 0, findings: [], summary: {},
  }),
  compliance_findings: z.array(ComplianceFinding),
  parsing_warnings: z.array(ParsingWarning),
  overall_confidence: z.number().min(0).max(1),
  review_state: ReviewState,
  architect_decision: ArchitectDecision.nullable().optional(),
  re_review_history: z.array(ReReviewRound).default([]),
  candidate: CandidateExtraction.nullable().optional(),
  processing_ms: ProcessingMs,
});
export type AnalysisResult = z.infer<typeof AnalysisResult>;

export const AnalysisSummary = z.object({
  diagram_id: z.string(),
  arc_number: z.string().default(""),
  title: z.string().default(""),
  submitted_by_employee_id: z.string().default(""),
  submitted_by_name: z.string().default(""),
  submitted_at: z.string(),
  filename: z.string(),
  primary_provider: PrimaryProvider,
  components_count: z.number().int(),
  overall_confidence: z.number(),
  review_state: ReviewState,
  architect_decision_status: z.enum(["approved", "rejected", "pending"]).default("pending"),
});
export type AnalysisSummary = z.infer<typeof AnalysisSummary>;
