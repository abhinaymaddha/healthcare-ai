# Low-Level Architecture — Infrastructure, Data, and Implementation

This document covers the technical details: how data is stored and processed, how traffic is handled, the service infrastructure, the LangGraph implementation, and the evolution path from demo to production. For the business-facing overview, see [HIGH_LEVEL_ARCHITECTURE.md](HIGH_LEVEL_ARCHITECTURE.md).

---

## Part 1 — Production Infrastructure

### System overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Patient Clients                             │
│         Chainlit Web UI  │  Mobile App  │  EHR/EMR Integration      │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ HTTPS / TLS 1.3
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     API Gateway / Load Balancer                      │
│         Auth (JWT/OAuth)  │  Rate limiting  │  TLS termination       │
│         WAF (block SQLi, XSS, prompt injection headers)              │
└─────────────────────────┬───────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI Service Cluster                            │
│              (horizontally scaled, stateless HTTP layer)             │
│                                                                      │
│   POST /triage ──► graph.ainvoke(message, thread_id=session_id)     │
│   GET  /health                                                       │
│   GET  /session/{id}/history                                        │
└──────────┬──────────────────────────────────────────────────────────┘
           │                              │
           ▼                              ▼
┌─────────────────────┐       ┌──────────────────────────────────────┐
│   Redis Cluster     │       │       LangGraph Worker Pool           │
│                     │       │   (separate async worker processes)   │
│  Session state      │◄─────►│                                      │
│  (RedisSaver        │       │   LangGraph CompiledGraph             │
│   checkpointer)     │       │   • MemorySaver → RedisSaver         │
│                     │       │   • All 11 nodes                     │
│  Rate limiting      │       │   • 3 UC subgraphs                   │
│  (per session_id,   │       │   • Resume router pattern            │
│   per IP)           │       │   • HITL interrupt                   │
│                     │       └──────────────┬───────────────────────┘
│  Inference cache    │                      │
│  (common symptom    │            ┌─────────┼──────────┐
│   response cache)   │            │         │          │
└─────────────────────┘            ▼         ▼          ▼
                         ┌──────────────┐  ┌──────┐  ┌──────────────┐
                         │ Local ML     │  │ LLM  │  │  Tool Layer  │
                         │ Servers      │  │ Gate-│  │ (Real APIs)  │
                         │              │  │ way  │  │              │
                         │ DeBERTa NLI  │  │      │  │ Patient DB   │
                         │ (health rel, │  │ Open-│  │ Prescription │
                         │  emergency,  │  │Router│  │   System     │
                         │  intent)     │  │  ↓   │  │ Appointment  │
                         │              │  │Haiku │  │   Booking    │
                         │ spaCy NER    │  │ 4.5  │  │ Emergency    │
                         │ (PHI detect) │  │      │  │   Dispatch   │
                         └──────────────┘  └──────┘  └──────┬───────┘
                                                             │
                                                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      PostgreSQL Database                             │
│                                                                      │
│  patient_sessions   │  audit_log        │  phi_lookup_table         │
│  phi_events         │  escalation_log   │  prescriptions            │
│  appointments       │  eval_runs        │  eval_results             │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼               ▼
          ┌──────────────┐  ┌──────────┐  ┌──────────────┐
          │ HITL         │  │ Monitor- │  │ Compliance   │
          │ Reviewer     │  │ ing      │  │ Reporting    │
          │ Dashboard    │  │ Stack    │  │ Dashboard    │
          │              │  │          │  │              │
          │ Emergency    │  │Prometheus│  │ PHI access   │
          │ case review  │  │ Grafana  │  │ Audit logs   │
          │ Escalation   │  │ Alerts   │  │ Violation    │
          │ override     │  │          │  │ history      │
          └──────────────┘  └──────────┘  └──────────────┘
