"""Dataclasses shared by the offline Peakflo AP workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LineItem:
    line_no: int
    description: str
    sku: str
    qty: float
    unit_price: float
    line_total: float
    tax_rate: float


@dataclass
class Invoice:
    vendor_name: str
    vendor_id: str
    invoice_no: str
    invoice_date: str
    currency: str
    po_number: str
    subtotal: float
    tax_amount: float
    total: float
    line_items: list[LineItem]
    source_file: str
    text_layer: bool


@dataclass
class POLine:
    sku: str
    description: str
    qty_ordered: float
    unit_price: float


@dataclass
class PurchaseOrder:
    po_number: str
    vendor_id: str
    currency: str
    line_items: list[POLine]
    approved_total: float


@dataclass
class GoodsReceipt:
    po_number: str
    lines: list[dict[str, Any]]


@dataclass
class Discrepancy:
    code: str
    severity: str
    message: str
    evidence: dict[str, Any]
    line_no: int | None = None
    amount_impact: float = 0.0

    def __post_init__(self) -> None:
        if self.severity not in {"info", "warning", "blocking"}:
            raise ValueError(f"Invalid discrepancy severity: {self.severity}")


@dataclass
class MatchResult:
    po_number: str
    status: str
    line_matches: list[dict[str, Any]] = field(default_factory=list)
    unmatched_invoice_lines: list[dict[str, Any]] = field(default_factory=list)
    unmatched_po_lines: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentStep:
    step_no: int
    name: str
    agent: str
    status: str
    duration_ms: int
    tokens: int
    summary: str
    payload_digest: str


@dataclass
class Judgment:
    confidence: float
    route: str
    rationale: str
    recommended_action: str
    checks_passed: list[str]
    checks_failed: list[str]

    def __post_init__(self) -> None:
        if self.route not in {"auto_post", "human_review", "block"}:
            raise ValueError(f"Invalid judgment route: {self.route}")


@dataclass
class AgentRun:
    invoice: Invoice | None
    match: MatchResult | None
    discrepancies: list[Discrepancy]
    judgment: Judgment
    steps: list[AgentStep]
    report_markdown: str
    report_rows: list[dict[str, Any]]
    extracted_fields: dict[str, Any] = field(default_factory=dict)

