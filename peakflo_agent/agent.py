"""Seven-step deterministic agentic accounts-payable workflow."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .extract import extract_invoice, has_usable_text, read_pdf_text
from .llm import MockLLM
from .match import match_invoice
from .models import AgentRun, AgentStep, Discrepancy, Invoice, Judgment, MatchResult
from .report import build_report


PRICE_TOLERANCE_PCT = 2.0
PRICE_TOLERANCE_ABS = 50.0
TAX_TOLERANCE_ABS = 1.00


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _step(
    steps: list[AgentStep],
    step_no: int,
    name: str,
    agent: str,
    started: float,
    tokens_before: int,
    llm: MockLLM,
    summary: str,
    payload: Any,
    status: str = "completed",
) -> None:
    steps.append(
        AgentStep(
            step_no=step_no,
            name=name,
            agent=agent,
            status=status,
            duration_ms=max(1, int((time.perf_counter() - started) * 1000)),
            tokens=llm.tokens - tokens_before,
            summary=summary,
            payload_digest=_digest(payload),
        )
    )


def _load_source(source: bytes | str | Path) -> tuple[bytes, str]:
    if isinstance(source, bytes):
        return source, "uploaded_invoice.pdf"
    path = Path(source)
    return path.read_bytes(), path.name


def _coerce_po(po_ledger: dict[str, Any], po_number: str) -> dict[str, Any] | None:
    value = po_ledger.get(po_number)
    return asdict(value) if value is not None and not isinstance(value, dict) else value


def _validate(invoice: Invoice, po_ledger: dict[str, Any]) -> tuple[list[Discrepancy], list[str]]:
    rows: list[Discrepancy] = []
    passed: list[str] = []
    line_sum = sum(item.line_total for item in invoice.line_items)
    if abs(line_sum - invoice.subtotal) > 0.02:
        rows.append(Discrepancy("ARITHMETIC_MISMATCH", "blocking", "Line totals do not equal subtotal.", {"line_sum": line_sum, "subtotal": invoice.subtotal}, amount_impact=abs(line_sum - invoice.subtotal)))
    else:
        passed.append("line totals equal subtotal")
    if abs(invoice.subtotal + invoice.tax_amount - invoice.total) > 0.02:
        rows.append(Discrepancy("ARITHMETIC_MISMATCH", "blocking", "Subtotal plus tax does not equal total.", {"calculated": invoice.subtotal + invoice.tax_amount, "total": invoice.total}, amount_impact=abs(invoice.subtotal + invoice.tax_amount - invoice.total)))
    else:
        passed.append("subtotal plus tax equals total")
    for item in invoice.line_items:
        calculated = item.qty * item.unit_price
        if abs(calculated - item.line_total) > 0.02:
            rows.append(Discrepancy("LINE_ARITHMETIC", "blocking", f"Quantity × unit price differs on line {item.line_no}.", {"calculated": calculated, "line_total": item.line_total}, line_no=item.line_no, amount_impact=abs(calculated - item.line_total)))
    try:
        invoice_day = datetime.strptime(invoice.invoice_date, "%Y-%m-%d").date()
        age = (date.today() - invoice_day).days
        if age < 0 or age > 365:
            rows.append(Discrepancy("DATE_OUT_OF_RANGE", "warning", "Invoice date is in the future or more than 365 days old.", {"invoice_date": invoice.invoice_date, "age_days": age}))
        else:
            passed.append("invoice date within 365-day policy")
    except ValueError:
        if invoice.invoice_date:
            rows.append(Discrepancy("DATE_OUT_OF_RANGE", "warning", "Invoice date format could not be validated.", {"invoice_date": invoice.invoice_date}))
    po = _coerce_po(po_ledger, invoice.po_number)
    if po and invoice.currency == str(po.get("currency", "")).upper():
        passed.append("invoice currency matches PO")
    elif po:
        rows.append(Discrepancy("CURRENCY_MISMATCH", "blocking", "Invoice currency does not match the PO.", {"invoice_currency": invoice.currency, "po_currency": po.get("currency")}))
    return rows, passed


def _detect(
    invoice: Invoice,
    match: MatchResult,
    extracted: dict[str, Any],
    ledger: dict[str, Any],
    po_ledger: dict[str, Any],
) -> list[Discrepancy]:
    rows: list[Discrepancy] = []
    if not invoice.po_number or invoice.po_number not in po_ledger:
        rows.append(Discrepancy("MISSING_PO", "blocking", "The PO number is missing or absent from the ledger.", {"po_number": invoice.po_number}))
    invoice_by_line = {item.line_no: item for item in invoice.line_items}
    for line in match.line_matches:
        item = invoice_by_line.get(int(line["invoice_line"]))
        delta_pct = float(line["price_delta_pct"])
        impact = abs(float(line["invoice_unit_price"]) - float(line["po_unit_price"])) * float(line["invoice_qty"])
        if abs(delta_pct) > 0.005:
            severity = "warning" if abs(delta_pct) > PRICE_TOLERANCE_PCT and impact > PRICE_TOLERANCE_ABS else "info"
            rows.append(Discrepancy("PRICE_VARIANCE", severity, f"Invoice price differs from PO by {delta_pct:.2f}%.", {"invoice_unit_price": line["invoice_unit_price"], "po_unit_price": line["po_unit_price"], "delta_pct": delta_pct}, line_no=int(line["invoice_line"]), amount_impact=round(impact, 2)))
        qty_delta = float(line["qty_delta"])
        if qty_delta > 0.001:
            rows.append(Discrepancy("QTY_OVER_RECEIPT", "blocking", "Invoiced quantity exceeds goods received.", {"invoice_qty": line["invoice_qty"], "qty_received": line["qty_received"]}, line_no=int(line["invoice_line"]), amount_impact=round(qty_delta * float(line["invoice_unit_price"]), 2)))
        elif qty_delta < -0.001:
            rows.append(Discrepancy("QTY_UNDER_RECEIPT", "warning", "Invoiced quantity is below goods received.", {"invoice_qty": line["invoice_qty"], "qty_received": line["qty_received"]}, line_no=int(line["invoice_line"]), amount_impact=round(abs(qty_delta) * float(line["invoice_unit_price"]), 2)))
        if item is not None:
            expected_tax = item.line_total * item.tax_rate / 100.0
        else:
            expected_tax = 0.0
    expected_tax_total = sum(item.line_total * item.tax_rate / 100.0 for item in invoice.line_items)
    tax_delta = abs(invoice.tax_amount - expected_tax_total)
    if tax_delta > TAX_TOLERANCE_ABS:
        rows.append(Discrepancy("TAX_MISMATCH", "blocking", "Invoice tax differs from line-level expected tax.", {"invoice_tax": invoice.tax_amount, "expected_tax": round(expected_tax_total, 2)}, amount_impact=round(tax_delta, 2)))
    for line in match.unmatched_invoice_lines:
        rows.append(Discrepancy("UNMATCHED_LINE", "warning", "Invoice line could not be matched to the PO.", {"sku": line.get("sku"), "description": line.get("description")}, line_no=line.get("line_no"), amount_impact=float(line.get("line_total", 0.0))))
    posted = ledger.get("posted_invoices", [])
    if any(str(row.get("vendor_id")) == invoice.vendor_id and str(row.get("invoice_no")) == invoice.invoice_no for row in posted):
        rows.append(Discrepancy("DUPLICATE_INVOICE", "blocking", "Vendor and invoice number already exist in the posted ledger.", {"vendor_id": invoice.vendor_id, "invoice_no": invoice.invoice_no}, amount_impact=invoice.total))
    vendor = ledger.get("vendors", {}).get(invoice.vendor_id, {})
    on_file = str(vendor.get("bank_account", ""))
    supplied = str(extracted.get("bank_account", ""))
    if on_file and supplied and on_file != supplied:
        rows.append(Discrepancy("BANK_CHANGE", "blocking", "Invoice bank account differs from the vendor master.", {"on_file": on_file, "invoice": supplied}, amount_impact=invoice.total))
    return rows


def run_agent(
    pdf_bytes_or_path: bytes | str | Path,
    ledger: dict[str, Any],
    po_ledger: dict[str, Any],
    grn_ledger: dict[str, Any],
) -> AgentRun:
    """Run all seven agent steps and return an auditable result."""
    llm = MockLLM()
    steps: list[AgentStep] = []
    discrepancies: list[Discrepancy] = []

    started = time.perf_counter()
    before = llm.tokens
    pdf_bytes, source_name = _load_source(pdf_bytes_or_path)
    page_text = read_pdf_text(pdf_bytes)
    text_layer = has_usable_text(page_text)
    _step(steps, 1, "ingest", "Document intake agent", started, before, llm, f"Accepted {source_name}; classified as {'text-layer' if text_layer else 'scanned/image-only'} PDF.", {"source": source_name, "text_layer": text_layer, "bytes": len(pdf_bytes)})

    started = time.perf_counter()
    before = llm.tokens
    invoice, extracted, extraction_issues, extracted_text = extract_invoice(pdf_bytes, source_name, text_layer, llm)
    discrepancies.extend(extraction_issues)
    path_name = "pypdf text + mock extraction" if text_layer else "mock vision OCR + mock extraction"
    _step(steps, 2, "extract", "Invoice understanding agent", started, before, llm, f"Used {path_name}; extracted {len(invoice.line_items)} line(s).", {"invoice": asdict(invoice), "text_chars": len(extracted_text)})

    started = time.perf_counter()
    before = llm.tokens
    validation_issues, checks_passed = _validate(invoice, po_ledger)
    discrepancies.extend(validation_issues)
    _step(steps, 3, "validate", "Financial controls agent", started, before, llm, f"Ran arithmetic, date, and currency checks; {len(validation_issues)} issue(s).", {"issues": [asdict(row) for row in validation_issues], "passed": checks_passed})

    started = time.perf_counter()
    before = llm.tokens
    match = match_invoice(invoice, po_ledger, grn_ledger)
    _step(steps, 4, "po_match", "Three-way matching agent", started, before, llm, f"Match status {match.status}; {len(match.line_matches)} line(s) matched.", asdict(match))

    started = time.perf_counter()
    before = llm.tokens
    detected = _detect(invoice, match, extracted, ledger, po_ledger)
    discrepancies.extend(detected)
    _step(steps, 5, "detect", "Exception detection agent", started, before, llm, f"Detected {len(detected)} policy exception(s).", [asdict(row) for row in detected])

    started = time.perf_counter()
    before = llm.tokens
    judgment = llm.judge({"discrepancies": [asdict(row) for row in discrepancies], "checks_passed": checks_passed, "match_status": match.status})
    _step(steps, 6, "judge", "LLM-as-judge agent (mock)", started, before, llm, f"Routed to {judgment.route} at {judgment.confidence:.0%} confidence.", asdict(judgment))

    started = time.perf_counter()
    before = llm.tokens
    report_markdown, report_rows = build_report(invoice, match, discrepancies, judgment, llm)
    _step(steps, 7, "report", "Reconciliation and posting agent", started, before, llm, f"Prepared reconciliation report and {len(report_rows)} posting/coding row(s).", report_rows)
    return AgentRun(invoice, match, discrepancies, judgment, steps, report_markdown, report_rows, extracted)


def run_agent_safe(
    pdf_bytes_or_path: bytes | str | Path,
    ledger: dict[str, Any],
    po_ledger: dict[str, Any],
    grn_ledger: dict[str, Any],
) -> AgentRun:
    """Run the workflow without leaking exceptions to a UI caller."""
    try:
        return run_agent(pdf_bytes_or_path, ledger, po_ledger, grn_ledger)
    except Exception as exc:
        failure = Discrepancy("AGENT_FAILURE", "blocking", "The workflow could not complete safely.", {"error_type": type(exc).__name__})
        judgment = Judgment(0.02, "block", "Workflow failure recorded as AGENT_FAILURE.", "Inspect the input and audit record, then retry.", [], ["AGENT_FAILURE"])
        step = AgentStep(0, "failure", "Safety wrapper", "failed", 1, 0, f"{type(exc).__name__}: {exc}", _digest({"type": type(exc).__name__, "message": str(exc)}))
        return AgentRun(None, None, [failure], judgment, [step], "# Reconciliation report\n\nWorkflow failed safely; no posting preview was created.", [], {})

