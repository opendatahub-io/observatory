from typing import Literal

from pydantic import BaseModel, Field, model_validator


Decision = Literal["equivalent", "related", "distinct", "needs_review"]


class CandidateGenerationInput(BaseModel):
    run_key: str = Field(min_length=1)
    retrieval_revision: str = Field(min_length=1)
    claim_id: int | None = Field(default=None, gt=0)
    batch_size: int = Field(default=250, ge=1, le=2000)
    shortlist_size: int = Field(default=10, ge=1, le=50)


class ShadowDecisionInput(BaseModel):
    decision_revision: str = Field(min_length=1)
    limit: int = Field(default=500, ge=1, le=5000)


class EquivalenceDecisionInput(BaseModel):
    decision: Decision
    rationale: str = Field(min_length=1)
    compared_qualifiers: dict = Field(default_factory=dict)
    decider_revision: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    actor: str = Field(min_length=1)


class QualifierComparison(BaseModel):
    left: str | list[str] | None = None
    right: str | list[str] | None = None
    compatible: bool | None = None
    rationale: str | None = None


class StructuredEquivalenceComparison(BaseModel):
    subject: QualifierComparison
    asserted_relationship: QualifierComparison
    negation: QualifierComparison
    product_version: QualifierComparison
    temporal_scope: QualifierComparison
    modality: QualifierComparison
    inventory_scope: QualifierComparison
    clarifications: QualifierComparison
    mutual_entailment: Literal[
        "both", "left_only", "right_only", "neither", "uncertain"
    ]


class ModelShadowDecisionInput(BaseModel):
    candidate_id: int = Field(gt=0)
    decision: Decision
    rationale: str = Field(min_length=1)
    compared_qualifiers: StructuredEquivalenceComparison
    decider_revision: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def enforce_mutual_entailment(self):
        entailment = self.compared_qualifiers.mutual_entailment
        if self.decision == "equivalent" and entailment != "both":
            raise ValueError("equivalent requires mutual entailment in both directions")
        if entailment in {"left_only", "right_only"} and self.decision != "related":
            raise ValueError("one-way implication must be related")
        if entailment == "uncertain" and self.decision != "needs_review":
            raise ValueError("uncertain entailment must abstain with needs_review")
        return self


class CanonicalGroupInput(BaseModel):
    canonical_text: str = Field(min_length=1)
    normalized_claim_ids: list[int] = Field(min_length=1)
    subject_key: str | None = None
    qualifier_summary: dict = Field(default_factory=dict)
    policy_revision: str = Field(min_length=1)
    actor: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_claims(self):
        if len(set(self.normalized_claim_ids)) != len(self.normalized_claim_ids):
            raise ValueError("normalized_claim_ids must be unique")
        return self


class GroupSplitInput(BaseModel):
    normalized_claim_ids: list[int] = Field(min_length=1)
    actor: str = Field(min_length=1)
    new_canonical_text: str | None = None
    policy_revision: str = Field(min_length=1)


class GroupRetirementInput(BaseModel):
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ConsolidationPolicyInput(BaseModel):
    revision: str = Field(min_length=1)
    automatic_assignment_enabled: bool = False
    kill_switch: bool = True
    minimum_confidence: float = Field(default=1.0, ge=0, le=1)
    minimum_precision: float = Field(default=0.99, ge=0, le=1)
    evaluated_precision: float | None = Field(default=None, ge=0, le=1)
    labeled_dataset_revision: str | None = None
    evaluation_run_id: str | None = None

    @model_validator(mode="after")
    def require_evaluated_gate(self):
        if self.automatic_assignment_enabled and not self.kill_switch:
            if (
                self.evaluated_precision is None
                or not self.labeled_dataset_revision
                or not self.evaluation_run_id
            ):
                raise ValueError(
                    "automatic assignment requires an evaluated labeled dataset run"
                )
            if self.evaluated_precision < self.minimum_precision:
                raise ValueError("evaluated precision is below the policy threshold")
        return self


class ConsolidationEvaluationInput(BaseModel):
    evaluation_run_id: str = Field(min_length=1)
    labeled_dataset_revision: str = Field(min_length=1)
    retrieval_revision: str = Field(min_length=1)
    decision_revision: str = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    labeled_pair_count: int = Field(ge=0)
    equivalent_prediction_count: int = Field(ge=0)
    true_positive_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    precision: float | None = Field(default=None, ge=0, le=1)
    recall: float | None = Field(default=None, ge=0, le=1)
    false_merge_rate: float | None = Field(default=None, ge=0, le=1)
    drift_summary: dict = Field(default_factory=dict)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_counts_and_rates(self):
        total_predictions = self.true_positive_count + self.false_positive_count
        if self.equivalent_prediction_count != total_predictions:
            raise ValueError(
                "equivalent_prediction_count must equal true positives plus false positives"
            )
        if self.equivalent_prediction_count == 0 and self.precision is not None:
            raise ValueError("precision must be null when there are no predictions")
        if self.equivalent_prediction_count > 0:
            expected_precision = self.true_positive_count / self.equivalent_prediction_count
            if self.precision is None or abs(self.precision - expected_precision) > 0.000001:
                raise ValueError("precision must match evaluation counts")
        positives = self.true_positive_count + self.false_negative_count
        if positives == 0 and self.recall is not None:
            raise ValueError("recall must be null when there are no positive labels")
        if positives > 0:
            expected_recall = self.true_positive_count / positives
            if self.recall is None or abs(self.recall - expected_recall) > 0.000001:
                raise ValueError("recall must match evaluation counts")
        return self
