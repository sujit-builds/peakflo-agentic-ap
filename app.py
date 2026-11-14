"""Streamlit UI for the zero-network agentic AP prototype."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import streamlit as st

from peakflo_agent import AgentRun, run_agent_safe
from peakflo_agent.agent import PRICE_TOLERANCE_ABS, PRICE_TOLERANCE_PCT, TAX_TOLERANCE_ABS
from peakflo_agent.samples import build_samples


APP_DIR = Path(__file__).resolve().parent


def _serialise(run: AgentRun) -> dict[str, Any]:
    return {
        "invoice": asdict(run.invoice) if run.invoice else None,
        "match": asdict(run.match) if run.match else None,
        "discrepancies": [asdict(row) for row in run.discrepancies],
        "judgment": asdict(run.judgment),
        "steps": [asdict(row) for row in run.steps],
        "report_rows": run.report_rows,
        "report_markdown": run.report_markdown,
    }


def _csv_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _timeline(run: AgentRun, expanded: bool) -> None:
    st.subheader("Agent execution")
    for step in run.steps:
        icon = "✓" if step.status == "completed" else "!"
        st.markdown(f"**{icon} {step.step_no}. {step.name}** · {step.agent} · `{step.status}`")
        if expanded:
            with st.expander(f"step {step.step_no} · technical detail"):
                st.caption(
                    f"{step.summary} · {step.duration_ms} ms · {step.tokens} tokens · payload `{step.payload_digest}`"
                )


def _invoice_panel(run: AgentRun) -> None:
    if not run.invoice:
        st.error("No invoice was produced. See the audit trail for the safe failure record.")
        return
    invoice = run.invoice
    st.subheader("Extracted invoice")
    st.dataframe(
        [
            {"Field": "Vendor", "Value": invoice.vendor_name},
            {"Field": "Vendor ID", "Value": invoice.vendor_id},
            {"Field": "Invoice", "Value": invoice.invoice_no},
            {"Field": "Date", "Value": invoice.invoice_date},
            {"Field": "PO", "Value": invoice.po_number},
            {"Field": "Currency", "Value": invoice.currency},
            {"Field": "Subtotal", "Value": f"{invoice.subtotal:,.2f}"},
            {"Field": "Tax", "Value": f"{invoice.tax_amount:,.2f}"},
            {"Field": "Total", "Value": f"{invoice.total:,.2f}"},
            {"Field": "Input mode", "Value": "Text layer" if invoice.text_layer else "Mock vision OCR"},
        ],
        width="stretch",
        hide_index=True,
    )
    if invoice.line_items:
        st.dataframe([asdict(row) for row in invoice.line_items], width="stretch", hide_index=True)


def _match_panel(run: AgentRun) -> None:
    if not run.match:
        return
    st.subheader("Three-way match")
    st.caption(f"PO {run.match.po_number or 'missing'} · status: {run.match.status}")
    rows = []
    for row in run.match.line_matches:
        item = dict(row)
        item["price_check"] = "🟢 within" if abs(float(row["price_delta_pct"])) <= 2.0 else "🔴 variance"
        item["receipt_check"] = "🟢 matched" if abs(float(row["qty_delta"])) < 0.001 else ("🔴 over" if float(row["qty_delta"]) > 0 else "🟠 under")
        rows.append(item)
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    if run.match.unmatched_invoice_lines:
        st.warning(f"{len(run.match.unmatched_invoice_lines)} invoice line(s) unmatched")


def _discrepancy_panel(run: AgentRun) -> None:
    st.subheader("Exceptions and controls")
    if not run.discrepancies:
        st.success("No discrepancies detected. All configured controls passed.")
    for row in run.discrepancies:
        message = f"**{row.code}** · {row.message} · impact {row.amount_impact:,.2f}"
        if row.severity == "blocking":
            st.error(message)
        elif row.severity == "warning":
            st.warning(message)
        else:
            st.info(message)


def _verdict(run: AgentRun) -> None:
    route = run.judgment.route
    palette = {"auto_post": ("#DCFCE7", "#166534"), "human_review": ("#FEF3C7", "#92400E"), "block": ("#FEE2E2", "#991B1B")}
    background, foreground = palette[route]
    st.markdown(
        f'<div style="display:inline-block;padding:.55rem .9rem;border-radius:.6rem;background:{background};color:{foreground};font-weight:700;font-size:1.15rem">{route.replace("_", " ").upper()} · {run.judgment.confidence:.0%}</div>',
        unsafe_allow_html=True,
    )
    st.write(run.judgment.rationale)
    st.caption(run.judgment.recommended_action)


def _run_sample(sample: dict[str, Any]) -> AgentRun:
    return run_agent_safe(sample["pdf_path"], sample["ledger"], sample["po_ledger"], sample["grn_ledger"])


def main() -> None:
    st.set_page_config(page_title="Peakflo · Agentic AP prototype", layout="wide")
    samples = build_samples(APP_DIR / ".demo_out")
    st.sidebar.title("Peakflo prototype")
    st.sidebar.caption("Agentic AP: invoice → PO → GRN → decision")
    show_log = st.sidebar.toggle("Step-by-step log", value=True)
    run_all = st.sidebar.button("Run all samples", type="primary", use_container_width=True)
    st.sidebar.caption(f"{len(samples)} samples")
    st.sidebar.caption(
        f"Tolerances · ±{PRICE_TOLERANCE_PCT:.1f}% price / {PRICE_TOLERANCE_ABS:,.0f} abs / {TAX_TOLERANCE_ABS:.2f} tax"
    )
    if run_all:
        all_runs = [(sample, _run_sample(sample)) for sample in samples]
        st.session_state["all_runs"] = all_runs
        st.session_state["run"] = all_runs[-1][1]
    if st.session_state.get("all_runs"):
        st.sidebar.dataframe(
            [{"ID": sample["id"], "Route": run.judgment.route, "Confidence": f"{run.judgment.confidence:.0%}"} for sample, run in st.session_state["all_runs"]],
            hide_index=True,
            width="stretch",
        )

    process_tab, report_tab, audit_tab, map_tab = st.tabs(
        ["Process invoice", "Reconciliation report", "Audit trail", "How this maps to Peakflo"]
    )
    with process_tab:
        st.title("Agentic accounts payable")
        st.caption("A deterministic, zero-network demonstration of invoice understanding, three-way matching, policy controls, judgment, and posting preparation.")
        summary_strip = st.container()
        left, right = st.columns([1, 1])
        with left:
            selected_label = st.selectbox("Pick a sample", [f"{row['id']} · {row['title']}" for row in samples])
        with right:
            uploaded = st.file_uploader("Or upload a PDF", type=["pdf"])
        if st.button("Run agent", type="primary"):
            selected = samples[[row["id"] for row in samples].index(selected_label.split(" · ", 1)[0])]
            if uploaded is not None:
                base_ledger = {"vendors": selected["ledger"]["vendors"], "posted_invoices": []}
                run = run_agent_safe(uploaded.getvalue(), base_ledger, selected["po_ledger"], selected["grn_ledger"])
            else:
                run = _run_sample(selected)
            st.session_state["run"] = run
        run = st.session_state.get("run")
        if run:
            blocking = [row for row in run.discrepancies if row.severity == "blocking"]
            amount_at_risk = sum(row.amount_impact for row in blocking)
            currency = run.invoice.currency if run.invoice else ""
            with summary_strip:
                decision_col, confidence_col, discrepancy_col, risk_col = st.columns(4)
                decision_col.metric(
                    "Decision",
                    {"auto_post": "Auto-post", "human_review": "Human review", "block": "Blocked"}.get(
                        run.judgment.route, run.judgment.route
                    ),
                )
                confidence_col.metric("Confidence", f"{run.judgment.confidence:.0%}")
                discrepancy_col.metric(
                    "Discrepancies",
                    len(run.discrepancies),
                    delta=len(blocking) or None,
                    delta_color="inverse",
                )
                risk_col.metric("Amount at risk", f"{currency} {amount_at_risk:,.2f}".strip())
            _verdict(run)
            _timeline(run, show_log)
            first, second = st.columns([1, 1])
            with first:
                _invoice_panel(run)
            with second:
                _match_panel(run)
            _discrepancy_panel(run)
        else:
            st.info("Choose a fixture or upload a PDF, then run the agent.")

    with report_tab:
        run = st.session_state.get("run")
        if run:
            st.markdown(run.report_markdown)
            st.dataframe(run.report_rows, width="stretch", hide_index=True)
            st.download_button("Download report CSV", _csv_text(run.report_rows), "reconciliation_report.csv", "text/csv")
        else:
            st.info("Run an invoice to build its reconciliation report.")

    with audit_tab:
        run = st.session_state.get("run")
        if run:
            st.subheader("Immutable-style execution record")
            st.dataframe([asdict(row) for row in run.steps], width="stretch", hide_index=True)
            st.download_button("Download full run JSON", json.dumps(_serialise(run), indent=2), "agent_run.json", "application/json")
        else:
            st.info("Run an invoice to populate the audit trail.")

    with map_tab:
        st.header("How the prototype maps to Peakflo")
        st.table(
            [
                {"Agent step": "Ingest + extract", "Peakflo capability": "Template library and document understanding"},
                {"Agent step": "Validate + PO match", "Peakflo capability": "ERP/browser agents and three-way matching"},
                {"Agent step": "Detect", "Peakflo capability": "Policy-driven exception automation"},
                {"Agent step": "Judge", "Peakflo capability": "LLM-as-judge self-evaluation"},
                {"Agent step": "Report", "Peakflo capability": "200+ ERP posting preparation"},
                {"Agent step": "Follow-up", "Peakflo capability": "Voice follow-up (mapping only in this demo)"},
            ]
        )
        st.subheader("Explicitly mocked")
        st.markdown(
            "- LLM extraction, vision OCR, GL classification, explanations, and judge scoring are deterministic local code.\n"
            "- PO, GRN, vendor-master, and posted-invoice records are generated JSON fixtures.\n"
            "- ERP/browser posting, bank validation, supplier outreach, and voice follow-up are represented but not executed.\n"
            "- Token counts are deterministic estimates; durations are local wall-clock measurements."
        )


if __name__ == "__main__":
    main()
