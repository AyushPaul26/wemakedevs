"""Shared boundary contracts for source provenance and fixed workflows.

Public views deliberately omit credentials, grants and lease-owner secrets.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Automation = Literal['review_changes', 'auto_permitted']
WorkflowStatus = Literal['queued', 'running', 'waiting_approval', 'completed', 'failed', 'rejected', 'cancelled', 'stale']
StepStatus = Literal['queued', 'running', 'waiting_approval', 'completed', 'failed', 'rejected', 'cancelled', 'stale', 'skipped']
ApprovalStatus = Literal['pending', 'approved', 'rejected', 'changes_requested', 'expired', 'stale', 'revoked']
Classification = Literal['general', 'finance']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SourceRef(Contract):
    source_id: Identifier
    version_id: Identifier


class EvidenceLocator(Contract):
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    row_start: int | None = Field(default=None, ge=1)
    row_end: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def ordered_rows(self):
        if self.row_end is not None and (self.row_start is None or self.row_end < self.row_start):
            raise ValueError('Invalid row range')
        return self


class EvidenceRef(SourceRef):
    chunk_id: Identifier
    locator: EvidenceLocator
    title: ShortText


class SourceSummary(Contract):
    id: Identifier
    title: ShortText
    type: Identifier
    author: str
    updated_at: str
    current_version_id: Identifier | None = None
    classification: Classification
    department_id: Identifier
    processing_status: str


class SourceDetail(SourceSummary):
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class MemberView(Contract):
    id: Identifier
    display_name: ShortText
    role: Literal['admin', 'operator', 'finance_auditor']
    department_ids: list[Identifier]


class SessionView(Contract):
    member: MemberView
    csrf_token: str
    expires_at: str


class RunInputs(Contract):
    invoice: SourceRef
    purchase_order: SourceRef
    context: list[SourceRef] = Field(default_factory=list, max_length=3)
    automation: Automation
    output_audience: list[Identifier] = Field(min_length=1, max_length=100)


class RunCreate(RunInputs):
    template: Literal['invoice_review']
    project_id: Identifier


class RunRevision(RunInputs):
    expected_revision: int = Field(ge=0)


class ApprovalDecision(Contract):
    decision: Literal['approve', 'reject', 'request_changes']
    expected_revision: int = Field(ge=0)
    scope_hash: Identifier
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)] | None = None

    @model_validator(mode='after')
    def decision_reason(self):
        if self.decision != 'approve' and not self.reason:
            raise ValueError('A reason is required')
        return self


class RunSnapshot(Contract):
    id: Identifier
    template: Literal['invoice_review']
    current_plan_id: Identifier
    generation: int = Field(ge=1)
    revision: int = Field(ge=0)
    status: WorkflowStatus
    steps: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    allowed_controls: list[str]
    created_at: str
    updated_at: str


class MigrationReport(Contract):
    current_version: int
    target_version: int
    phase: str
    counts: dict[str, int]
    violations: list[str]


class SourcePage(Contract):
    items: list[SourceSummary]
    next_cursor: str | None = None


class EventPage(Contract):
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class VersionResult(Contract):
    ref: SourceRef
    source_revision: int
    invalidated_run_ids: list[str]


class StoredBlob(Contract):
    key: str
    sha256: str
    byte_size: int = Field(ge=0)
    mime: str


class ParsedRow(Contract):
    item_id: str
    quantity: int = Field(ge=1, le=1000000)
    unit_price: str
    row_number: int = Field(ge=2)


class ParsedTable(Contract):
    currency: Literal['USD', 'INR', 'EUR', 'GBP']
    rows: list[ParsedRow]


class ParsedDocument(Contract):
    chunks: list[dict[str, Any]]
    table: ParsedTable | None = None


class ComparisonResult(Contract):
    currency: Literal['USD', 'INR', 'EUR', 'GBP']
    invoice_total: str
    order_total: str
    difference: str
    findings: list[dict[str, Any]]


class StepLease(Contract):
    step_id: Identifier
    run_id: Identifier
    plan_id: Identifier
    generation: int
    fence: int
    worker_id: Identifier
    lease_until: str


class StepEffects(Contract):
    effect_key: str
    result: dict[str, Any]
    evidence_refs: list[EvidenceRef]
    artifacts: list[dict[str, Any]]
    case_revision: dict[str, Any] | None = None


class StagedArtifacts(Contract):
    items: list[dict[str, Any]]


class RecoveryReport(Contract):
    requeued: list[str]
    waiting: list[str]
    reconciled: list[str]
    failed: list[str]


class EvidenceContext(Contract):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    prior_memories: list[dict[str, Any]] = Field(default_factory=list)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    permitted_run_outputs: list[dict[str, Any]] = Field(default_factory=list)
