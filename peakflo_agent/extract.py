"""PDF text ingestion and tolerant invoice extraction."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .llm import MockLLM
from .models import Discrepancy, Invoice, LineItem


REQUIRED_FIELDS = ("vendor_name", "vendor_id", "invoice_no", "invoice_date", "currency", "po_number")


def read_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def has_usable_text(text: str) -> bool:
    lowered = text.lower()
    markers = sum(token in lowered for token in ("invoice no", "vendor", "po number", "subtotal", "item |"))
    return len(text.strip()) >= 80 and markers >= 3


def normalise_date(value: str) -> str:
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except (ValueError, AttributeError):
            continue
    return value.strip() if value else ""


def extract_invoice(
    pdf_bytes: bytes,
    source_file: str,
    text_layer: bool,
    llm: MockLLM,
) -> tuple[Invoice, dict[str, Any], list[Discrepancy], str]:
    text = read_pdf_text(pdf_bytes) if text_layer else llm.ocr_invoice(pdf_bytes)
    data = llm.extract_invoice(text)
    discrepancies: list[Discrepancy] = []
    for field_name in REQUIRED_FIELDS:
        if not data.get(field_name):
            discrepancies.append(
                Discrepancy(
                    code="MISSING_FIELD",
                    severity="blocking" if field_name in {"vendor_id", "invoice_no", "currency"} else "warning",
                    message=f"Required invoice field '{field_name}' was not extracted.",
                    evidence={"field": field_name},
                )
            )
    if not data.get("line_items"):
        discrepancies.append(
            Discrepancy(
                code="MISSING_FIELD",
                severity="blocking",
                message="No invoice line items were extracted.",
                evidence={"field": "line_items"},
            )
        )
    items = [LineItem(**row) for row in data.get("line_items", [])]
    invoice = Invoice(
        vendor_name=data.get("vendor_name", ""),
        vendor_id=data.get("vendor_id", ""),
        invoice_no=data.get("invoice_no", ""),
        invoice_date=normalise_date(data.get("invoice_date", "")),
        currency=data.get("currency", "").upper(),
        po_number=data.get("po_number", ""),
        subtotal=float(data.get("subtotal", 0.0)),
        tax_amount=float(data.get("tax_amount", 0.0)),
        total=float(data.get("total", 0.0)),
        line_items=items,
        source_file=Path(source_file).name,
        text_layer=text_layer,
    )
    return invoice, data, discrepancies, text

