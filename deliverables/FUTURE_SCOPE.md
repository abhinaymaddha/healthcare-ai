# Future Scope — Planned Improvements

This document captures planned improvements that are out of scope for the current pilot but should be addressed before or during a production rollout. Items are grouped by theme. Each entry describes the problem, the risk it carries today, and the direction for resolution.

---

## 1. Fine-grained clinical triage classification

### Problem
The current acuity classifier (Low / Medium / High) is driven by a DeBERTa NLI model with general symptom-severity labels. It classifies each message in isolation and does not account for several clinically important signals:

- **Duration** — a symptom that has persisted for 48+ hours carries higher risk than one that started an hour ago, even if the symptom words are identical. A patient who says "I have had a headache and nausea for the last two days" receives the same Low-acuity treatment as one who says "I have a mild headache right now."
- **Symptom co-occurrence** — multiple concurrent symptoms (e.g., headache + nausea + fever) may individually classify as Low but together suggest a higher-acuity presentation.
- **Symptom progression** — a patient reporting symptoms that are "getting worse" should escalate relative to a stable presentation with identical words.
- **Age, comorbidities, and risk factors** — not currently captured. A 65-year-old describing chest tightness and fatigue is a different risk profile than a 25-year-old with the same words.
- **Prior-turn context** — if a patient's acuity was classified as Medium on turn 1 and they describe worsening on turn 2, the system should escalate, not re-classify from scratch.

### Risk today
The system may under-triage. A Low acuity ruling leads to "monitor at home" guidance — which is clinically appropriate for a mild tension headache but inappropriate for a 2-day persistent headache with nausea, which can be an early presentation of meningitis, hypertensive crisis, or inner ear pathology. The mandatory disclaimer does not fully mitigate this risk; it shifts liability but does not prevent harm.

### Direction for improvement
- Introduce a structured **clinical feature extraction** step before acuity classification: parse duration, onset (sudden vs. gradual), trajectory (improving/stable/worsening), and symptom count from the patient message.
- Use extracted features as explicit inputs to the acuity model rather than letting the NLI model infer them from raw text.
- Add a rule layer on top of the NLI model: duration ≥ 48h AND symptom count ≥ 2 AND acuity = Low → bump to Medium. Rules encode clinical conservatism; the NLI model handles the open-ended cases.
- In multi-turn conversations, carry forward the highest acuity seen so far as a floor — never lower acuity between turns unless the patient explicitly reports improvement.
- Evaluate against a clinician-labeled dataset with known ground-truth acuity ratings.

---

## 2. Improved diagnosis boundary enforcement

### Problem
The current approach to preventing diagnosis language is two-layer:

1. **Input-side:** a keyword + NLI detector intercepts explicit diagnosis demands ("diagnose me", "tell me what I have") before the LLM is called.
2. **Output-side:** regex patterns scan the generated response for diagnostic assertion phrases.

Both layers have known limitations:

- The keyword list for input detection is enumerated — it can be bypassed by phrasings not on the list.
- The output regex catches structural patterns but is not semantically aware. A response that implies a diagnosis without using a flagged phrase ("based on what you've described, this presentation is classic for migraine") could pass undetected.
- Neither layer evaluates **clinical appropriateness** of the response as a whole — only the presence or absence of specific forbidden constructs.

### Direction for improvement
- Add an **LLM-as-judge** evaluation step for UC1 responses: a second, fast LLM call with a strict binary prompt ("Does this response assert or strongly imply a specific diagnosis? Yes/No") to catch semantic violations that regex misses.
- Extend the input-side NLI classifier with a broader set of labels covering indirect diagnosis-seeking framing (e.g., "patient is asking the AI to confirm a self-diagnosis").
- Periodically review production responses flagged by the output regex to identify recurring bypass patterns and update the keyword list accordingly.

---

## 3. Message traceability and session logging

### Problem
Extracted clinical data (medications in UC2, symptoms in UC1, appointment details in UC3) has no traceable link back to the specific patient message it was derived from. If a prescription refill is submitted based on medication data extracted from message 3 of a session, there is no record connecting the order to that message.

This is a compliance gap: HIPAA and general clinical audit requirements call for a complete chain of evidence from patient statement to clinical action.

### Direction for improvement
- Assign a **message ID** to every patient message and every system response at the time of receipt/generation.
- Log message IDs in a `message_log` table with fields: `session_id`, `message_id`, `turn_number`, `sender_type` (patient / system / clinician), `de_identified_content`, `timestamp`.
- Propagate `source_message_id` into all extracted data structures (medications list, symptom record, appointment request) so every clinical data point is traceable to the turn it was stated.
- Surface `message_id` references in the audit log and in HITL reviewer views.

---

## 4. Adaptive response tone and health literacy matching

### Problem
All patients currently receive the same response style regardless of how they communicate. A patient who writes in short plain sentences and a clinician who uses medical terminology both receive identically structured responses.

### Direction for improvement
- Infer a rough **health literacy signal** from the patient's own message (vocabulary complexity, sentence length, use of medical terms) and pass it as a parameter to the UC1 prompt.
- Adjust response vocabulary and sentence complexity accordingly: avoid jargon for plain-language writers; use clinical terms where appropriate for medically literate patients.
- Detect preferred language (non-English inputs) and route to a translation-aware response path.

---

## 5. Evaluation and continuous improvement infrastructure

### Problem
The current eval suite (262 test cases) is run manually against a live server and produces a static report. There is no mechanism to detect regressions when prompts, models, or routing logic change, and no systematic way to incorporate real production failures into the test suite.

### Direction for improvement
- Integrate the eval suite into CI: run `eval/evaluate.py` automatically on every pull request against a local test server; fail the build if pass rate drops below a configurable threshold.
- Add **LLM-as-judge scoring** for response quality dimensions not captured by string matching: empathy, clinical appropriateness, clarity, and correct disclaimer placement.
- Implement a **failure logging pipeline**: production responses that trigger compliance violations or HITL escalations are automatically anonymised, de-identified, and added as candidate test cases for human review.
- Build an **acuity ground-truth dataset**: have clinical reviewers label a sample of real session transcripts with correct acuity, then use this to measure and improve the NLI classifier's calibration.
