from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, conlist

# Type aliases ----------------------------------------------------------------

Provider = Literal["azure", "aws", "gcp", "oci", "on_prem", "kubernetes", "other"]
PrimaryProvider = Literal["azure", "aws", "gcp", "oci", "multi", "on_prem", "unknown"]
InputFormat = Literal["png", "jpg", "svg", "pdf", "drawio", "visio", "unknown"]
DiagramStyle = Literal[
    "official_stencil", "hand_drawn", "whiteboard", "mixed", "unknown"
]
TrustZoneKind = Literal[
    "external", "perimeter", "dmz", "internal", "restricted", "management"
]
Tier = Literal["edge", "web", "app", "data", "integration", "management", "unknown"]
Redundancy = Literal["single", "multi_az", "multi_region", "unknown"]
ServiceType = Literal[
    "edge_waf", "cdn", "api_gateway", "load_balancer", "dns",
    "compute_vm", "compute_serverless", "compute_container", "compute_k8s",
    "storage_object", "storage_file", "storage_block",
    "database_relational", "database_nosql", "database_cache", "database_warehouse",
    "messaging_queue", "messaging_pubsub", "messaging_event_stream",
    "identity", "secrets_vault", "key_management",
    "monitoring", "logging", "siem",
    "networking_vnet", "networking_subnet", "networking_firewall",
    "networking_private_endpoint", "networking_peering", "networking_vpn",
    "networking_express_route", "networking_nat",
    "ai_ml", "search", "integration_service", "workflow_orchestrator",
    "backup", "dr", "mainframe", "on_prem_app", "third_party_saas",
    "user_actor", "unknown",
]
ComplianceStatus = Literal["pass", "fail", "warn", "not_applicable"]
Severity = Literal["info", "low", "medium", "high", "critical"]
ParsingWarningKind = Literal[
    "low_confidence_component", "ambiguous_edge", "unreadable_label",
    "unknown_icon", "overlapping_bboxes", "missing_trust_zone",
]
ReviewState = Literal["auto_review_recommended", "needs_human_review", "rejected"]

BBox = conlist(float, min_length=4, max_length=4)


# Models ----------------------------------------------------------------------