```

---

### Service responsibilities

#### FastAPI Service (stateless HTTP layer)
- Validates request schema (Pydantic)
- Resolves session state via Redis (does the session already exist?)
- Dispatches to LangGraph worker pool
- Returns structured JSON response
- Horizontally scalable; holds no local state

#### LangGraph Worker Pool
- Executes the compiled graph for one turn
- Reads/writes checkpoint via RedisSaver
- Calls local ML servers for NLI/NER inference
- Calls LLM gateway for Haiku completions
- Calls tool layer (real databases and APIs in production, mocks in demo)
- Can be scaled independently of the HTTP layer

#### Local ML Servers
- Serve DeBERTa NLI (`cross-encoder/nli-deberta-v3-xsmall`) via REST or gRPC
- Serve spaCy NER pipeline (`en_core_web_md`)
- GPU-backed in production for lower latency; CPU is sufficient for current load
- Separate from worker pool to allow independent scaling and model updates

#### LLM Gateway (OpenRouter)
- Routes to `anthropic/claude-haiku-4-5`
- Adds retry logic, fallback routing, and spend tracking
- Enables zero-code model swaps (change config, not code)

#### HITL Reviewer Dashboard
- Web UI for clinical reviewers to see emergency-escalated sessions
- Receives alerts from the Redis HITL queue
- Reviewers can approve emergency dispatch, mark cases resolved, or escalate to a clinician
- All reviewer actions are written to `escalation_log`

---

### Scalability model

| Load | Instances |
|---|---|
| < 100 req/min | 2 FastAPI pods, 2 LangGraph workers, 1 Redis node, 1 Postgres |
| 100–1,000 req/min | 4 FastAPI pods, 4 LangGraph workers, Redis Cluster (3 shards) |
| > 1,000 req/min | Auto-scale FastAPI + workers; ML servers on GPU; Postgres read replicas |

LangGraph workers are the bottleneck at high load — each invocation blocks for 500ms–3,000ms waiting on the Haiku API call. Horizontal scaling (more workers) is the primary lever.

---

## Part 2 — Data Architecture

### PostgreSQL — persistent storage

PostgreSQL is the system of record for everything that must survive restarts, be audited, or be queried across sessions.

#### `patient_sessions`
```sql
CREATE TABLE patient_sessions (
    session_id          UUID PRIMARY KEY,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    patient_id          VARCHAR(64),                    -- hashed patient identifier
    intents_visited     TEXT[],                         -- ["UC1", "UC2", "UC3"]
    final_intent        VARCHAR(8),
    acuity              VARCHAR(8),                     -- 'Low' | 'Medium' | 'High'
    escalated           BOOLEAN DEFAULT FALSE,
    uc1_complete        BOOLEAN DEFAULT FALSE,
    uc2_complete        BOOLEAN DEFAULT FALSE,
    uc3_complete        BOOLEAN DEFAULT FALSE,
    total_turns         INTEGER DEFAULT 0,
    total_cost_usd      NUMERIC(10, 6) DEFAULT 0,
    total_llm_calls     INTEGER DEFAULT 0
);
```

#### `audit_log` — immutable per-turn record (HIPAA requirement)
```sql
CREATE TABLE audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID REFERENCES patient_sessions(session_id),
    turn_number         INTEGER NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- PHI never stored here; de-identified content only
    de_identified_input TEXT NOT NULL,
    de_identified_output TEXT NOT NULL,
    intent              VARCHAR(8),
    acuity              VARCHAR(8),
    escalated           BOOLEAN,
    llm_calls           INTEGER,
    cost_usd            NUMERIC(10, 6),
    latency_ms          INTEGER,
    node_path           TEXT[]                          -- which nodes executed this turn
);
```

#### `phi_lookup_table` — encrypted, session-scoped, TTL-controlled
```sql
CREATE TABLE phi_lookup_table (
    session_id          UUID REFERENCES patient_sessions(session_id),
    token               VARCHAR(64) NOT NULL,           -- "[PERSON_a3f7]"
    encrypted_value     BYTEA NOT NULL,                 -- AES-256 encrypted original
    phi_type            VARCHAR(32) NOT NULL,           -- "PERSON", "SSN", "MRN", etc.
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL,           -- session TTL
    PRIMARY KEY (session_id, token)
);
```

#### `phi_events` — compliance reporting (no PHI values stored)
```sql
CREATE TABLE phi_events (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID REFERENCES patient_sessions(session_id),
    turn_number         INTEGER,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    phi_types_detected  TEXT[],                         -- ["SSN", "PERSON"]
    token_count         INTEGER
);
```

#### `escalation_log` — emergency and HITL decisions
```sql
CREATE TABLE escalation_log (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID REFERENCES patient_sessions(session_id),
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    escalation_type     VARCHAR(32),                    -- "keyword" | "nli_soft" | "both"
    signals             TEXT[],
    dispatch_requested  BOOLEAN,
    dispatch_confirmed  BOOLEAN,
    hitl_triggered      BOOLEAN DEFAULT FALSE,
    hitl_reviewer_id    VARCHAR(64),
    hitl_resolution     VARCHAR(32),                    -- "dispatched" | "declined" | "monitoring"
    resolved_at         TIMESTAMPTZ
);
```

#### `prescriptions` and `appointments` — production tool backends
```sql
CREATE TABLE prescriptions (
    id                  BIGSERIAL PRIMARY KEY,
    patient_id          VARCHAR(64) NOT NULL,
    medication_name     VARCHAR(128) NOT NULL,          -- stored as stated; no brand normalisation
    dosage              VARCHAR(64),
    prescribing_doctor  VARCHAR(64),
    issued_date         DATE,
    valid_through       DATE,
    refills_remaining   INTEGER DEFAULT 0
);

