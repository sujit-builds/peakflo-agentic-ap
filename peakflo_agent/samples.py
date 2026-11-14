"""Generate five deterministic AP demo cases and their local ledgers."""

from __future__ import annotations

import io
import json
import struct
import zlib
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .models import GoodsReceipt, POLine, PurchaseOrder


def _png_placeholder(width: int = 900, height: int = 1100) -> bytes:
    """Create a plain RGB PNG using only the standard library."""
    row = b"\x00" + b"\xe9\xed\xf2" * width
    raw = row * height
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _invoice_text(case: dict[str, Any]) -> str:
    lines = [
        f"Vendor: {case['vendor_name']}",
        f"Vendor ID: {case['vendor_id']}",
        f"Bank Account: {case['bank_account']}",
        f"Invoice No: {case['invoice_no']}",
        f"Invoice Date: {case['invoice_date']}",
        f"Currency: {case['currency']}",
        f"PO Number: {case['po_number']}",
    ]
    for index, item in enumerate(case["line_items"], 1):
        lines.append(
            f"ITEM | {index} | {item['sku']} | {item['description']} | {item['qty']:.2f} | "
            f"{item['unit_price']:,.2f} | {item['tax_rate']:.2f} | {item['line_total']:,.2f}"
        )
    lines.extend(
        (
            f"Subtotal: {case['currency']} {case['subtotal']:,.2f}",
            f"Tax: {case['currency']} {case['tax_amount']:,.2f}",
            f"Total: {case['currency']} {case['total']:,.2f}",
        )
    )
    return "\n".join(lines)


