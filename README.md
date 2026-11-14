# Peakflo agentic AP prototype

This is a working, zero-network demonstration of an agentic accounts-payable workflow: invoice PDF → structured extraction → validation → PO/GRN three-way match → exception detection → deterministic judgment → reconciliation and posting preview.

## Run it

Use the measured project interpreter; no installation or API key is needed.

```bash
cd /root/hermes-ai-outreach/jobs/peakflo/prototype
/root/hermes-ai-outreach/jobs/peakflo/.venv/bin/python demo_run.py
/root/hermes-ai-outreach/jobs/peakflo/.venv/bin/python -m streamlit run app.py
```

The CLI generates five PDF invoices plus PO/GRN ledgers under `.demo_out/`, exercises all cases, prints expected-vs-actual results, and writes the full serialised output to `.demo_out/run.json`.

## What is implemented

- Seven numbered and audited agent steps: ingest, extract, validate, PO match, detect, judge, and report.
- Real local PDF creation and text extraction with ReportLab and pypdf.
- An image-only scanned fixture that exercises a deterministic vision-OCR path.
- Arithmetic, date, currency, duplicate, bank-change, tax, quantity, price, missing-PO, and unmatched-line controls.
- SKU matching with normalised-description fallback, GL suggestions, journal preview, JSON audit export, and CSV reconciliation export.
- A safe wrapper that records failures rather than exposing tracebacks to the UI.

## What is mocked

`MockLLM` replaces document extraction, scanned-invoice OCR, GL classification, natural-language explanation, and LLM-as-judge calls. It is deterministic and uses no network, model, model download, secret, or API key. Fake token counts are recorded to make orchestration visible. PO, GRN, vendor, and posted-invoice ledgers are local fixtures.

## What is intentionally missing

The posting journal is a preview only. There is no live ERP/browser automation, payment execution, supplier communication, voice follow-up, authentication, database, or external bank/vendor validation. Those production integrations are shown only in the Peakflo mapping tab.
