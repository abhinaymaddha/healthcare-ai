# Low-Level Architecture — Current Implementation

This document describes the current implementation in detail: the LangGraph graph structure, how a request flows through the system turn by turn, the data model, and where the system needs to evolve to reach production. For the production infrastructure design, see [HIGH_LEVEL_ARCHITECTURE.md](HIGH_LEVEL_ARCHITECTURE.md).

---

## LangGraph graph structure

The entire triage pipeline is a single compiled `StateGraph`. All session state lives in `TriageState`, a `TypedDict` that LangGraph persists and restores via the `MemorySaver` checkpointer.

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
                  └──────┬──────┘  ◄── all paths end here
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

## TriageState schema

Every node reads from and writes to `TriageState`. LangGraph merges node return dicts into the state automatically. The `messages` field uses the `add_messages` reducer, which appends rather than replaces.

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
    pending_intent: Optional[str]       # queued transition (e.g. "UC3" after UC1)

    # Guardrail outputs (updated every turn)
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

## Node responsibilities

### `guardrail_node`
Runs on every turn before any UC processing.

**Inputs:** `messages[-1].content` (latest patient message)
**Outputs:** `de_identified_message`, `phi_lookup_table`, `is_health_related`, `needs_escalation`, `escalation_signals`, `response_blocked`

**Steps:**
1. Regex scan for SSN, MRN, insurance ID, Aadhaar, PAN, phone
2. spaCy NER for PERSON, DATE, GPE, LOC
3. Hash each detected value → deterministic token
4. Merge into `phi_lookup_table`
5. Extract first name from PERSON tokens (if not already known)
6. DeBERTa NLI: classify de-identified message as health-related (threshold ≥ 0.6)
7. Keyword scan for hard escalation signals
8. DeBERTa NLI: soft escalation check if no hard signals
9. **Always** reset `response_blocked = False` (prevents stale state from previous turns)
10. Set `response_blocked = True` only if this turn is not health-related

**Routing:** `route_after_guardrail(state)` returns `"blocked"` | `"escalation"` | `"pass"`. Checks both `needs_escalation` and `awaiting_911_confirmation` so turn 2 of an emergency conversation correctly routes back to the emergency node.

---

### `emergency_node`
Multi-turn emergency HITL handler.

**Turn 1** (first escalation): asks patient if emergency services should be dispatched
**Turn 2** (patient replies):
- "yes" → `dispatch_emergency_services()` tool call → confirm message
- "no" → monitoring instructions
- unclear → `interrupt()` + `notify_human_reviewer()` → HITL message

The `awaiting_911_confirmation` flag in state ensures turn 2 routes back here regardless of whether the reply message triggers emergency keywords.

---

### `intent_router_node`
Classifies or continues the active use case.

**Priority order:**
1. If `current_intent` is set and the UC is not complete → stay in current UC (no LLM call)
2. If `pending_intent` is set (queued transition) → switch to pending intent
3. Otherwise → classify with DeBERTa NLI (labels: UC1/UC2/UC3 descriptions)
4. If NLI confidence < 0.55 → Haiku fallback classification (1 LLM call)

---

### UC subgraphs — resume router pattern

All three UC subgraphs use the same design principle: **no intra-invocation loops**. Each invocation runs exactly one step and ends. The resume router at the subgraph entry reads state flags to determine which step to run.

#### UC2 Prescription Refill — state machine

```
State flags          →   Step executed
─────────────────────────────────────────────────────────────────────
medications_extracted is empty               → extract_medications_node
  │ (sets medications_extracted, uc2_awaiting_confirmation=True)
  └── then automatically → confirmation_loop_node → END

medications_extracted set
uc2_awaiting_confirmation=True
patient message contains confirmation word   → check_prescription_node
  │ prescription_status = "found"            → END (order confirmed)
  └── prescription_status = "not_found"      → offer_appointment_node → END

medications_extracted set
uc2_awaiting_confirmation=True
no confirmation word in patient message      → confirmation_loop_node → END
  (re-show summary)

prescription_status = "not_found"
uc2_complete = False
uc2_awaiting_confirmation = False            → handle_no_prescription_response_node → END
  │ patient chose "appointment"             → pending_intent = "UC3", uc2_complete=True
  └── patient chose "upload"               → create order (hold), uc2_complete=True
```

