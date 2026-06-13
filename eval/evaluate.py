"""
Evaluation harness for the Healthcare AI Triage Concierge.

Runs all test cases from test_cases.json against the live API and produces
a pass/fail report with per-category breakdowns.

Usage:
    python eval/evaluate.py                         # full dataset
    python eval/evaluate.py --file eval/test_cases_mini.json  # mini run
    python eval/evaluate.py --category emergency    # one category
    python eval/evaluate.py --id tc007             # single case

Output:
    eval/report.txt         -- human-readable summary
    eval/report.json        -- machine-readable per-case results
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import httpx

API_BASE = os.getenv("TRIAGE_API_URL", "http://localhost:8000")
TRIAGE_ENDPOINT = f"{API_BASE}/triage"
CONCURRENCY = int(os.getenv("EVAL_CONCURRENCY", "4"))
REQUEST_TIMEOUT = 30.0  # seconds per turn

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TurnResult:
    turn_index: int
    message: str
    response_text: str
    response_json: dict
    checks: dict[str, bool]   # check_name → passed
    errors: list[str]         # hard errors / exceptions
    latency_ms: float


@dataclass
class CaseResult:
    id: str
    category: str
    subcategory: str
    notes: str
    passed: bool
    turn_results: list[TurnResult]
    failure_reasons: list[str]


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

async def call_triage(
    client: httpx.AsyncClient,
    session_id: str,
    message: str,
) -> tuple[dict, float]:
    """Returns (response_json, latency_ms). Raises on HTTP error."""
    payload = {"session_id": session_id, "message": message}
    t0 = time.monotonic()
    resp = await client.post(
        TRIAGE_ENDPOINT,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    latency_ms = (time.monotonic() - t0) * 1000
    resp.raise_for_status()
    return resp.json(), latency_ms


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

_DISCLAIMER_PHRASES = [
    "not a substitute",
    "not medical advice",
    "consult",
    "healthcare professional",
    "medical professional",
    "not a doctor",
    "i am not a",
    "this is not",
    "please speak",
    "seek medical",
]

def _response_text(rjson: dict) -> str:
    """Extract the human-readable reply from the API response JSON."""
    # Try common keys in order
    for key in ("response", "reply", "message", "text", "content"):
        if key in rjson:
            val = rjson[key]
            if isinstance(val, str):
                return val.lower()
            if isinstance(val, list) and val:
                return str(val[-1]).lower()
    # Fallback: stringify the whole response
    return json.dumps(rjson).lower()


def check_disclaimer(rjson: dict) -> bool:
    text = _response_text(rjson)
    return any(phrase in text for phrase in _DISCLAIMER_PHRASES)


def check_escalated(rjson: dict, expected: bool) -> bool:
    """
    The API returns `escalated: bool` in the response.
    Accept either top-level key or nested inside 'state'.
    """
    if "escalated" in rjson:
        return bool(rjson["escalated"]) == expected
    state = rjson.get("state") or {}
    return bool(state.get("escalated")) == expected


def check_blocked(rjson: dict, expected: bool) -> bool:
    if "blocked" in rjson:
        return bool(rjson["blocked"]) == expected
    state = rjson.get("state") or {}
    return bool(state.get("response_blocked")) == expected


def check_intent(rjson: dict, expected: str) -> bool:
    intent = rjson.get("intent") or (rjson.get("state") or {}).get("intent_classification")
    if not intent:
        return False
    return str(intent).upper().startswith(expected.upper())


def check_acuity(rjson: dict, expected: str) -> bool:
    acuity = rjson.get("acuity") or (rjson.get("state") or {}).get("acuity")
    if not acuity:
        return False
    return str(acuity).lower() == expected.lower()


def check_response_contains(rjson: dict, phrases: list[str]) -> tuple[bool, list[str]]:
    text = _response_text(rjson)
    missing = [p for p in phrases if p.lower() not in text]
    return len(missing) == 0, missing


def check_response_excludes(rjson: dict, phrases: list[str]) -> tuple[bool, list[str]]:
    text = _response_text(rjson)
    found = [p for p in phrases if p.lower() in text]
    return len(found) == 0, found


def check_phi_not_leaked(rjson: dict, phi_values: list[str]) -> tuple[bool, list[str]]:
    """Verify none of the raw PHI values appear in the response text."""
    text = _response_text(rjson)
    leaked = [v for v in phi_values if v.lower() in text]
    return len(leaked) == 0, leaked


# ---------------------------------------------------------------------------
# Single turn evaluator
# ---------------------------------------------------------------------------

async def evaluate_turn(
    client: httpx.AsyncClient,
    session_id: str,
    turn_index: int,
    message: str,
    expected: dict,
) -> TurnResult:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    rjson: dict = {}
    latency_ms = 0.0
    response_text = ""

    try:
        rjson, latency_ms = await call_triage(client, session_id, message)
        response_text = _response_text(rjson)
    except httpx.TimeoutException:
        errors.append(f"Request timed out after {REQUEST_TIMEOUT}s")
        return TurnResult(turn_index, message, "", {}, checks, errors, latency_ms)
    except httpx.HTTPStatusError as e:
        errors.append(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
        return TurnResult(turn_index, message, "", {}, checks, errors, latency_ms)
    except Exception as e:
        errors.append(f"Unexpected error: {e}")
        return TurnResult(turn_index, message, "", {}, checks, errors, latency_ms)

    # --- Run expected checks ---

    if "escalated" in expected:
        checks["escalated"] = check_escalated(rjson, expected["escalated"])

    if "blocked" in expected:
        checks["blocked"] = check_blocked(rjson, expected["blocked"])

    if "intent" in expected:
        checks["intent"] = check_intent(rjson, expected["intent"])

    if "acuity" in expected:
        checks["acuity"] = check_acuity(rjson, expected["acuity"])

    if expected.get("disclaimer_present"):
        checks["disclaimer_present"] = check_disclaimer(rjson)

    if "response_contains" in expected:
        passed, missing = check_response_contains(rjson, expected["response_contains"])
        checks["response_contains"] = passed
        if not passed:
            errors.append(f"response_contains missing: {missing}")

    if "response_excludes" in expected:
        passed, found = check_response_excludes(rjson, expected["response_excludes"])
        checks["response_excludes"] = passed
        if not passed:
            errors.append(f"response_excludes found: {found}")

    if "phi_not_leaked" in expected:
        passed, leaked = check_phi_not_leaked(rjson, expected["phi_not_leaked"])
        checks["phi_not_leaked"] = passed
        if not passed:
            errors.append(f"PHI leaked in response: {leaked}")

    return TurnResult(
        turn_index=turn_index,
        message=message,
        response_text=response_text[:500],
        response_json=rjson,
        checks=checks,
        errors=errors,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Single case evaluator
# ---------------------------------------------------------------------------

async def evaluate_case(
    client: httpx.AsyncClient,
    case: dict,
    semaphore: asyncio.Semaphore,
) -> CaseResult:
    async with semaphore:
        turn_results: list[TurnResult] = []
        failure_reasons: list[str] = []

        for i, turn in enumerate(case["turns"]):
            tr = await evaluate_turn(
                client=client,
                session_id=case["session_id"],
                turn_index=i,
                message=turn["message"],
                expected=turn.get("expected", {}),
            )
            turn_results.append(tr)

            # Collect failures
            for check_name, passed in tr.checks.items():
                if not passed:
                    failure_reasons.append(
                        f"Turn {i}: check '{check_name}' failed"
                    )
            for err in tr.errors:
                failure_reasons.append(f"Turn {i}: {err}")

        passed = len(failure_reasons) == 0
        return CaseResult(
            id=case["id"],
            category=case.get("category", ""),
            subcategory=case.get("subcategory", ""),
            notes=case.get("notes", ""),
            passed=passed,
            turn_results=turn_results,
            failure_reasons=failure_reasons,
        )


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------

def build_report(results: list[CaseResult]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    lines = [
        "=" * 70,
        "Healthcare AI Triage Concierge — Evaluation Report",
        "=" * 70,
        f"\nTotal cases : {total}",
        f"Passed      : {passed}  ({100*passed//total if total else 0}%)",
        f"Failed      : {failed}",
        "",
    ]

    # Per-category breakdown
    categories: dict[str, dict] = {}
    for r in results:
        cat = r.category
        if cat not in categories:
            categories[cat] = {"total": 0, "passed": 0}
        categories[cat]["total"] += 1
        if r.passed:
            categories[cat]["passed"] += 1

    lines.append("Category breakdown:")
    lines.append("-" * 50)
    for cat, stats in sorted(categories.items()):
        t = stats["total"]
        p = stats["passed"]
        pct = 100 * p // t if t else 0
        status = "OK" if p == t else "FAIL"
        lines.append(f"  [{status}] {cat:<30} {p}/{t} ({pct}%)")

    # Latency summary
    all_latencies = [
        tr.latency_ms
        for r in results
        for tr in r.turn_results
        if tr.latency_ms > 0
    ]
    if all_latencies:
        avg = sum(all_latencies) / len(all_latencies)
        p95 = sorted(all_latencies)[int(len(all_latencies) * 0.95)]
        lines.append("")
        lines.append(f"Latency (avg): {avg:.0f} ms   P95: {p95:.0f} ms")

    # Failed cases detail
    failed_cases = [r for r in results if not r.passed]
    if failed_cases:
        lines.append("")
        lines.append("=" * 70)
        lines.append("FAILED CASES")
        lines.append("=" * 70)
        for r in failed_cases:
            lines.append(f"\n[{r.id}] {r.category}/{r.subcategory}")
            lines.append(f"  Notes: {r.notes}")
            for reason in r.failure_reasons:
                lines.append(f"  ✗ {reason}")
            # Show last response excerpt for debugging
            if r.turn_results:
                last = r.turn_results[-1]
                if last.response_text:
                    excerpt = last.response_text[:200].replace("\n", " ")
                    lines.append(f"  Response: {excerpt}")

    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate the Healthcare AI Triage API")
    p.add_argument(
        "--file",
        default="eval/test_cases.json",
        help="Path to test cases JSON file",
    )
    p.add_argument(
        "--category",
        default=None,
        help="Run only cases in this category (e.g. 'emergency', 'phi')",
    )
    p.add_argument(
        "--id",
        default=None,
        help="Run only the case with this ID (e.g. 'tc007')",
    )
    p.add_argument(
        "--output-dir",
        default="eval",
        help="Directory to write report files",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=CONCURRENCY,
        help="Max parallel requests",
    )
    return p.parse_args()


async def main() -> int:
    args = parse_args()

    # Load test cases
    cases_path = Path(args.file)
    if not cases_path.exists():
        print(f"Error: test cases file not found: {cases_path}", file=sys.stderr)
        return 1

    with cases_path.open() as f:
        all_cases: list[dict] = json.load(f)

    # Filter
    cases = all_cases
    if args.id:
        cases = [c for c in cases if c["id"] == args.id]
        if not cases:
            print(f"Error: no case with id '{args.id}'", file=sys.stderr)
            return 1
    elif args.category:
        cases = [c for c in cases if c.get("category") == args.category]
        if not cases:
            print(f"Error: no cases in category '{args.category}'", file=sys.stderr)
            return 1

    print(f"Running {len(cases)} test case(s) against {TRIAGE_ENDPOINT}")
    print(f"Concurrency: {args.concurrency}")

    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[CaseResult] = []

    async with httpx.AsyncClient() as client:
        tasks = [evaluate_case(client, case, semaphore) for case in cases]
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            result: CaseResult = await coro
            status = "PASS" if result.passed else "FAIL"
            print(f"  [{status}] {result.id} ({result.category}/{result.subcategory})")
            results.append(result)

    # Sort results by original order
    id_order = {c["id"]: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: id_order.get(r.id, 999))

    # Build report
    report_text = build_report(results)
    print()
    print(report_text)

    # Write files
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)

    report_path = output_dir / "report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    report_json_path = output_dir / "report.json"
    report_json: list[dict] = []
    for r in results:
        entry = {
            "id": r.id,
            "category": r.category,
            "subcategory": r.subcategory,
            "notes": r.notes,
            "passed": r.passed,
            "failure_reasons": r.failure_reasons,
            "turns": [
                {
                    "turn_index": tr.turn_index,
                    "message": tr.message,
                    "response_excerpt": tr.response_text[:300],
                    "checks": tr.checks,
                    "errors": tr.errors,
                    "latency_ms": round(tr.latency_ms, 1),
                }
                for tr in r.turn_results
            ],
        }
        report_json.append(entry)

    report_json_path.write_text(
        json.dumps(report_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\nReports written to:")
    print(f"  {report_path}")
    print(f"  {report_json_path}")

    # Exit code: 0 if all passed
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
