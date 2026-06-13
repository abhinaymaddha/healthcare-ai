# High-Level Architecture — Production System Design

This document describes what the Healthcare AI Triage Concierge looks like at production scale. The demo (see [LOW_LEVEL_ARCHITECTURE.md](LOW_LEVEL_ARCHITECTURE.md)) implements the full conversation logic but uses in-memory state and mock tools. This document defines the infrastructure required to make the system production-ready, HIPAA-compliant, and horizontally scalable.

---

## Production system overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Patient Clients                             │
│         Chainlit Web UI  │  Mobile App  │  EHR/EMR Integration      │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ HTTPS
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

## Data stores

### PostgreSQL — persistent storage

PostgreSQL is the system of record for everything that must survive restarts, be audited, or be queried across sessions.

#### `patient_sessions`
Tracks conversation sessions and their outcome.

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

#### `audit_log`
Immutable log of every conversation turn. HIPAA requires this.

```sql
CREATE TABLE audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID REFERENCES patient_sessions(session_id),
    turn_number         INTEGER NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- PHI never stored here; de-identified message only
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

#### `phi_lookup_table`
Stores the de-identification mapping per session. Encrypted at rest. TTL-controlled.

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

#### `phi_events`
Tracks every PHI detection event for compliance reporting.

```sql
CREATE TABLE phi_events (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID REFERENCES patient_sessions(session_id),
    turn_number         INTEGER,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    phi_types_detected  TEXT[],                         -- ["SSN", "PERSON"]
    token_count         INTEGER
    -- Never stores actual PHI values
);
```

#### `escalation_log`
Tracks all emergency escalations and HITL decisions.

```sql
CREATE TABLE escalation_log (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID REFERENCES patient_sessions(session_id),
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    escalation_type     VARCHAR(32),                    -- "keyword" | "nli_soft" | "both"
    signals             TEXT[],                         -- which signals triggered it
    dispatch_requested  BOOLEAN,
    dispatch_confirmed  BOOLEAN,
    hitl_triggered      BOOLEAN DEFAULT FALSE,
    hitl_reviewer_id    VARCHAR(64),
    hitl_resolution     VARCHAR(32),                    -- "dispatched" | "declined" | "monitoring"
    resolved_at         TIMESTAMPTZ
);
```

#### `prescriptions` and `appointments`
Production replacements for the mock tools.

```sql
CREATE TABLE prescriptions (
    id                  BIGSERIAL PRIMARY KEY,
    patient_id          VARCHAR(64) NOT NULL,
    medication_name     VARCHAR(128) NOT NULL,
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

Redis handles everything that is high-frequency, time-bounded, or needs sub-millisecond access.

#### LangGraph session state (RedisSaver)
The primary use of Redis. LangGraph's `RedisSaver` checkpointer stores the full `TriageState` snapshot after every graph invocation.

```
Key pattern:  langgraph:checkpoint:{thread_id}:{checkpoint_id}
TTL:          24 hours (configurable per deployment)
Serialization: MessagePack (LangGraph default)
```

When a patient sends turn 2, the graph reads the checkpoint, restores full state, and continues the conversation exactly where it left off — even if the request hits a different FastAPI instance.

#### Rate limiting
```
Key pattern:  ratelimit:session:{session_id}   → counter, TTL 60s
              ratelimit:ip:{client_ip}          → counter, TTL 60s
Limits:       10 requests/minute per session
              30 requests/minute per IP
```

#### Inference caching (optional)
For common symptom messages, cache the de-identified response to avoid redundant LLM calls.
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

## Service breakdown

### FastAPI Service (stateless HTTP layer)
- Validates request schema (Pydantic)
- Resolves session state via Redis (does the session already exist?)
- Dispatches to LangGraph worker pool
- Returns structured JSON response
- Horizontally scalable; no local state

### LangGraph Worker Pool
- Executes the compiled graph for one turn
- Reads/writes checkpoint via RedisSaver
- Calls local ML servers for NLI/NER inference
- Calls LLM gateway for Haiku completions
- Calls tool layer (real DBs in production, mocks in demo)
- Can be scaled independently of the HTTP layer

### Local ML Servers
- Serve DeBERTa NLI (`cross-encoder/nli-deberta-v3-xsmall`) via REST or gRPC
- Serve spaCy NER pipeline (`en_core_web_md`)
- GPU-backed in production for lower latency; CPU is sufficient for current load
- Separate from worker pool to allow independent scaling

### LLM Gateway (OpenRouter)
- Routes to `anthropic/claude-haiku-4-5`
- Adds retry logic, fallback routing, and spend tracking
- Enables zero-code model swaps (change config, not code)

### HITL Reviewer Dashboard
- Web UI for human reviewers to see emergency sessions
- Receives alerts from the Redis HITL queue
- Allows reviewers to approve emergency dispatch, mark cases as resolved, or escalate to a clinician
- All reviewer actions written to `escalation_log`

---

## HIPAA compliance design

| Requirement | Implementation |
|---|---|
| PHI never sent to LLM | De-identification before every LLM call; only hashed tokens sent |
| PHI at rest encrypted | AES-256 encryption on `phi_lookup_table.encrypted_value` |
| PHI in transit encrypted | TLS everywhere; no HTTP |
| Audit trail | Immutable `audit_log` table; de-identified inputs/outputs only |
| Access control | Role-based access on PostgreSQL; reviewers only see escalation data |
| Data retention | PHI lookup TTL = 24h; audit logs retained per compliance policy |
| Breach detection | Prometheus alert on unexpected PHI event volume spikes |

---

## Monitoring and alerting

### Key metrics (Prometheus)

| Metric | Alert threshold |
|---|---|
| `escalation_miss_rate` | Alert if > 0 in 1h window (requires labeled validation set) |
| `phi_deidentification_latency_p95` | Alert if > 200ms |
| `llm_call_error_rate` | Alert if > 5% in 5m window |
| `session_state_read_latency_p99` | Alert if > 50ms (Redis health) |
| `avg_cost_per_request` | Alert if > $0.005 (model regression or misuse) |
| `hitl_queue_depth` | Alert if > 10 (backlog of unreviewed emergencies) |

### Dashboards (Grafana)
- **Operations:** request volume, latency P50/P95/P99, error rates, cost per hour
- **Safety:** escalation events per hour, HITL queue depth, resolution time
- **Compliance:** PHI detection rate, disclaimer presence rate, violation count

---

## Scalability model

| Load | Instances |
|---|---|
| < 100 req/min | 2 FastAPI pods, 2 LangGraph workers, 1 Redis node, 1 Postgres |
| 100–1000 req/min | 4 FastAPI pods, 4 LangGraph workers, Redis Cluster (3 shards) |
| > 1000 req/min | Auto-scale FastAPI + workers; ML servers on GPU; Postgres read replicas |

LangGraph workers are the bottleneck at high load — each invocation blocks for ~500ms–3000ms waiting on the Haiku API call. Horizontal scaling (more workers) is the primary lever.

---

## Evolution from demo to production

| Component | Demo | Production |
|---|---|---|
| Session state | MemorySaver (in-process dict) | RedisSaver (Redis Cluster) |
| PHI lookup | Python dict, session lifetime | PostgreSQL `phi_lookup_table`, AES-encrypted, TTL |
| Tools (patient/prescription/appointment) | Mock data | Real API calls to EHR/EMR systems |
| Emergency dispatch | `print()` log | Real 911 API or CAD system integration |
| HITL notification | `print()` log | Redis queue + reviewer dashboard |
| Audit logging | None | PostgreSQL `audit_log`, immutable |
| ML serving | In-process (loaded at startup) | Dedicated model servers (TorchServe or Triton) |
| Monitoring | None | Prometheus + Grafana |
| Auth | None | JWT/OAuth at API gateway |