def _write_invoice_pdf(path: Path, case: dict[str, Any], scanned: bool = False) -> str:
    raw_text = _invoice_text(case)
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    pdf.setTitle(f"Invoice {case['invoice_no']}")
    if scanned:
        pdf.setAuthor("Offline scanned invoice fixture")
        image = ImageReader(io.BytesIO(_png_placeholder()))
        pdf.drawImage(image, 50, 90, width=width - 100, height=height - 150, preserveAspectRatio=False)
        pdf.setFillColor(colors.HexColor("#16324F"))
        pdf.rect(50, height - 125, width - 100, 35, fill=1, stroke=0)
        # Deliberately no page text: OCR fixture text is held in metadata only.
        pdf.setSubject(raw_text)
        pdf.showPage()
        pdf.save()
        return raw_text

    pdf.setFillColor(colors.HexColor("#16324F"))
    pdf.rect(0, height - 82, width, 82, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(42, height - 50, "INVOICE")
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(width - 42, height - 49, case["vendor_name"])
    pdf.setFillColor(colors.HexColor("#1E293B"))
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(42, height - 112, case["vendor_name"])
    pdf.setFont("Helvetica", 9)
    y = height - 132
    for line in raw_text.splitlines()[:7]:
        pdf.drawString(42, y, line)
        y -= 15
    y -= 10
    pdf.setFillColor(colors.HexColor("#E2E8F0"))
    pdf.rect(42, y - 5, width - 84, 22, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#334155"))
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(48, y + 3, "LINE  |  SKU  |  DESCRIPTION  |  QTY  |  UNIT PRICE  |  TAX %  |  LINE TOTAL")
    y -= 24
    pdf.setFont("Helvetica", 8)
    for line in raw_text.splitlines()[7 : 7 + len(case["line_items"])]:
        pdf.drawString(48, y, line)
        y -= 21
    pdf.setStrokeColor(colors.HexColor("#CBD5E1"))
    pdf.line(42, y + 10, width - 42, y + 10)
    y -= 8
    pdf.setFont("Helvetica", 10)
    for line in raw_text.splitlines()[-3:]:
        pdf.drawRightString(width - 42, y, line)
        y -= 18
    pdf.setFillColor(colors.HexColor("#64748B"))
    pdf.setFont("Helvetica", 8)
    pdf.drawString(42, 45, "Generated locally for the zero-network agentic AP demonstration")
    pdf.showPage()
    pdf.save()
    return raw_text


def build_samples(dirpath: str | Path) -> list[dict[str, Any]]:
    """Write PDF fixtures and JSON ledgers, then return executable sample cases."""
    output = Path(dirpath)
    output.mkdir(parents=True, exist_ok=True)
    invoice_day = (date.today() - timedelta(days=30)).isoformat()
    northwind_bank = "NW-IN-001-8899"
    helios_bank = "HC-US-4410"
    case_data = [
        {
            "id": "S1", "title": "Clean three-line PO invoice", "expected_route": "auto_post", "expected_codes": [],
            "vendor_name": "Northwind Components Pvt Ltd", "vendor_id": "V-NW-001", "bank_account": northwind_bank,
            "invoice_no": "NW-2026-1001", "invoice_date": invoice_day, "currency": "INR", "po_number": "PO-NW-1001",
            "line_items": [
                {"sku": "NWC-CPU", "description": "Server processor hardware", "qty": 50.0, "unit_price": 2000.0, "line_total": 100000.0, "tax_rate": 18.0},
                {"sku": "NWC-SSD", "description": "Enterprise SSD equipment", "qty": 40.0, "unit_price": 2500.0, "line_total": 100000.0, "tax_rate": 18.0},
                {"sku": "NWC-RAM", "description": "ECC RAM hardware", "qty": 100.0, "unit_price": 800.0, "line_total": 80000.0, "tax_rate": 18.0},
            ],
        },
        {
            "id": "S2", "title": "Price variance above policy", "expected_route": "human_review", "expected_codes": ["PRICE_VARIANCE", "QTY_UNDER_RECEIPT"],
            "vendor_name": "Northwind Components Pvt Ltd", "vendor_id": "V-NW-001", "bank_account": northwind_bank,
            "invoice_no": "NW-2026-1002", "invoice_date": invoice_day, "currency": "INR", "po_number": "PO-NW-1002",
            "line_items": [{"sku": "NWC-RTR", "description": "Network router equipment", "qty": 4.0, "unit_price": 20960.0, "line_total": 83840.0, "tax_rate": 18.0}],
        },
        {
            "id": "S3", "title": "Quantity exceeds goods receipt", "expected_route": "block", "expected_codes": ["QTY_OVER_RECEIPT"],
            "vendor_name": "Northwind Components Pvt Ltd", "vendor_id": "V-NW-001", "bank_account": northwind_bank,
            "invoice_no": "NW-2026-1003", "invoice_date": invoice_day, "currency": "INR", "po_number": "PO-NW-1003",
            "line_items": [{"sku": "NWC-NIC", "description": "Network interface hardware", "qty": 120.0, "unit_price": 1000.0, "line_total": 120000.0, "tax_rate": 18.0}],
        },
        {
            "id": "S4", "title": "Duplicate vendor invoice", "expected_route": "block", "expected_codes": ["DUPLICATE_INVOICE"],
            "vendor_name": "Northwind Components Pvt Ltd", "vendor_id": "V-NW-001", "bank_account": northwind_bank,
            "invoice_no": "NW-2026-0998", "invoice_date": invoice_day, "currency": "INR", "po_number": "PO-NW-1004",
            "line_items": [{"sku": "NWC-SRV", "description": "Rack server equipment", "qty": 20.0, "unit_price": 5000.0, "line_total": 100000.0, "tax_rate": 18.0}],
        },
        {
            "id": "S5", "title": "Scanned clean cloud invoice", "expected_route": "auto_post", "expected_codes": [],
            "vendor_name": "Helios Cloud Services Inc", "vendor_id": "V-HC-001", "bank_account": helios_bank,
            "invoice_no": "HC-2026-7015", "invoice_date": invoice_day, "currency": "USD", "po_number": "PO-HC-2001",
            "line_items": [{"sku": "HC-SAAS-A", "description": "Annual SaaS software subscription", "qty": 1.0, "unit_price": 6000.0, "line_total": 6000.0, "tax_rate": 0.0}],
            "text_layer": False,
        },
    ]
    for case in case_data:
        case["subtotal"] = round(sum(row["line_total"] for row in case["line_items"]), 2)
        case["tax_amount"] = round(sum(row["line_total"] * row["tax_rate"] / 100.0 for row in case["line_items"]), 2)
        case["total"] = round(case["subtotal"] + case["tax_amount"], 2)

    po_rows = [
        PurchaseOrder("PO-NW-1001", "V-NW-001", "INR", [POLine("NWC-CPU", "Server processor hardware", 50, 2000), POLine("NWC-SSD", "Enterprise SSD equipment", 40, 2500), POLine("NWC-RAM", "ECC RAM hardware", 100, 800)], 280000),
        PurchaseOrder("PO-NW-1002", "V-NW-001", "INR", [POLine("NWC-RTR", "Network router equipment", 5, 20000)], 100000),
        PurchaseOrder("PO-NW-1003", "V-NW-001", "INR", [POLine("NWC-NIC", "Network interface hardware", 120, 1000)], 120000),
        PurchaseOrder("PO-NW-1004", "V-NW-001", "INR", [POLine("NWC-SRV", "Rack server equipment", 20, 5000)], 100000),
        PurchaseOrder("PO-HC-2001", "V-HC-001", "USD", [POLine("HC-SAAS-A", "Annual SaaS software subscription", 1, 6000)], 6000),
    ]
    grn_rows = [
        GoodsReceipt("PO-NW-1001", [{"sku": "NWC-CPU", "qty_received": 50}, {"sku": "NWC-SSD", "qty_received": 40}, {"sku": "NWC-RAM", "qty_received": 100}]),
        GoodsReceipt("PO-NW-1002", [{"sku": "NWC-RTR", "qty_received": 5}]),
        GoodsReceipt("PO-NW-1003", [{"sku": "NWC-NIC", "qty_received": 100}]),
        GoodsReceipt("PO-NW-1004", [{"sku": "NWC-SRV", "qty_received": 20}]),
        GoodsReceipt("PO-HC-2001", [{"sku": "HC-SAAS-A", "qty_received": 1}]),
    ]
    po_ledger = {row.po_number: asdict(row) for row in po_rows}
    grn_ledger = {row.po_number: asdict(row) for row in grn_rows}
    (output / "po_ledger.json").write_text(json.dumps(po_ledger, indent=2), encoding="utf-8")
    (output / "grn_ledger.json").write_text(json.dumps(grn_ledger, indent=2), encoding="utf-8")
    samples: list[dict[str, Any]] = []
    for case in case_data:
        path = output / f"{case['id'].lower()}_invoice.pdf"
        raw_text = _write_invoice_pdf(path, case, scanned=case["id"] == "S5")
        ledger = {
            "vendors": {
                "V-NW-001": {"bank_account": northwind_bank},
                "V-HC-001": {"bank_account": helios_bank},
            },
            "posted_invoices": ([{"vendor_id": "V-NW-001", "invoice_no": "NW-2026-0998"}] if case["id"] == "S4" else []),
        }
        sample = {
            "id": case["id"],
            "title": case["title"],
            "expected_route": case["expected_route"],
            "expected_codes": case["expected_codes"],
            "pdf_path": str(path),
            "po_number": case["po_number"],
            "ledger": ledger,
            "po_ledger": po_ledger,
            "grn_ledger": grn_ledger,
        }
        if case["id"] == "S5":
            sample["raw_text"] = raw_text
        samples.append(sample)
    return samples
