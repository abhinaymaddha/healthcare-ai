# Evaluation Results — Healthcare AI Triage Concierge

**Evaluation Date:** June 2026  
**Test Suite:** `eval/test_cases.json` (190 cases across 9 categories)  
**Server:** `python -m uvicorn main:app` (FastAPI + LangGraph, local deployment)  
**Evaluator:** `eval/evaluate.py` — automated end-to-end harness against live API

---

## Overall Results

| Metric                   | Value     |
| ------------------------ | --------- |
| **Total test cases**     | 190       |
| **Passed**               | 180       |
| **Failed**               | 10        |
| **Pass rate**            | **94.7%** |
| **Average latency**      | ~4 321 ms |
| **P50 latency (median)** | ~2 387 ms |

---

## Category Breakdown

| Category              | Passed | Total | Pass Rate | Status         |
| --------------------- | ------ | ----- | --------- | -------------- |
| **adversarial**       | 23     | 25    | 92%       | Minor failures |
| **borderline_health** | 4      | 5     | 80%       | Minor failures |
| **emergency**         | 23     | 25    | 92%       | Minor failures |
| **mixed_intent**      | 17     | 18    | 94%       | Minor failures |
| **non_health**        | 14     | 14    | 100%      | ✓              |
| **phi**               | 19     | 19    | 100%      | ✓              |
| **uc1_symptom**       | 30     | 33    | 91%       | Minor failures |
| **uc2_prescription**  | 35     | 35    | 100%      | ✓              |
| **uc3_appointment**   | 15     | 16    | 94%       | Minor failures |

---

---

## Key Observations

### Strengths

- **PHI de-identification: 100%** — All 19 PHI test cases pass. No patient identifiers (SSN, DOB, names, addresses) leak into responses.
- **Non-health blocking: 100%** — All 14 off-topic requests (weather, jokes, finance, travel) are correctly blocked before reaching the LLM.
- **Prescription refill: 100%** — All 35 UC2 cases pass including multi-medication, brand/generic variations, and confirmation loops.
- **Adversarial robustness: 92%** — The system correctly handles diagnosis demands, roleplay bypasses, fictional framing, and post-session injection attempts. Only 2 failures, both due to safety scanner false positives rather than actual safety compromises.

### Known Limitations

1. **Safety scanner false positives** (affects `adversarial`, `uc1_symptom`, `emergency`): The `DIAGNOSIS_PATTERNS` regex triggers on conversational medical language that is not a diagnosis. 4 of the 10 failures are caused by this. The fix is to narrow pattern specificity or add a secondary LLM-as-judge verification pass.

2. **Thunderclap headache multi-turn escalation** (`uc1_symptom/tc209`): The guardrail re-evaluates each message independently. If a patient reveals a high-acuity symptom in turn 2 of an existing UC1 session, the system may not re-escalate because the session state already carries `current_intent: UC1`. A stateful acuity-monitoring hook on each turn would address this.

3. **Mixed intent disambiguation** (`mixed_intent/tc256`): When a message contains both a symptom and a prescription refill request, the intent router tends to favour UC2 when medication confidence is high.

---

## Test Suite Composition

| Category          | Cases | Coverage Notes                                                   |
| ----------------- | ----- | ---------------------------------------------------------------- |
| uc1_symptom       | 33    | Low / medium / high acuity; multi-turn; escalation mid-session   |
| uc2_prescription  | 35    | Single/multi drug; brand vs generic; confirmation loop           |
| uc3_appointment   | 16    | Single-turn; specialist; multi-turn slot selection               |
| emergency         | 25    | Cardiac, respiratory, stroke, overdose, mental health crisis     |
| adversarial       | 25    | Diagnosis demands, roleplay bypass, jailbreak, session injection |
| phi               | 19    | SSN, DOB, name, address, insurance ID, mixed PHI types           |
| non_health        | 14    | Sports, finance, cooking, travel, entertainment, jokes           |
| borderline_health | 5     | Diet, lifestyle, exercise, supplements                           |
| mixed_intent      | 18    | UC1+UC2, UC1+UC3, escalation redirect, multi-session             |

---

## How to Reproduce

```bash
# Start the server
cd F:/code/ey_healthcare_triage
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Run full evaluation (separate terminal)
python eval/evaluate.py --session-prefix run1

# Run a single category
python eval/evaluate.py --category adversarial --session-prefix run1

# Run a single test case
python eval/evaluate.py --id tc086 --session-prefix run1
```

Results are written to `eval/report.txt` (human-readable) and `eval/report.json` (machine-readable).
