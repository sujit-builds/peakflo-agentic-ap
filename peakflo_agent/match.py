"""Deterministic invoice-to-PO-to-GRN matching."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from .models import GoodsReceipt, Invoice, MatchResult, POLine, PurchaseOrder


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _po(value: PurchaseOrder | dict[str, Any]) -> PurchaseOrder:
    if isinstance(value, PurchaseOrder):
        return value
    return PurchaseOrder(
        po_number=value["po_number"],
        vendor_id=value["vendor_id"],
        currency=value["currency"],
        line_items=[row if isinstance(row, POLine) else POLine(**row) for row in value.get("line_items", [])],
        approved_total=float(value.get("approved_total", 0.0)),
    )


def _grn(value: GoodsReceipt | dict[str, Any] | None, po_number: str) -> GoodsReceipt:
    if isinstance(value, GoodsReceipt):
        return value
    if isinstance(value, dict):
        return GoodsReceipt(po_number=value.get("po_number", po_number), lines=value.get("lines", []))
    return GoodsReceipt(po_number=po_number, lines=[])


def match_invoice(
    invoice: Invoice,
    po_ledger: dict[str, PurchaseOrder | dict[str, Any]],
    grn_ledger: dict[str, GoodsReceipt | dict[str, Any]],
) -> MatchResult:
    if not invoice.po_number or invoice.po_number not in po_ledger:
        return MatchResult(
            po_number=invoice.po_number,
            status="no_po",
            unmatched_invoice_lines=[asdict(line) for line in invoice.line_items],
        )
    po = _po(po_ledger[invoice.po_number])
    grn = _grn(grn_ledger.get(invoice.po_number), invoice.po_number)
    received = {str(row.get("sku", "")): float(row.get("qty_received", 0.0)) for row in grn.lines}
    unused = set(range(len(po.line_items)))
    line_matches: list[dict[str, Any]] = []
    unmatched_invoice: list[dict[str, Any]] = []
    for invoice_line in invoice.line_items:
        candidate = next((i for i in unused if po.line_items[i].sku and po.line_items[i].sku == invoice_line.sku), None)
        if candidate is None:
            candidate = next(
                (i for i in unused if _normalise(po.line_items[i].description) == _normalise(invoice_line.description)),
                None,
            )
        if candidate is None:
            unmatched_invoice.append(asdict(invoice_line))
            continue
        unused.remove(candidate)
        po_line = po.line_items[candidate]
        price_delta_pct = (
            ((invoice_line.unit_price - po_line.unit_price) / po_line.unit_price) * 100.0
            if po_line.unit_price
            else 0.0
        )
        qty_received = received.get(po_line.sku, 0.0)
        line_matches.append(
            {
                "invoice_line": invoice_line.line_no,
                "invoice_sku": invoice_line.sku,
                "description": invoice_line.description,
                "invoice_qty": invoice_line.qty,
                "invoice_unit_price": invoice_line.unit_price,
                "invoice_line_total": invoice_line.line_total,
                "po_qty": po_line.qty_ordered,
                "po_unit_price": po_line.unit_price,
                "qty_received": qty_received,
                "price_delta_pct": round(price_delta_pct, 2),
                "qty_delta": round(invoice_line.qty - qty_received, 2),
                "matched_sku": po_line.sku,
            }
        )
    unmatched_po = [asdict(po.line_items[index]) for index in sorted(unused)]
    status = "matched" if not unmatched_invoice and not unmatched_po else "partial"
    return MatchResult(
        po_number=invoice.po_number,
        status=status,
        line_matches=line_matches,
        unmatched_invoice_lines=unmatched_invoice,
        unmatched_po_lines=unmatched_po,
    )

