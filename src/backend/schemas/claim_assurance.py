from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


class EvidenceRecord(BaseModel):
    evidence_type: str
    uri: str | None = None
    repository_revision: str | None = None
    artifact_digest: str | None = None
    source_locator: str | None = None
    query: str | None = None
    excerpt: str | None = None
    relationship: str | None = None
    authority: str | None = None
    product_version: str | None = None
    retrieved_at: str | None = None


class SourceUnit(BaseModel):
    unit_key: str = Field(validation_alias=AliasChoices("unit_key", "id"))
    unit_kind: str = Field(validation_alias=AliasChoices("unit_kind", "kind"))
    source_locator: str
    original_text: str = Field(validation_alias=AliasChoices("original_text", "text"))
    heading_path: list[str] = Field(default_factory=list)
    preceding_context: list[str] = Field(default_factory=list)
    following_context: list[str] = Field(default_factory=list)
    list_preamble: str | None = None


class SelectionResult(BaseModel):
    classification: Literal["verifiable", "mixed", "unverifiable"]
    selected_text: str | None = None
    rationale: str | None = None
    evaluator_revision: str

    @model_validator(mode="after")
    def require_mixed_selection(self):
        if self.classification == "mixed" and not self.selected_text:
            raise ValueError("mixed selection requires selected_text")
        return self


class AmbiguityResult(BaseModel):
    status: Literal["none", "resolved", "unresolved"]
    ambiguity_types: list[str] = Field(default_factory=list)
    clarified_text: str | None = None
    resolution_context: list[str] = Field(default_factory=list)
    rationale: str | None = None
    evaluator_revision: str

    @model_validator(mode="after")
    def require_resolved_clarification(self):
        if self.status == "resolved" and not self.clarified_text:
            raise ValueError("resolved ambiguity requires clarified_text")
        return self


class CoverageElement(BaseModel):
    element_text: str
    element_kind: Literal["verifiable", "unverifiable"]
    coverage: Literal["explicit", "implicit", "omitted", "included"]
    rationale: str | None = None

    @model_validator(mode="after")
    def require_kind_appropriate_coverage(self):
        allowed = (
            {"explicit", "implicit", "omitted"}
            if self.element_kind == "verifiable" else {"omitted", "included"}
        )
        if self.coverage not in allowed:
            raise ValueError("coverage is invalid for element_kind")
        return self


class ExtractionEvaluation(BaseModel):
    evaluator_revision: str
    entailed: bool | None = None
    entailment_rationale: str | None = None
    coverage_result: Literal["complete", "partial", "failed"]
    decontextualization_result: Literal[
        "desirable", "undesirable", "self_contained", "needs_review", "not_sampled"
    ]
    maximally_contextualized_claim: str | None = None
    extracted_retrieval_digest: str | None = None
    comparison_retrieval_digest: str | None = None
    evidence_context_digest: str | None = None
    coverage_elements: list[CoverageElement] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_element_coverage(self):
        if not self.coverage_elements:
            raise ValueError("extraction evaluation requires coverage_elements")
        if not self.evidence:
            raise ValueError("extraction evaluation requires source evidence")
        if self.decontextualization_result in {"desirable", "undesirable"}:
            required = (
                "maximally_contextualized_claim",
                "extracted_retrieval_digest",
                "comparison_retrieval_digest",
                "evidence_context_digest",
            )
            missing = [field for field in required if not getattr(self, field)]
            if missing:
                raise ValueError(
                    "full decontextualization comparison requires "
                    + ", ".join(missing)
                )
        return self


class ClaimOccurrenceInput(BaseModel):
    claim_text: str = Field(validation_alias=AliasChoices("claim_text", "claim"))
    claim_type: Literal[
        "factual", "architectural", "security", "scope", "attribution"
    ] = Field(
        validation_alias=AliasChoices("claim_type", "type")
    )
    original_text: str | None = None
    modality: str | None = None
    product_version: str | None = None
    temporal_scope: str | None = None
    clarification: str | None = None
    accepted: bool = True
    jira_keys: list[str] = Field(default_factory=list)
    evaluation: ExtractionEvaluation | None = None

    @model_validator(mode="after")
    def require_extraction_evaluation(self):
        if self.evaluation is None:
            raise ValueError("a staged claim occurrence requires extraction evaluation")
        if self.evaluation.entailed is not True and self.accepted:
            raise ValueError("a non-entailed occurrence cannot be accepted")
        return self


