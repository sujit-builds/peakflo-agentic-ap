"""Headless runner for all five offline AP workflow samples."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from peakflo_agent import AgentRun, run_agent_safe
from peakflo_agent.samples import build_samples


def serialise_run(run: AgentRun) -> dict[str, Any]:
    return {
        "invoice": asdict(run.invoice) if run.invoice else None,
        "match": asdict(run.match) if run.match else None,
        "discrepancies": [asdict(row) for row in run.discrepancies],
        "judgment": asdict(run.judgment),
        "steps": [asdict(row) for row in run.steps],
        "report_rows": run.report_rows,
        "report_markdown": run.report_markdown,
    }


def main() -> int:
    output = Path(__file__).resolve().parent / ".demo_out"
    samples = build_samples(output)
    results: list[dict[str, Any]] = []
    passed = 0
    print("id | route        | confidence | codes                              | total")
    print("---|--------------|------------|------------------------------------|-------------")
    for sample in samples:
        run = run_agent_safe(sample["pdf_path"], sample["ledger"], sample["po_ledger"], sample["grn_ledger"])
        codes = [row.code for row in run.discrepancies]
        expected_codes = sample["expected_codes"]
        ocr_ok = sample["id"] != "S5" or any("mock vision OCR" in step.summary for step in run.steps)
        ok = run.judgment.route == sample["expected_route"] and all(code in codes for code in expected_codes) and ocr_ok
        passed += int(ok)
        total = run.invoice.total if run.invoice else 0.0
        currency = run.invoice.currency if run.invoice else ""
        code_text = ",".join(codes) or "—"
        print(f"{sample['id']:<2} | {run.judgment.route:<12} | {run.judgment.confidence:>10.2f} | {code_text:<34} | {currency} {total:,.2f}")
        print(f"{sample['id']} {'PASS' if ok else 'FAIL'} expected route={sample['expected_route']} codes={expected_codes}")
        results.append({"sample": {key: sample[key] for key in ("id", "title", "expected_route", "expected_codes", "po_number")}, "result": serialise_run(run), "passed": ok})
    (output / "run.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"{passed}/5 as expected")
    return 0 if passed == 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())

