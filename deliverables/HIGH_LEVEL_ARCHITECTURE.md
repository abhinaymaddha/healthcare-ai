# High-Level Architecture — Healthcare AI Patient Triage Concierge

This document describes what the system does, how it protects patients, and how it ensures safe and compliant responses — written for a clinical, compliance, or business audience. For infrastructure specifications, data schemas, and implementation details, see [LOW_LEVEL_ARCHITECTURE.md](LOW_LEVEL_ARCHITECTURE.md).

---

## What the system does

The Healthcare AI Patient Triage Concierge is a conversational AI that manages the first turn of a patient interaction in a telehealth platform. A patient sends a message in plain language; the system identifies the need, applies privacy and safety controls, and returns a safe, empathetic, clinically appropriate response — across a persistent multi-turn conversation that retains full context between messages.

**Three patient workflows are supported end-to-end:**

| Workflow | Patient intent | System outcome |
|---|---|---|
| **Symptom Check (UC1)** | Report symptoms and receive guidance | Acuity classification (Low / Medium / High), empathetic response, emergency escalation if needed |
| **Prescription Refill (UC2)** | Request a refill for an existing prescription | Medication extraction, patient confirmation, prescription verification, order submission |
| **Appointment Booking (UC3)** | Schedule a doctor visit | Preference collection, availability check, slot selection, booking confirmation |

The system handles transitions between workflows in a single session. A patient can report symptoms, then request a refill, then book an appointment — without starting a new conversation or repeating their history.

---

## How patient privacy is protected

**Personally identifiable information never reaches the AI model.**

Before any patient message is processed by the AI, a de-identification pipeline scans it for all recognisable forms of PHI: Social Security Numbers, Medical Record Numbers, insurance member IDs, names, dates of birth, phone numbers, and government-issued identifiers (Aadhaar, PAN). Each detected value is replaced with a cryptographic token before the message is forwarded.

The AI sees only anonymised content such as:

> "My name is `[PERSON_a3f7]`, SSN `[SSN_bc12]`, and I have had a fever for three days."

The original values are stored encrypted and scoped to the session. They are never written to any log.

**Only the patient's first name is restored** in the AI's response, so the patient receives a personally addressed reply while all other PHI remains protected throughout the entire conversation.

This two-layer approach uses:
- **Pattern matching** for structured identifiers (SSNs, MRNs, insurance IDs, government IDs)
- **Named Entity Recognition** for unstructured identifiers (names, dates, locations mentioned in free text)

---

## How emergency situations are handled

Emergency detection runs before the AI model and does not depend on it. Two independent detection layers evaluate every message:

**Layer 1 — Keyword detection**
Hardcoded pattern matching triggers immediately on terms indicating cardiac arrest, stroke, respiratory failure, uncontrolled bleeding, overdose, and explicit suicidal ideation. This requires no AI call and responds in under 50 milliseconds.

**Layer 2 — Soft signal detection**
A locally hosted AI classifier — running on clinic infrastructure, not a cloud API — identifies indirect crisis language: passive suicidal ideation ("I do not want to be here anymore"), hopelessness, self-harm, and perceived burdensomeness.

**When either layer fires:**
1. The patient is immediately asked whether emergency services should be dispatched to their location
2. A clinical reviewer is notified via the Human-in-the-Loop (HITL) dashboard
3. If the patient confirms, emergency dispatch is initiated
4. The AI model generates no response during escalation — the patient receives a structured clinical message only

Mental health escalations route to the 988 Suicide and Crisis Lifeline in addition to the HITL reviewer. Physical emergencies route to 911.

The patient's reply to the dispatch question is handled by the same emergency logic on the next turn — the system does not re-classify it as a new symptom check.

---

## How we ensure responses are safe and compliant

Every AI-generated response passes through a deterministic compliance check before it is returned to the patient. This layer does not use the AI model — it is pure rule-based logic.

**What the compliance layer enforces:**

