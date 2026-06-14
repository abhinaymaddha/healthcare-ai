# Healthcare AI Patient Symptom Triage Concierge

A multi-agent, multi-turn AI system that handles the first turn of a patient conversation in a telehealth app. It classifies the inquiry, applies clinical-safety and privacy checks, and generates a compliant patient-facing reply — across three use cases: symptom checking, prescription refills, and appointment booking.

Built with **LangGraph** for stateful multi-turn orchestration, a two-tier LLM strategy (small LLM for routing/extraction, medium-size LLM for clinical response generation) via OpenRouter, and a local **DeBERTa NLI** model for guardrails. Testing used **Claude Haiku 4.5** (small LLM) and **Claude Sonnet 4.6** (medium-size LLM).

---

## Deliverables

All submission artifacts are in [`deliverables/`](deliverables/). Start with [`deliverables/README.md`](deliverables/README.md) for a guided reading order:

1. **[Executive Summary](deliverables/EXECUTIVE_SUMMARY.md)** — business case and pilot recommendation for clinical leadership
2. **[High-Level Architecture](deliverables/HIGH_LEVEL_ARCHITECTURE.md)** — patient workflows, PHI protection, safety and compliance (clinical/business audience)
3. **[Architecture Decisions](deliverables/ARCHITECTURE_DECISIONS.md)** — design principles, technology choices, cost model
4. **[Low-Level Architecture](deliverables/LOW_LEVEL_ARCHITECTURE.md)** — infrastructure, data schemas, LangGraph implementation (engineering audience)
5. **[Future Scope](deliverables/FUTURE_SCOPE.md)** — five planned improvement areas with problem statements and direction

---

## Architecture overview

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full breakdown, including:
- [High-Level Architecture](HIGH_LEVEL_ARCHITECTURE.md) — production system design (Postgres, Redis, services)
- [Low-Level Architecture](LOW_LEVEL_ARCHITECTURE.md) — current LangGraph implementation and data flow

---

## Prerequisites

- Python 3.11+
- An OpenRouter API key (free tier works): [openrouter.ai](https://openrouter.ai)

---

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Download the NLP models** (one-time, ~130MB total)
```bash
python -m spacy download en_core_web_md
```
The DeBERTa NLI model downloads automatically on first startup and is cached in `.cache/`.

**3. Set your API key**
```bash
cp .env.example .env
# Edit .env and set: OPENROUTER_API_KEY=sk-or-v1-...
```

---

## Running

### FastAPI backend

```bash
uvicorn main:app --reload
```

Server starts at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

### Chainlit chat UI

In a separate terminal:
```bash
chainlit run chainlit_app.py
```

Opens at `http://localhost:8501` — a ChatGPT-style interface connected to the backend.

---

## Quick test

**Health check:**
```bash
curl http://localhost:8000/health
```

**Symptom check:**
```bash
curl -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"message": "I have had a persistent headache for 3 days", "session_id": "demo-1"}'
```

**Prescription refill (multi-turn — send to same session_id):**
```bash
# Turn 1: request refill
curl -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"message": "I need to refill my metformin 500mg", "session_id": "demo-2"}'

# Turn 2: confirm (after reviewing summary in turn 1 response)
curl -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"message": "Yes, that looks correct", "session_id": "demo-2"}'
```

**Emergency escalation:**
```bash
curl -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"message": "I am having severe chest pain and my left arm is numb", "session_id": "demo-3"}'
```

**Run smoke tests** (server must be running):
```bash
python smoke_test.py
```

---

## API reference

### `POST /triage`

**Request:**
```json
{
  "message": "string",
  "session_id": "string (optional, defaults to 'default-session')"
}
```

**Response:**
```json
{
  "response": "Patient-facing reply text",
  "session_id": "demo-1",
  "intent": "UC1",
  "acuity": "Medium",
  "escalated": false,
  "latency_ms": 1842,
  "estimated_cost_usd": 0.0015,
  "llm_calls": 1
}
```

**Intent values:** `UC1` (symptom check) | `UC2` (prescription refill) | `UC3` (appointment booking)
**Acuity values:** `Low` | `Medium` | `High` | `null` (for non-UC1 intents)

### `GET /health`

```json
{ "status": "ok", "graph_ready": true }
```

---

## Running evaluation

```bash
# Quick (30 cases, ~2 minutes)
python eval/evaluate.py --cases eval/test_cases_mini.json

# Full (200 cases, ~15 minutes)
python eval/evaluate.py --cases eval/test_cases.json --output eval/report.txt
```

---

## Project structure

```
├── config/llm_configs.py       All LLM configurations — change model/provider here
├── models/
│   ├── state.py                LangGraph state (TriageState TypedDict)
│   ├── llm.py                  Provider-agnostic LLM abstraction
│   └── classifier.py           DeBERTa NLI singleton
├── guardrail/                  PHI de-id, health relevance, emergency detection
├── intent/                     Intent router (local NLI + small LLM fallback)
├── uc1_symptom_check/          Symptom check, acuity classification, reply gen
├── uc2_prescription_refill/    Prescription refill multi-turn workflow
├── uc3_appointment_booking/    Appointment booking multi-turn workflow
├── summarization/              Context compression between UC transitions
├── safety/                     Compliance check + response formatter
├── tools/                      Mock tool implementations (patient, prescription, appointment, emergency)
├── graph/main_graph.py         LangGraph graph assembly
├── eval/                       Evaluation dataset + harness
├── main.py                     FastAPI backend
├── chainlit_app.py             Chainlit chat frontend
└── smoke_test.py               Quick 5-scenario smoke test
```

---

## Switching LLM providers

All LLM calls are routed through `config/llm_configs.py`. To switch models:

```python
# config/llm_configs.py
SMALL_MODEL  = "anthropic/claude-haiku-4-5"    # intent, extraction, clarification
MEDIUM_MODEL = "anthropic/claude-sonnet-4-6"  # clinical response generation (UC1)
_PROVIDER = "openrouter"                    # or "openai", "anthropic", "gemini"
```

No changes needed in any node code.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key |
| `REDIS_URL` | No | Redis connection string for production session state |

---

## Known limitations (demo scope)

- All tool calls return **mock data** (no real prescriptions, appointments, or emergency dispatch)
- Session state is **in-memory** (lost on server restart; use `REDIS_URL` for persistence)
- PHI lookup table is **per-session** (not persisted to a database)
- The DeBERTa NLI health relevance classifier may pass some borderline non-health messages