class UnitExtractionInput(BaseModel):
    source_unit: SourceUnit
    selection: SelectionResult
    ambiguity: AmbiguityResult | None = None
    claims: list[ClaimOccurrenceInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def preserve_stage_boundaries(self):
        classification = self.selection.classification
        if classification == "unverifiable" and self.claims:
            raise ValueError("unverifiable source units cannot emit claims")
        if classification != "unverifiable" and self.ambiguity is None:
            raise ValueError("selected source units require ambiguity evaluation")
        if self.ambiguity and self.ambiguity.status == "unresolved" and self.claims:
            raise ValueError("unresolved source units cannot emit claims")
        bounded_source = "\n".join([
            *self.source_unit.preceding_context,
            self.source_unit.original_text,
            *self.source_unit.following_context,
        ])
        for claim in self.claims:
            if claim.original_text and claim.original_text not in bounded_source:
                raise ValueError(
                    "claim original_text must be an exact bounded-source excerpt"
                )
        return self


class ExtractionRunInput(BaseModel):
    run_key: str
    source_file: str
    pipeline_slug: str
    artifact_type: str | None = None
    artifact_digest: str | None = None
    extractor_revision: str
    repository_revision: str | None = None
    model: str | None = None
    harness: str | None = None
    configuration_digest: str | None = None
    configuration: dict = Field(default_factory=dict)
    token_count: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    units: list[UnitExtractionInput]


class VerificationRunInput(BaseModel):
    claim_occurrence_id: int
    verifier_revision: str
    repository_revision: str | None = None
    model: str | None = None
    harness: str | None = None
    configuration_digest: str | None = None
    evidence_context_digest: str = Field(min_length=1)
    verdict: Literal["supported", "contradicted", "insufficient_evidence", "not_applicable"]
    severity: Literal["info", "low", "medium", "high", "critical"] | None = None
    confidence: int = Field(ge=0, le=100)
    evidence_summary: str | None = None
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    token_count: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_verdict_evidence(self):
        if self.verdict != "not_applicable" and not self.evidence:
            raise ValueError("factual verification verdict requires evidence")
        return self


class ExplanationRunInput(BaseModel):
    verification_run_id: int
    explainer_revision: str
    repository_revision: str | None = None
    model: str | None = None
    harness: str | None = None
    configuration_digest: str | None = None
    category: Literal[
        "skill_instruction_gap", "context_gap", "retrieval_failure",
        "source_misinterpretation", "workflow_gap", "tool_or_harness_gap",
        "model_reasoning_error", "human_source_quality", "compound_error", "unknown",
    ]
    improvement_target: str | None = None
    explanation: str
    contributing_factors: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    remediation: str | None = None
    regression_test: str | None = None
    human_review_required: bool = False
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    token_count: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_improvement_route_or_review(self):
        if self.category == "unknown":
            if not self.human_review_required:
                raise ValueError("unknown explanations require human review")
        elif not all((self.improvement_target, self.remediation, self.regression_test)):
            raise ValueError(
                "routed explanations require improvement_target, remediation, and regression_test"
            )
        elif not self.evidence:
            raise ValueError("routed explanations require attribution evidence")
        return self


class HumanOverrideInput(BaseModel):
    claim_occurrence_id: int
    verification_run_id: int = Field(gt=0)
    actor: str
    decision: str
    rationale: str


class RegressionRunInput(BaseModel):
    explanation_run_id: int
    dataset_fqn: str
    implementation_revision: str
    status: Literal["queued", "running", "passed", "failed", "error"]
    metrics: dict = Field(default_factory=dict)
    run_uri: str | None = None


class StageReceiptEventInput(BaseModel):
    stage: str
    scope_key: str
    input_digest: str
    evidence_context_digest: str | None = None
    skill_fqn: str
    skill_revision: str
    model: str | None = None
    harness: str | None = None
    configuration_digest: str | None = None
    status: Literal["hit", "miss", "written", "invalid"]
    agent_job_avoided: bool = False
    details: dict = Field(default_factory=dict)