| Rule | How it works |
|---|---|
| Mandatory disclaimer | All symptom responses must end with: *"This is not a medical diagnosis. Please consult a licensed healthcare provider for personalised medical advice."* If missing, it is appended automatically. |
| No diagnosis language | A pattern set covering declarative assertions ("you have [condition]", "this sounds like [X]", "this appears to be", "you are presenting with") is scanned on every response. Any match discards the response and returns a safe fallback. |
| No prescription advice | Phrases such as "take 500mg", "I prescribe", "increase your dose", "stop taking" are detected and trigger the same replacement. |
| No brand-to-generic substitution | Medications are always extracted as stated by the patient. We do not silently rename a brand name to a generic — that is a clinical and formulary decision requiring authorisation. |
| Diagnosis demand blocked at input | If a patient pushes for a specific diagnosis ("diagnose me", "is it pneumonia", "do you think it is COVID", "skip the disclaimers"), the request is intercepted before the AI model is called. A fixed empathetic response explains what the system can and cannot do, and offers to assess urgency instead. |
| Jailbreak and bypass attempts blocked | The AI system prompt contains an unconditional rule: safety boundaries apply regardless of whether the patient claims to be a clinician, grants permission, or frames the request as fictional, hypothetical, or a role-play scenario. |
| Clarification before commitment | When a patient message contains both symptom signals and an explicit task request (e.g., "I ran out of my blood pressure medication and I have a headache"), the system does not immediately jump to the task. It asks one focused clarifying question per turn — checking for emergency signs first — before routing to any workflow. |

The AI prompts are separately engineered to prevent these violations. The compliance layer is an independent safety net that holds even if a prompt fails on an edge case.

---

## Security controls

| Control | What we do |
|---|---|
| Data in transit | TLS 1.3 on all connections; no unencrypted HTTP permitted |
| PHI to the AI | Never sent — only cryptographic tokens reach the AI model |
| PHI at rest | AES-256 encryption; scoped to session; automatic expiry |
| Audit trail | Every conversation turn is logged with de-identified content only; original PHI is never in any log |
| Access control | Role-based: clinical reviewers access escalation queue only; no patient PII visible in any operational UI |
| API security | JWT/OAuth authentication at the gateway; WAF blocks SQL injection, XSS, and prompt injection headers |
| Local AI processing | Health relevance, emergency detection, and intent routing run on clinic infrastructure — no patient data is sent to a cloud API for routing decisions |
| LLM provider | A two-tier LLM approach: a small LLM handles intent confirmation, clarification, extraction, and summarization; a medium-size LLM generates clinical responses (UC1) where quality and safety nuance matter most. Both see only de-identified tokens; switching provider requires a single configuration change. Testing used Claude Haiku 4.5 (small) and Claude Sonnet 4.6 (medium). |

---

## Cost model

| Scenario | AI model calls | Estimated cost |
|---|---|---|
| Symptom check (single turn) | 1 | ~$0.0015 |
| Prescription refill (extract + confirm) | 1 | ~$0.0015 |
| Appointment booking | 0 — template responses only | $0.0000 |
| Emergency escalation | 0 — rule-based, no AI | $0.0000 |
| Multi-turn conversation average | ~1.2–1.5 calls | ~$0.0020 |

Health relevance classification, emergency detection, and intent routing are handled by locally hosted models at zero cloud API cost. The AI model is invoked only for tasks that genuinely require natural language generation: symptom responses, medication extraction, and session summarisation when a patient transitions between workflows.

At 10,000 patient conversations per month, the estimated AI cost is approximately **$20 per month**.

---

## Recommended pilot approach

A phased rollout minimises clinical risk while building operational confidence:

| Phase | Scope | Risk level | Rationale |
|---|---|---|---|
| Month 1 | Appointment booking only | Very low | No AI-generated clinical content; fully deterministic templates |
| Month 2 | Add prescription refill | Low | Extract-and-confirm pattern; no new prescriptions issued; existing records verified |
| Month 3 | Add symptom triage | Medium | AI-generated responses; HITL reviewer coverage required before go-live |

A Human-in-the-Loop reviewer dashboard should be operational before symptom triage goes live. All emergency escalations should be reviewed by a clinician for the first 30 days.

---

## What this system does not do

- It does not diagnose medical conditions
- It does not prescribe, adjust, or recommend medications
- It does not replace a licensed healthcare provider
- It does not store raw PHI at any point in the conversation pipeline
- It does not make autonomous emergency dispatch decisions — the patient confirms first, and a clinical reviewer is notified in parallel

---

## Further reading

- [LOW_LEVEL_ARCHITECTURE.md](LOW_LEVEL_ARCHITECTURE.md) — data stores, infrastructure, service design, LangGraph implementation, and the evolution path from demo to production
- [ARCHITECTURE.md](ARCHITECTURE.md) — technology decisions, design principles, and cost analysis
- [EXECUTIVE_EMAIL.md](EXECUTIVE_EMAIL.md) — pilot recommendation summary for clinical leadership