#### UC3 Appointment Booking — state machine

```
State flags          →   Step executed
─────────────────────────────────────────────────────────────────────
selected_slot set, uc3 not complete
  └── patient confirmed                     → book_appointment_node → END
  └── patient wants different slot          → fetch_slots_node → END (clears selected_slot)

available_slots set (slots shown to patient)→ confirm_appointment_node → END
  (sets selected_slot)

visit_mode set                              → fetch_slots_node → END
  (sets available_slots, clears selected_slot)

preference words in patient message         → fetch_slots_node → END

no preferences yet                          → collect_preferences_node → END
```

---

## Data flow — single request

### UC1 first turn: "I have had a headache for 3 days"

```
1. FastAPI receives POST /triage { message, session_id }
   ├── aget_state(session_id) → empty (new session)
   └── input_data = { ...initial_state, messages: [user message] }

2. graph.ainvoke(input_data, config)

3. guardrail_node
   ├── PHI scan: no PHI detected
   ├── Health relevance: "headache for 3 days" → health-related ✓
   ├── Emergency detection: no signals
   └── State update: de_identified_message = "I have had a headache for 3 days"

4. route_after_guardrail → "pass"

5. intent_router_node
   ├── No current_intent set
   ├── DeBERTa NLI: "symptom check or health concern" → 0.87 confidence → UC1
   └── State update: current_intent = "UC1"

6. uc1 subgraph → symptom_check_node
   ├── Acuity classification: "3 days" → MEDIUM_ACUITY_TERMS match → "Medium"
   ├── Haiku call: reply generation (1 LLM call, ~$0.0015)
   ├── get_appointment_history(patient_id) → has_prior_appointments: false
   └── State update: acuity="Medium", patient_response="...[response]...\nWould you like to book an appointment?"

7. route_after_uc1 → "compliance" (no pending_intent)

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

### UC2 multi-turn: prescription refill (2 turns)

```
Turn 1: "I need to refill my metformin 500mg"
─────────────────────────────────────────────
guardrail → pass → intent_router → UC2

uc2 subgraph:
  uc2_resume_router: medications_extracted is empty → "extract"
  extract_medications_node:
    Haiku call: extract [{ name:"metformin", dosage:"500mg", quantity: null }]
    get_standard_quantity("metformin") → { quantity: 90, pack: "90 tablets" }
    State: medications_extracted=[...], uc2_awaiting_confirmation=True
  confirmation_loop_node:
    State: patient_response = "I've noted: metformin 500mg — 90 tablets. Is this correct?"
  → END

FastAPI returns: { response: "I've noted: metformin...", intent: "UC2" }

─────────────────────────────────────────────
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

route_after_uc2 → "compliance" (no pending_intent)
safety_compliance → response_formatter → FastAPI returns confirmed response
```

---

## PHI de-identification pipeline

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
                                   │  sha256 (first   │
                                   │  8 chars)        │
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
                                   │  only → first name        │
                                   └────────┬──────────────────┘
                                            │
Final response: "Hello John, I understand you have a fever..."
                (first name only; SSN stays hashed in all logs)
```

---

## LLM abstraction layer

```
config/llm_configs.py
  REPLY_GENERATION_CONFIG = LLMConfig(
      provider="openrouter",
      model="anthropic/claude-haiku-4-5",
      max_tokens=400, temperature=0.3,
      system_prompt="..."
  )
            │
            ▼
models/llm.py
  client = get_llm_client()       # singleton per provider
  response = await client.complete(
      LLMRequest(
          config=REPLY_GENERATION_CONFIG,
          messages=[LLMMessage(role="user", content="...")]
      )
  )
            │
            ▼ (OpenRouter provider)
  openai.AsyncOpenAI(
      base_url="https://openrouter.ai/api/v1",
      api_key=os.getenv("OPENROUTER_API_KEY")
  ).chat.completions.create(
      model="anthropic/claude-haiku-4-5",
      messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user",   "content": "..."}
      ],
      max_tokens=400, temperature=0.3
  )
            │
            ▼
  LLMResponse(
      content="...",
      estimated_cost_usd=0.0015,
      input_tokens=312,
      output_tokens=187
  )
```

