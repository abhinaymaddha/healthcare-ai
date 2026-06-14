# Architecture — Healthcare AI Patient Symptom Triage Concierge

This document is the top-level entry point for the system architecture. It describes design philosophy, use case scope, and links to detailed architecture documents.

---

## What we built

A multi-agent, multi-turn **Patient Symptom Triage Concierge** for telehealth. A patient sends a message; the system classifies it, applies safety and privacy guardrails, conducts the appropriate multi-step workflow, and returns a compliant, empathetic response — all within a persistent conversation session.

**Three use cases:**
- **UC1 — Symptom Check:** acuity classification (Low/Medium/High), safe reply generation, emergency escalation, appointment offer
- **UC2 — Prescription Refill:** medication extraction, confirmation, prescription history check, order creation or appointment offer
- **UC3 — Appointment Booking:** preference collection, doctor availability, slot selection, booking

---

## Core design principles

| Principle | How it's applied |
|---|---|
| LLMs only where irreplaceable | Regex + local NLI model handle guardrails; small LLM for extraction, classification and summarization; medium-size LLM for clinical response generation |
| PHI de-identification, not blocking | Sensitive fields are hashed before reaching the LLM; only first name is restored in the response |
| Provider-agnostic LLM layer | All LLM calls go through a Pydantic abstraction; switching models = one config change |
| Stateful multi-turn sessions | LangGraph `StateGraph` with `MemorySaver` (demo) / `RedisSaver` (production) |
| Fail safe | Any unhandled error defaults to a blocked response; never silently passes |
| Cost transparency | Every API call metered; cost reported per request |

---

## Architecture documents

### [HIGH_LEVEL_ARCHITECTURE.md](HIGH_LEVEL_ARCHITECTURE.md)
Business and compliance overview — written for clinical leadership, compliance officers, and client stakeholders:
- What each patient workflow does and what outcomes it produces
- How patient privacy is protected (PHI de-identification, conceptual)
- How emergency situations are detected and escalated
- What the compliance layer enforces and why
- Security controls in plain language
- Cost model and recommended pilot approach
- Explicit list of what the system does not do

### [LOW_LEVEL_ARCHITECTURE.md](LOW_LEVEL_ARCHITECTURE.md)
Infrastructure, data, and implementation reference — written for engineers and technical reviewers:
- Production infrastructure diagram: API gateway, FastAPI cluster, LangGraph workers, ML servers, Redis, PostgreSQL
- PostgreSQL table schemas (patient_sessions, audit_log, phi_lookup_table, prescriptions, appointments, escalation_log)
- Redis key patterns: LangGraph checkpointing, rate limiting, inference cache, HITL queue
- Service responsibilities and scalability model
- HIPAA technical controls and monitoring metrics
- LangGraph graph structure (15 nodes across main graph + emergency companion subgraph, 3 UC subgraphs, routing logic)
- TriageState schema (all 39 fields with annotations)
- Node-by-node responsibilities and UC2/UC3 state machines
- Turn-by-turn data flow traces with actual state changes
- PHI de-identification pipeline and re-identification rules
- LLM abstraction layer and session lifecycle
- Evolution table: demo vs. production for every component

---

## Technology decisions at a glance

| Component | Technology | Reason |
|---|---|---|
| Graph orchestration | LangGraph | Stateful multi-turn, conditional routing, HITL interrupt, subgraph composition |
| LLM (small) | Small LLM via OpenRouter | Intent confirmation, clarification, extraction, summarization — fast and low-cost |
| LLM (medium) | Medium-size LLM via OpenRouter | Clinical response generation (UC1) — higher quality where patient safety depends on nuance |
| LLM SDK | openai (AsyncOpenAI) | OpenRouter is OpenAI-compatible; same code works for any provider |
| Local classifier | `cross-encoder/nli-deberta-v3-xsmall` | Zero-cost NLI for health relevance, emergency signals, intent classification |
| NER | spaCy `en_core_web_md` | PERSON/DATE/GPE entity extraction for PHI detection |
| Session state (demo) | LangGraph MemorySaver | In-process, zero dependencies for demo |
| Session state (prod) | LangGraph RedisSaver | Persistent, horizontally scalable |
| Backend | FastAPI | Async, auto OpenAPI docs, Pydantic validation |
| Frontend | Chainlit | Python-native ChatGPT-style chat UI |

---

## Cost model

| Scenario | LLM calls | Estimated cost |
|---|---|---|
| Symptom check, happy path | 1 medium-size LLM | ~$0.007 |
| Prescription refill (extract + check) | 1 small LLM | ~$0.0015 |
| Refill → appointment (with summarization) | 1 small + 1 medium-size LLM | ~$0.009 |
| Mixed-intent clarification + symptom check | 1–3 small + 1 medium-size LLM | ~$0.009–0.012 |
| Emergency short-circuit | 0 | $0.00 |
| Non-health block | 0 | $0.00 |
| **Average (estimated)** | ~1.2–1.5 | **~$0.005–0.008** |

**Testing implementation:** small LLM = Claude Haiku 4.5, medium-size LLM = Claude Sonnet 4.6. A large LLM (e.g., Claude Opus 4.8) is not currently used but is provisioned in the model tier for future high-complexity tasks.

Using a large LLM for everything would cost ~$0.025–0.050/request — approximately 5–10× more expensive than the two-tier approach.

---

## Safety and compliance

Every response passes through two deterministic checks before reaching the patient:

1. **Disclaimer enforcement:** UC1 responses must contain the mandatory disclaimer. If missing, it is appended.
2. **Violation detection:** Regex patterns flag diagnosis language ("you have X") and prescription advice ("take 500mg"). Any match replaces the response with a safe fallback.

The LLM system prompt is written to prevent violations; the safety layer is a belt-and-suspenders guarantee.

---

## What's mocked (demo scope)

The following are simulated with mock data and would be replaced with real integrations in production:

- `tools/patient.py` — patient identity and appointment history lookup
- `tools/prescription.py` — prescription database and order creation
- `tools/appointment.py` — doctor availability and booking API
- `tools/emergency.py` — emergency dispatch and HITL notification

Session state, PHI lookup tables, and all logs are in-memory. See [HIGH_LEVEL_ARCHITECTURE.md](HIGH_LEVEL_ARCHITECTURE.md) for the production data persistence design.

---

## Future scope

See [FUTURE_SCOPE.md](FUTURE_SCOPE.md) for planned improvements across five areas:

1. **Fine-grained clinical triage classification** — duration, symptom co-occurrence, progression, and risk factors as explicit acuity inputs
2. **Improved diagnosis boundary enforcement** — LLM-as-judge output checking; broader NLI coverage of indirect diagnosis-seeking
3. **Message traceability and session logging** — message IDs, sender types, and source references on all extracted clinical data
4. **Adaptive response tone** — health literacy matching and non-English routing
5. **Evaluation and continuous improvement** — CI-integrated eval, LLM-as-judge scoring, failure-to-test-case pipeline
