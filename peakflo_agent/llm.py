"""Deterministic mock standing in for LLM, vision OCR, and judge calls.

No model, API key, network access, or model download is used by this module.
"""

from __future__ import annotations

import io
import re
from typing import Any

from pypdf import PdfReader

from .models import Discrepancy, Judgment

USE_MOCK = True  # Set False and place a real provider call at each marked boundary.


def _number(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _field(text: str, label: str) -> str:
    match = re.search(rf"(?im)^\s*{label}\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


class MockLLM:
    """Small deterministic substitute with observable fake token accounting."""

    def __init__(self) -> None:
        self.calls = 0
        self.tokens = 0

    def _count(self, text: str) -> None:
        self.calls += 1
        self.tokens += len(text) // 4 + 120

    def extract_invoice(self, text: str) -> dict[str, Any]:
        # Real provider boundary: send invoice text for schema-constrained extraction.
        self._count(text)
        items: list[dict[str, Any]] = []
        item_pattern = re.compile(
            r"(?im)^\s*ITEM\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
            r"\s*([\d,.]+)\s*\|\s*([₹$]?[\d,.]+)\s*\|\s*([\d.]+)%?\s*\|"
            r"\s*([₹$]?[\d,.]+)\s*$"
        )
        for match in item_pattern.finditer(text):
            items.append(
                {
                    "line_no": int(match.group(1)),
                    "sku": match.group(2).strip(),
                    "description": match.group(3).strip(),
                    "qty": _number(match.group(4)),
                    "unit_price": _number(match.group(5)),
                    "tax_rate": _number(match.group(6)),
                    "line_total": _number(match.group(7)),
                }
            )
        currency = _field(text, "Currency").upper()
        if not currency:
            currency = "INR" if "₹" in text else ("USD" if "$" in text else "")
        return {
            "vendor_name": _field(text, "Vendor"),
            "vendor_id": _field(text, "Vendor ID"),
            "invoice_no": _field(text, "Invoice No(?:\\.|)") or _field(text, "Invoice Number"),
            "invoice_date": _field(text, "Invoice Date"),
            "currency": currency,
            "po_number": _field(text, "PO Number"),
            "subtotal": _number(_field(text, "Subtotal")),
            "tax_amount": _number(_field(text, "Tax")),
            "total": _number(_field(text, "Total")),
            "bank_account": _field(text, "Bank Account"),
            "line_items": items,
        }

    def ocr_invoice(self, pdf_bytes: bytes) -> str:
        # Real provider boundary: submit page images to a vision/OCR model.
        fixture_text = ""
        try:
            metadata = PdfReader(io.BytesIO(pdf_bytes)).metadata or {}
            fixture_text = str(metadata.get("/OCRText", "") or metadata.get("/Subject", ""))
        except Exception:
            fixture_text = ""
        self._count(fixture_text or "image-only-pdf")
        return fixture_text

    def classify_gl(self, description: str) -> str:
        # Real provider boundary: classify an expense using chart-of-accounts context.
        self._count(description)
        lowered = description.lower()
        table = (
            (("software", "saas", "subscription", "cloud"), "6100 Software & Subscriptions"),
            (("freight", "shipping", "delivery"), "6200 Freight Inbound"),
            (("consulting", "professional", "advisory"), "6300 Professional Fees"),
            (("hardware", "equipment", "router", "server", "ssd", "ram", "processor"), "6400 Equipment"),
        )
        for keywords, account in table:
            if any(word in lowered for word in keywords):
                return account
        return "6500 Office & Admin"

    def judge(self, payload: dict[str, Any]) -> Judgment:
        # Real provider boundary: ask a judge model to evaluate evidence and routing.
        serialized = repr(payload)
        self._count(serialized)
        discrepancies = payload.get("discrepancies", [])
        warnings = sum(1 for row in discrepancies if row.get("severity") == "warning")
        blocking = sum(1 for row in discrepancies if row.get("severity") == "blocking")
        confidence = max(0.02, min(0.99, 0.99 - 0.12 * warnings - 0.45 * blocking))
        codes = [row.get("code", "UNKNOWN") for row in discrepancies]
        if blocking:
            route = "block"
            action = "Do not post; resolve blocking controls and re-run the workflow."
        elif confidence >= 0.85:
            route = "auto_post"
            action = "Post the journal to AP and retain this audit trail."
        else:
            route = "human_review"
            action = "Route to an AP analyst for evidence-backed review."
        named = ", ".join(codes) if codes else "none"
        return Judgment(
            confidence=round(confidence, 2),
            route=route,
            rationale=f"Deterministic control score evaluated discrepancy codes: {named}.",
            recommended_action=action,
            checks_passed=list(payload.get("checks_passed", [])),
            checks_failed=codes,
        )

    def explain(self, discrepancy: Discrepancy) -> str:
        # Real provider boundary: generate a user-facing explanation from evidence.
        source = f"{discrepancy.code} {discrepancy.message} {discrepancy.evidence}"
        self._count(source)
        return f"{discrepancy.code}: {discrepancy.message}"