class TrustZone(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    kind: TrustZoneKind
    bbox: BBox | None = None  # type: ignore[valid-type]
    evidence: str | None = None


class ComponentEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ocr_text: str | None = None
    bbox: BBox  # type: ignore[valid-type]
    icon_hint: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class Component(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    canonical_name: str = ""
    service_type: ServiceType = "unknown"
    provider: Provider = "other"
    trust_zone: str = ""
    tier: Tier = "unknown"
    redundancy: Redundancy = "unknown"
    evidence: ComponentEvidence


class Connection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    from_: str = Field(alias="from")
    to: str
    label: str | None = None
    protocol: str | None = None
    port: int | None = None
    encrypted: bool | None = None
    bidirectional: bool = False
    is_data_flow: bool = True
    evidence: str | None = None

    def model_dump_alias(self) -> dict:  # type: ignore[type-arg]
        return self.model_dump(by_alias=True)


class Flows(BaseModel):
    north_south: list[str] = Field(default_factory=list)
    east_west: list[str] = Field(default_factory=list)


class ComplianceFinding(BaseModel):
    rule: str
    status: ComplianceStatus
    severity: Severity
    message: str
    affected_component_ids: list[str] = Field(default_factory=list)
    affected_connection_ids: list[str] = Field(default_factory=list)


class ParsingWarning(BaseModel):
    kind: ParsingWarningKind
    message: str
    affected_ids: list[str] = Field(default_factory=list)


JourneyKind = Literal[
    "auth",         # ends at an identity provider
    "read",         # ends at a database / storage read sink
    "write",        # ends at a database / storage write sink
    "admin",        # touches a management plane component
    "integration",  # ends at messaging / SaaS / third-party
    "generic",
]


class JourneyHop(BaseModel):
    """One step on a user journey: a directed edge between two components."""
    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    from_name: str = ""
    to_name: str = ""
    label: str | None = None
    protocol: str | None = None
    port: int | None = None
    encrypted: bool | None = None
    from_zone_kind: str = ""
    to_zone_kind: str = ""
    connection_id: str | None = None
    direction_inferred: bool = False  # true if the edge was undirected and we guessed

    def model_dump_alias(self) -> dict:  # type: ignore[type-arg]
        return self.model_dump(by_alias=True)


class Journey(BaseModel):
    """A meaningful path from an entry actor to a terminal sink."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    title: str
    kind: JourneyKind = "generic"
    hops: list[JourneyHop] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)
    connection_ids: list[str] = Field(default_factory=list)
    zones_crossed: list[str] = Field(default_factory=list)  # zone KINDS, in order
    protocols: list[str] = Field(default_factory=list)
    is_fully_encrypted: bool | None = None
    has_unencrypted_hop: bool = False
    enters_restricted: bool = False
    starts_external: bool = False
    related_findings: list[str] = Field(default_factory=list)  # compliance rule ids
    score: int = 0
    narrative: str = ""
    warnings: list[str] = Field(default_factory=list)


CriticFindingKind = Literal[
    "missed_component",
    "spurious_component",
    "wrong_label",
    "wrong_service_type",
    "reversed_flow",
    "missed_connection",
    "questionable_journey",
]

CriticStatus = Literal[
    "auto_applied",   # confidence above threshold, deterministic merge done
    "pending",        # awaiting architect's accept/reject
    "approved",       # architect clicked Approve
    "rejected",       # architect clicked Reject
]


class CriticFinding(BaseModel):
    """One issue flagged by the AI self-critique pass.

    Either auto-applied (high confidence) or surfaced as `pending` for the
    architect to Approve / Reject in the AI Self-Review tab.
    """
    model_config = ConfigDict(extra="ignore")

    id: str                                # stable id like "f-1"
    kind: CriticFindingKind
    status: CriticStatus = "pending"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    message: str
    reason: str = ""                       # the critic's justification
    # Free-form payload describing the suggestion. Shape depends on `kind`:
    #   missed_component  → {name, bbox, suggested_service_type, suggested_zone}
    #   wrong_label       → {component_id, current, suggested}
    #   reversed_flow     → {connection_id}
    #   spurious_component→ {component_id}
    suggestion: dict[str, Any] = Field(default_factory=dict)  # type: ignore[type-arg]
    affected_component_ids: list[str] = Field(default_factory=list)
    affected_connection_ids: list[str] = Field(default_factory=list)
    affected_journey_ids: list[str] = Field(default_factory=list)
    # Audit fields — populated when an architect accepts or rejects.
    decided_at: str | None = None          # ISO timestamp
    decided_by_employee_id: str | None = None
    decided_by_name: str | None = None


class CriticReview(BaseModel):
    """Aggregate result of the AI Self-Critique pass."""
    model_config = ConfigDict(extra="ignore")

    ran: bool = False
    model: str | None = None
    duration_ms: int = 0
    overall_assessment: str = ""
    critique_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    findings: list[CriticFinding] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    # ^ summary["auto_applied"], summary["pending"], summary["approved"], etc.


class ArchitectDecision(BaseModel):
    """The architect's overall verdict on an entire analysis.

    Separate from the auto-computed ``review_state`` (which is a heuristic
    based on confidence + critical findings). This one is the *human's*
    final call — and every Approve / Reject is appended to the feedback
    ledger to seed the future fine-tune.
    """
    model_config = ConfigDict(extra="ignore")

    status: Literal["approved", "rejected"]
    decided_at: str                            # ISO timestamp
    decided_by_employee_id: str = ""
    decided_by_name: str = ""
    decided_by_role: str = ""
    comment: str = ""                          # optional architect note


ReReviewStage = Literal["doc_intelligence", "vision_llm"]


class ReReviewRound(BaseModel):
    """One past round of architect-driven re-extraction.

    Lives on ``AnalysisResult.re_review_history`` once a candidate has been
    Accepted or Discarded — gives the UI a chronological audit trail.
    The full new extraction is NOT inlined here (it's already either live
    on the result or thrown away); we keep just the metadata + deltas.
    """
    model_config = ConfigDict(extra="ignore")

    round_no: int                                  # 1, 2, 3, …
    status: Literal["accepted", "discarded"]
    requested_at: str
    requested_by_employee_id: str = ""
    requested_by_name: str = ""
    requested_by_role: str = ""
    feedback: str
    decided_stages: list[ReReviewStage] = Field(default_factory=list)
    router_reason: str = ""
    deltas: dict[str, Any] = Field(default_factory=dict)  # components_added, etc.
    duration_ms: int = 0


class CandidateExtraction(BaseModel):
    """A staged re-extraction awaiting architect Accept/Discard.

    Lives on ``AnalysisResult.candidate``. Mirrors the swappable subset of
    AnalysisResult fields (everything the re-run can change). When the
    architect Accepts, we copy these fields onto the parent and clear
    ``candidate``. On Discard, we just clear ``candidate``.
    """
    model_config = ConfigDict(extra="ignore")

    # — metadata —
    round_no: int
    requested_at: str
    requested_by_employee_id: str = ""
    requested_by_name: str = ""
    requested_by_role: str = ""
    feedback: str
    decided_stages: list[ReReviewStage] = Field(default_factory=list)
    router_reason: str = ""
    duration_ms: int = 0
    deltas: dict[str, Any] = Field(default_factory=dict)

    # — the new extraction (subset of AnalysisResult fields that may change) —
    cloud_providers: list[Provider] = Field(default_factory=list)
    primary_provider: PrimaryProvider = "unknown"
    diagram_style: DiagramStyle = "unknown"
    trust_zones: list[TrustZone] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    flows: Flows = Field(default_factory=Flows)
    journeys: list[Journey] = Field(default_factory=list)
    compliance_findings: list[ComplianceFinding] = Field(default_factory=list)
    parsing_warnings: list[ParsingWarning] = Field(default_factory=list)
    critic_review: CriticReview = Field(default_factory=lambda: CriticReview())
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    review_state: ReviewState = "needs_human_review"


class ProcessingMs(BaseModel):
    image_prep: int = 0
    doc_intelligence: int = 0
    vision_llm: int = 0
    post_process: int = 0
    critic: int = 0
    total: int = 0


class ImageDimensions(BaseModel):
    width: int
    height: int


class Submitter(BaseModel):
    employee_id: str = ""
    name: str = ""
    role: str = ""
    email: str = ""


class AnalysisResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    diagram_id: str
    arc_number: str = ""
    title: str = ""
    description: str = ""
    submitted_by: Submitter | None = None
    submitted_at: str
    filename: str
    input_format: InputFormat
    image_dimensions: ImageDimensions
    tiles_processed: int = 1
    cloud_providers: list[Provider] = Field(default_factory=list)
    primary_provider: PrimaryProvider = "unknown"
    diagram_style: DiagramStyle = "unknown"
    trust_zones: list[TrustZone] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    flows: Flows = Field(default_factory=Flows)
    journeys: list[Journey] = Field(default_factory=list)
    critic_review: CriticReview = Field(default_factory=lambda: CriticReview())
    compliance_findings: list[ComplianceFinding] = Field(default_factory=list)
    parsing_warnings: list[ParsingWarning] = Field(default_factory=list)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    review_state: ReviewState = "needs_human_review"
    architect_decision: ArchitectDecision | None = None
    re_review_history: list[ReReviewRound] = Field(default_factory=list)
    candidate: CandidateExtraction | None = None
    processing_ms: ProcessingMs = Field(default_factory=ProcessingMs)

    def to_json_dict(self) -> dict:  # type: ignore[type-arg]
        return self.model_dump(by_alias=True)


class AnalysisSummary(BaseModel):
    diagram_id: str
    arc_number: str = ""
    title: str = ""
    submitted_by_employee_id: str = ""
    submitted_by_name: str = ""
    submitted_at: str
    filename: str
    primary_provider: PrimaryProvider
    components_count: int
    overall_confidence: float
    review_state: ReviewState
    architect_decision_status: Literal["approved", "rejected", "pending"] = "pending"


# LLM extraction output (subset of AnalysisResult that the LLM is allowed
# to produce). Server fills in the rest.
class LLMExtraction(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    diagram_style: DiagramStyle = "unknown"
    cloud_providers: list[Provider] = Field(default_factory=list)
    trust_zones: list[TrustZone] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    parsing_warnings: list[ParsingWarning] = Field(default_factory=list)
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
