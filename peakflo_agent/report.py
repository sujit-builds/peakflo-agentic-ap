"""Reconciliation report and posting journal construction."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .llm import MockLLM
from .models import Discrepancy, Invoice, Judgment, MatchResult


def build_report(
    invoice: Invoice,
    match: MatchResult,
    discrepancies: list[Discrepancy],
    judgment: Judgment,
    llm: MockLLM,
) -> tuple[str, list[dict[str, Any]]]:
    expenses: dict[str, float] = defaultdict(float)
    coding_rows: list[dict[str, Any]] = []
    for item in invoice.line_items:
        account = llm.classify_gl(item.description)
        expenses[account] += item.line_total
        coding_rows.append(
            {
                "section": "GL coding",
                "line": item.line_no,
                "dr_cr": "",
                "account": account,
                "description": item.description,
                "debit": round(item.line_total, 2),
                "credit": 0.0,
                "currency": invoice.currency,
            }
        )
    journal_rows: list[dict[str, Any]] = []
    for account, amount in expenses.items():
        journal_rows.append(
            {
                "section": "Journal preview",
                "line": None,
                "dr_cr": "DR",
                "account": account,
                "description": f"Expense · {invoice.invoice_no}",
                "debit": round(amount, 2),
                "credit": 0.0,
                "currency": invoice.currency,
            }
        )
    if invoice.tax_amount:
        journal_rows.append(
            {
                "section": "Journal preview",
                "line": None,
                "dr_cr": "DR",
                "account": "1400 Input Tax",
                "description": f"Input tax · {invoice.invoice_no}",
                "debit": round(invoice.tax_amount, 2),
                "credit": 0.0,
                "currency": invoice.currency,
            }
        )
    journal_rows.append(
        {
            "section": "Journal preview",
            "line": None,
            "dr_cr": "CR",
            "account": "2100 Accounts Payable",
            "description": invoice.vendor_name,
            "debit": 0.0,
            "credit": round(invoice.total, 2),
            "currency": invoice.currency,
        }
    )
    codes = ", ".join(row.code for row in discrepancies) or "None"
    markdown = f"""# Reconciliation report

**Invoice:** {invoice.invoice_no}  
**Vendor:** {invoice.vendor_name} (`{invoice.vendor_id}`)  
**PO / match:** {invoice.po_number or 'Missing'} / {match.status}  
**Decision:** `{judgment.route}` at {judgment.confidence:.0%} confidence  
**Discrepancies:** {codes}

## Totals

| Measure | Amount |
|---|---:|
| Subtotal | {invoice.currency} {invoice.subtotal:,.2f} |
| Input tax | {invoice.currency} {invoice.tax_amount:,.2f} |
| Invoice total / AP credit | {invoice.currency} {invoice.total:,.2f} |

## Recommended action

{judgment.recommended_action}

## Posting journal preview

The journal debits the suggested expense accounts and input tax, then credits Accounts Payable. No ERP posting is performed by this offline demo.
"""
    return markdown, coding_rows + journal_rows