CREATE TABLE appointments (
    id                  BIGSERIAL PRIMARY KEY,
    appointment_id      UUID DEFAULT gen_random_uuid(),
    patient_id          VARCHAR(64) NOT NULL,
    doctor_id           VARCHAR(64) NOT NULL,
    scheduled_at        TIMESTAMPTZ NOT NULL,
    visit_mode          VARCHAR(16),                    -- "in_person" | "telehealth"
    reason              TEXT,
    status              VARCHAR(16) DEFAULT 'scheduled',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### Redis — ephemeral state and performance

#### LangGraph session state (RedisSaver)
```
Key pattern:  langgraph:checkpoint:{thread_id}:{checkpoint_id}
TTL:          24 hours (configurable per deployment)
Serialization: MessagePack (LangGraph default)
```
When a patient sends turn 2, the graph reads the checkpoint, restores full `TriageState`, and continues exactly where it left off — even if the request hits a different FastAPI instance.

#### Rate limiting
```
Key pattern:  ratelimit:session:{session_id}   → counter, TTL 60s
              ratelimit:ip:{client_ip}          → counter, TTL 60s
Limits:       10 requests/minute per session
              30 requests/minute per IP
```

#### Inference caching (optional)
```
Key pattern:  inference:cache:{hash_of_deidentified_message}
TTL:          1 hour
Value:        { response, intent, acuity, cost_usd }
```

#### HITL notification queue
```
Key pattern:  hitl:queue        → Redis List (LPUSH / BRPOP)
Value:        { session_id, transcript_excerpt, timestamp }
Consumer:     HITL reviewer service (long-polls the list)
```

---

### HIPAA technical controls

| Requirement | Implementation |
|---|---|
| PHI never sent to LLM | De-identification before every LLM call; only hashed tokens sent |
| PHI at rest encrypted | AES-256 on `phi_lookup_table.encrypted_value` |
| PHI in transit encrypted | TLS everywhere; no HTTP |
| Audit trail | Immutable `audit_log` table; de-identified inputs/outputs only |
| Access control | Role-based on PostgreSQL; reviewers see escalation data only |
| Data retention | PHI lookup TTL = 24h; audit logs per compliance policy |
| Breach detection | Prometheus alert on unexpected PHI event volume spikes |

---

### Monitoring and alerting

#### Key metrics (Prometheus)

| Metric | Alert threshold |
|---|---|
| `escalation_miss_rate` | Alert if > 0 in 1h window |
| `phi_deidentification_latency_p95` | Alert if > 200ms |
| `llm_call_error_rate` | Alert if > 5% in 5m window |
| `session_state_read_latency_p99` | Alert if > 50ms (Redis health) |
| `avg_cost_per_request` | Alert if > $0.005 (model regression or misuse) |
| `hitl_queue_depth` | Alert if > 10 (backlog of unreviewed emergencies) |

#### Dashboards (Grafana)
- **Operations:** request volume, latency P50/P95/P99, error rates, cost per hour
- **Safety:** escalation events per hour, HITL queue depth, resolution time
- **Compliance:** PHI detection rate, disclaimer presence rate, violation count

---

## Part 3 — Application Architecture

### LangGraph graph structure

The entire triage pipeline is a single compiled `StateGraph`. All session state lives in `TriageState`, a `TypedDict` that LangGraph persists and restores via the `MemorySaver` checkpointer (demo) or `RedisSaver` (production).

```
START
  │
  ▼
┌────────────┐
│  guardrail │  ← runs every turn
└─────┬──────┘
      │
  ┌───┴──────────────────┐
  │                      │
blocked             escalation          pass
  │                      │               │
  │              ┌───────▼──────┐        │
  │              │  emergency   │        │
  │              └───────┬──────┘        │
  │                      │               │
  └──────────────────────┼───────────────┘
                         │
                  ┌──────▼──────┐
                  │ response_   │  ◄── blocked / emergency paths end here
                  │ formatter   │
                  └──────┬──────┘
                         │
    ╔════════════════════╪══════════════════════════════╗
    ║        (pass path continues from guardrail)       ║
    ╚════════════════════╪══════════════════════════════╝
                         ▼
                ┌──────────────────┐
                │  intent_router   │
                └────────┬─────────┘
                         │
           ┌─────────────┼─────────────┐
          UC1            UC2           UC3
           │              │             │
    ┌──────▼──────┐ ┌─────▼──────┐ ┌───▼────────┐
    │ uc1 sub-    │ │ uc2 sub-   │ │ uc3 sub-   │
    │ graph       │ │ graph      │ │ graph      │
    └──────┬──────┘ └─────┬──────┘ └───┬────────┘
           │              │             │
    route_after_uc1  route_after_uc2    │
           │              │             │
      ┌────┴─────┐   ┌────┴─────┐       │
  summarize  compliance  summarize  compliance
    uc1           │   uc2           │
      │           │     │           │
      └───────► [uc3]   │           │
                  │     │           │
                  │     └───────────┘
                  │
           ┌──────▼──────────┐
           │ safety_          │
           │ compliance       │
           └──────┬──────────┘
                  │
           ┌──────▼──────────┐
           │ response_        │
           │ formatter        │
           └──────┬──────────┘
                  │
                 END
```

---

### TriageState schema

Every node reads from and writes to `TriageState`. LangGraph merges node return dicts into state automatically. The `messages` field uses the `add_messages` reducer, which appends rather than replaces.

```python
class TriageState(TypedDict):
    # Identity
    session_id: str
    patient_id: Optional[str]
    patient_first_name: Optional[str]

    # PHI de-identification
    phi_lookup_table: dict              # { "[PERSON_a3f7]": "John", "[SSN_bc12]": "123-45-..." }

    # Conversation history
    messages: Annotated[list, add_messages]

    # Intent tracking
    current_intent: Optional[str]       # "UC1" | "UC2" | "UC3"
    intent_history: list
    pending_intent: Optional[str]       # queued transition (e.g. "UC3" after UC2 no-prescription)

    # Guardrail outputs (reset and re-evaluated every turn)
    de_identified_message: Optional[str]
    is_health_related: bool
    needs_escalation: bool
    escalation_signals: list
    awaiting_911_confirmation: bool
    hitl_triggered: bool

    # UC1 — Symptom Check
    chief_complaint: Optional[str]
    acuity: Optional[str]               # "Low" | "Medium" | "High"
    uc1_complete: bool
    uc1_summary: Optional[str]

    # UC2 — Prescription Refill
    medications_extracted: list         # [{ name, dosage, quantity, pack }]
    medications_confirmed: list
    uc2_awaiting_confirmation: bool
    prescription_status: Optional[str]  # "found" | "not_found"
    order_id: Optional[str]
    uc2_complete: bool
    uc2_summary: Optional[str]

    # UC3 — Appointment Booking
    visit_mode: Optional[str]           # "in_person" | "telehealth"
    reason_for_visit: Optional[str]
    preferred_doctor: Optional[str]
    available_slots: list
    selected_slot: Optional[dict]
    appointment_id: Optional[str]
    uc3_complete: bool

    # Response to patient
    patient_response: Optional[str]
    response_blocked: bool
    block_reason: Optional[str]

    # Cost tracking
    total_cost_usd: float
    llm_calls: int
    turn_count: int
```

---

### Node responsibilities

#### `guardrail_node`
Runs on every turn before any UC processing.

**Inputs:** `messages[-1].content` (latest patient message)
**Outputs:** `de_identified_message`, `phi_lookup_table`, `is_health_related`, `needs_escalation`, `escalation_signals`, `response_blocked`

**Steps:**
1. Regex scan for SSN, MRN, insurance ID, Aadhaar, PAN, phone
2. spaCy NER for PERSON, DATE, GPE, LOC
3. Hash each detected value → deterministic token (MD5, first 8 chars)
4. Merge into `phi_lookup_table`
5. Extract first name from PERSON tokens (if not already known)
6. Keyword fast-pass: if message contains any of ~40 health keywords, skip NLI
7. DeBERTa NLI: classify de-identified message as health-related (threshold ≥ 0.5)
8. Keyword scan for hard escalation signals
9. DeBERTa NLI: soft escalation check if no hard signals
10. **Always** reset `response_blocked = False` at start (prevents stale state across turns)
11. Set `response_blocked = True` only if not health-related

**Routing:** `route_after_guardrail(state)` returns `"blocked"` | `"escalation"` | `"pass"`. Checks `awaiting_911_confirmation` first so turn 2 of an emergency conversation routes back to the emergency node regardless of message content.

---

#### `emergency_node`
Multi-turn emergency HITL handler.

**Turn 1** (first escalation): Asks patient if emergency services should be dispatched. Sets `awaiting_911_confirmation = True`.

**Turn 2** (patient replies):
- "yes" → `dispatch_emergency_services()` tool call → confirmed message
- "no" → monitoring instructions with crisis line numbers
- unclear → `interrupt()` + `notify_human_reviewer()` → HITL message

The `awaiting_911_confirmation` flag ensures turn 2 routes back to the emergency node via `route_after_guardrail`, regardless of whether the reply contains emergency keywords.

---

#### `intent_router_node`
Classifies or continues the active use case.

**Priority order:**
1. If `current_intent` is set and the UC is not complete → stay in current UC (no LLM call)
2. If `pending_intent` is set (queued transition, e.g. UC2 → UC3) → switch to pending
3. Otherwise → classify with DeBERTa NLI (three UC description labels)
4. If NLI confidence < 0.55 → Haiku fallback classification (1 LLM call, structured JSON output)

---

#### UC subgraphs — resume router pattern

All three UC subgraphs use the same design: **no intra-invocation loops**. Each invocation executes exactly one step and ends. The resume router at the subgraph entry reads state flags to decide which step to run next.

**UC2 Prescription Refill — state machine**

```
State flags                                    → Step executed
───────────────────────────────────────────────────────────────────
medications_extracted is empty                 → extract_medications_node
  (sets medications_extracted,
   uc2_awaiting_confirmation=True)
  └── automatically → confirmation_loop_node → END

medications_extracted set
uc2_awaiting_confirmation=True
patient message contains confirmation word     → check_prescription_node
  prescription_status = "found"               → END (order submitted)
  prescription_status = "not_found"           → offer_appointment_node → END

medications_extracted set
uc2_awaiting_confirmation=True
no confirmation word in patient message        → confirmation_loop_node → END
  (re-show summary)

prescription_status = "not_found"
uc2_complete = False
uc2_awaiting_confirmation = False              → handle_no_prescription_response_node → END
  patient chose "appointment"                 → pending_intent="UC3", uc2_complete=True
  patient chose "upload"                      → create order on hold, uc2_complete=True
```

**UC3 Appointment Booking — state machine**

```
State flags                                    → Step executed
───────────────────────────────────────────────────────────────────
selected_slot set, uc3_complete=False
  patient confirmed                            → book_appointment_node → END
  patient wants different slot                 → fetch_slots_node → END
                                                 (clears selected_slot)

available_slots set (slots shown to patient)   → confirm_appointment_node → END
  (sets selected_slot)

visit_mode set                                 → fetch_slots_node → END
  (sets available_slots, clears selected_slot)

preference words in patient message            → fetch_slots_node → END

no preferences yet                             → collect_preferences_node → END
```

---

### Data flow — single request walkthrough

#### UC1 first turn: "I have had a headache for 3 days"

```
1. FastAPI receives POST /triage { message, session_id }
   └── input_data = { ...initial_state, messages: [user message] }

2. graph.ainvoke(input_data, config)

3. guardrail_node
   ├── PHI scan: no PHI detected
   ├── Health relevance: keyword fast-pass ("headache") → health-related ✓
   ├── Emergency detection: no signals
   └── State: de_identified_message = "I have had a headache for 3 days"

4. route_after_guardrail → "pass"

5. intent_router_node
   ├── No current_intent set
   ├── DeBERTa NLI: "symptom check or health concern" → 0.87 confidence → UC1
   └── State: current_intent = "UC1"

6. uc1 subgraph → symptom_check_node
   ├── Acuity: duration terms → "Medium"
   ├── Haiku call: reply generation (1 LLM call, ~$0.0015)
   └── State: acuity="Medium", patient_response="...[response]..."

7. route_after_uc1 → "compliance"

8. safety_compliance_node
   ├── UC1 intent → check disclaimer present → yes ✓
   ├── Diagnosis pattern regex → no match ✓
   └── Prescription pattern regex → no match ✓

9. response_formatter_node
   ├── phi_lookup_table empty → no re-identification needed
   └── patient_response unchanged

10. FastAPI returns:
    { response: "...", intent: "UC1", acuity: "Medium", escalated: false,
      llm_calls: 1, estimated_cost_usd: 0.0015, latency_ms: 1842 }
```

#### UC2 multi-turn: prescription refill (2 turns)

```
Turn 1: "I need to refill my metformin 500mg"
─────────────────────────────────────────────
guardrail → pass → intent_router → UC2

uc2 subgraph:
  uc2_resume_router: medications_extracted empty → "extract"
  extract_medications_node:
    Haiku call: extract [{ name:"metformin", dosage:"500mg", quantity: null }]
    (name preserved verbatim — no brand normalisation)
    get_standard_quantity("metformin") → { quantity: 90, pack: "90 tablets" }
    State: medications_extracted=[...], uc2_awaiting_confirmation=True
  confirmation_loop_node:
    State: patient_response = "I've noted: metformin 500mg — 90 tablets. Is this correct?"
  → END

Turn 2: "Yes, that's correct"
─────────────────────────────────────────────
guardrail → pass → intent_router: UC2 not complete → stays in UC2

uc2 subgraph:
  uc2_resume_router:
    medications_extracted set ✓
    uc2_awaiting_confirmation=True ✓
    "yes" in last message → _patient_confirmed() = True → "check_prescription"
  check_prescription_node:
    check_prescription_history(patient_id, medications) → has_prescription: True
    State: prescription_status="found", uc2_complete=True
    patient_response = "Your prescription has been verified. Refill submitted..."
  → END

route_after_uc2 → "compliance"
safety_compliance → response_formatter → FastAPI returns confirmed response
```

---

### PHI de-identification pipeline

```
Patient message: "My name is John Smith, SSN 123-45-6789, and I have a fever"
                                            │
                                   ┌────────▼─────────┐
                                   │  Regex scanner   │
                                   │  SSN detected:   │
                                   │  "123-45-6789"   │
                                   └────────┬─────────┘
                                            │
                                   ┌────────▼─────────┐
                                   │  spaCy NER       │
                                   │  PERSON: "John   │
                                   │  Smith"          │
                                   └────────┬─────────┘
                                            │
                                   ┌────────▼─────────┐
                                   │  Hash each value │
                                   │  MD5 (first 8    │
                                   │  chars of hex)   │
                                   └────────┬─────────┘
                                            │
                          "123-45-6789" → "[SSN_a3f7b2c1]"
                          "John Smith"  → "[PERSON_de56ef78]"
                                            │
                                   ┌────────▼─────────┐
                                   │  Lookup table    │
                                   │  {               │
                                   │   "[SSN_a3f7]":  │
                                   │    "123-45-6789",│
                                   │   "[PERSON_de56]"│
                                   │    "John Smith"  │
                                   │  }               │
                                   └────────┬─────────┘
                                            │
De-identified: "My name is [PERSON_de56ef78], SSN [SSN_a3f7b2c1], and I have a fever"
                                            │
                                   ┌────────▼──────────────────┐
                                   │  Sent to LLM              │
                                   │  (tokens, not real PHI)   │
                                   └────────┬──────────────────┘
                                            │
LLM response: "Hello [PERSON_de56ef78], I understand you have a fever..."
                                            │
                                   ┌────────▼──────────────────┐
                                   │  response_formatter_node  │
                                   │  Re-identify [PERSON_*]   │
                                   │  first name only          │
                                   └────────┬──────────────────┘
                                            │
Final response: "Hello John, I understand you have a fever..."
                (first name only; SSN remains hashed in all logs and storage)
```

---

### LLM abstraction layer

All LLM calls go through a provider-agnostic `LLMClient`. Prompts, output schemas, and request builders live in `prompts/` — nodes contain no prompt text.

```
prompts/uc1.py          → build_symptom_response_request(message, acuity, name)
prompts/uc2.py          → build_extraction_request(message), MedicationExtractionResult
prompts/intent.py       → build_intent_request(message), IntentResult
prompts/summarization.py → build_uc1_summary_request(...), build_uc2_summary_request(...)
        │
        ▼
models/llm.py
  LLMRequest(
      config=LLMConfig(provider, model, max_tokens, temperature),
      messages=[LLMMessage(role, content)],
      system_prompt=...,   # request-level override
      json_mode=True       # → response_format={"type":"json_object"}
  )
        │
        ▼ (OpenRouter provider)
  openai.AsyncOpenAI(
      base_url="https://openrouter.ai/api/v1",
      api_key=os.getenv("OPENROUTER_API_KEY")
  ).chat.completions.create(
      model="anthropic/claude-haiku-4-5",
      messages=[system + user],
      max_tokens=..., temperature=...
  )
        │
        ▼
  LLMResponse(content, input_tokens, output_tokens, estimated_cost_usd)
```

To switch providers, change `DEFAULT_PROVIDER` and `DEFAULT_MODEL` in `config/llm_configs.py`. No node code changes needed.

---

### Session state lifecycle

```
Session created (first POST /triage):
  aget_state(session_id) → empty (no checkpoint)
  ainvoke({ ...initial_state, messages: [msg1] })
  MemorySaver writes checkpoint keyed by session_id
  Returns response

Turn 2 (same session_id):
  aget_state(session_id) → full TriageState from turn 1
  ainvoke({ messages: [msg2] })   ← new message only; rest from checkpoint
  MemorySaver updates checkpoint
  Returns response

Session ends when:
  uc3_complete = True
  OR patient abandons
  OR MemorySaver evicted (server restart in demo)
```

In production, one line change in `main.py` switches to persistent Redis-backed state:

```python
from langgraph.checkpoint.redis import RedisSaver
graph = build_graph(checkpointer=RedisSaver.from_conn_string(os.getenv("REDIS_URL")))
```

---

## Part 4 — Evolution: Demo → Production

| Component | Demo (current) | Production target |
|---|---|---|
| Session checkpointing | `MemorySaver` (in-process) | `RedisSaver` (Redis Cluster) |
| PHI lookup storage | Python dict, in-process | PostgreSQL `phi_lookup_table`, AES-256 encrypted |
| Audit logging | None | PostgreSQL `audit_log` — every turn, de-identified |
| Patient identity | Mock `get_patient_info()` | Real EHR/EMR API call |
| Prescription lookup | Mock `check_prescription_history()` | PostgreSQL `prescriptions` table |
| Appointment booking | Mock `create_appointment()` | PostgreSQL `appointments` + calendar API |
| Emergency dispatch | `print()` + mock | Real CAD/911 API integration |
| HITL notification | `print()` + mock | Redis queue → reviewer dashboard |
| ML serving | In-process at startup | Dedicated TorchServe / Triton servers |
| Monitoring | None | Prometheus + Grafana |
| Auth | None | JWT at API gateway, role-based access |

### What does not change

- The LangGraph graph structure (nodes, edges, subgraphs, routing)
- The resume router pattern for UC2 and UC3
- The PHI de-identification logic
- The LLM abstraction layer
- The `TriageState` schema (additive changes only)
- The safety compliance rules and prompts

The current implementation is production-shaped at the orchestration level. Moving to production is primarily replacing the persistence and tool layers, not restructuring the agentic logic.