To switch to direct Anthropic API, Gemini, or another OpenRouter model, change only `_PROVIDER` and `_MODEL` in `config/llm_configs.py`. No node code changes needed.

---

## Session state lifecycle

```
Session created (first POST /triage):
  aget_state() → empty
  ainvoke({ ...initial_state, messages: [msg1] })
  MemorySaver writes checkpoint keyed by session_id
  Returns response + state snapshot

Turn 2 (same session_id):
  aget_state() → checkpoint with full TriageState from turn 1
  ainvoke({ messages: [msg2] })   ← only new message; rest from checkpoint
  MemorySaver updates checkpoint
  Returns response

Session ends when:
  uc3_complete=True  (all 3 UCs done, or booking confirmed)
  OR: patient abandons session
  OR: MemorySaver evicted (server restart in demo)
```

In production, MemorySaver is replaced with RedisSaver. The `build_graph()` function accepts a `checkpointer=` parameter — no graph changes needed:

```python
# Production path (one line change in main.py)
from langgraph.checkpoint.redis import RedisSaver
graph = build_graph(checkpointer=RedisSaver.from_conn_string(os.getenv("REDIS_URL")))
```

---

## Evolution path: demo → production

### What changes, and where

| Area | Current (demo) | Production target |
|---|---|---|
| Session checkpointing | `MemorySaver` | `RedisSaver` (Redis Cluster) |
| PHI lookup storage | Python dict, in-process | PostgreSQL `phi_lookup_table`, AES-encrypted |
| Audit logging | None | PostgreSQL `audit_log` — every turn, de-identified |
| Patient identity | Mock `get_patient_info()` | Real EHR/EMR API call |
| Prescription lookup | Mock `check_prescription_history()` | PostgreSQL `prescriptions` table |
| Appointment booking | Mock `create_appointment()` | PostgreSQL `appointments` + calendar API |
| Emergency dispatch | `print()` + mock | Real CAD/911 API integration |
| HITL notification | `print()` + mock | Redis queue → reviewer dashboard |
| ML serving | In-process at FastAPI startup | Dedicated TorchServe / Triton servers |
| Monitoring | None | Prometheus + Grafana (escalation miss rate, cost, latency) |
| Auth | None | JWT at API gateway, role-based access |

### What does NOT change

- The LangGraph graph structure (nodes, edges, subgraphs)
- The resume router pattern for UC2 and UC3
- The PHI de-identification logic
- The LLM abstraction layer
- The `TriageState` schema (additive changes only)
- The safety compliance rules

The current implementation is production-shaped at the orchestration level. Moving to production is primarily replacing the persistence and tool layers, not restructuring the agentic logic.

---

## Known limitations (current demo)

| Issue | Impact | Fix |
|---|---|---|
| `response_blocked` not reset between turns | Turn after a block is also blocked | Set `response_blocked=False` in guardrail on every turn |
| `awaiting_911_confirmation` not checked in guardrail routing | Emergency turn 2 bypasses emergency node | Add flag check to `route_after_guardrail` |
| `fetch_slots_node` doesn't clear `selected_slot` | Re-selection after rejection books old slot | Return `"selected_slot": None` from `fetch_slots_node` |
| Health relevance NLI too permissive | Some non-health messages pass | Add confidence threshold ≥ 0.6 |
| LLM responses may include markdown headers | Patient sees `# Response to Patient` | Add "no markdown headers" to system prompt |
| Patient addressed as "the patient" in third person | Wrong pronoun when no name known | Fix fallback to "you" in UC1 prompt |
