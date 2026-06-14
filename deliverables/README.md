# Deliverables — Healthcare AI Patient Triage Concierge

This folder contains all submission artifacts for the EY Healthcare AI project. Read them in the order below.

---

## Reading order

| # | File | Audience | What it covers |
|---|------|----------|----------------|
| 1 | [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) | Clinical leadership, CMIOs | Business case, pilot recommendation, what was built and why |
| 2 | [HIGH_LEVEL_ARCHITECTURE.md](HIGH_LEVEL_ARCHITECTURE.md) | Clinical, compliance, business | Patient workflows, PHI protection, emergency handling, compliance rules, security controls, cost model |
| 3 | [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) | Engineering leads | Design principles, technology choices, cost analysis, what is mocked vs. production |
| 4 | [LOW_LEVEL_ARCHITECTURE.md](LOW_LEVEL_ARCHITECTURE.md) | Engineers, technical reviewers | Infrastructure diagrams, data schemas, LangGraph implementation, node responsibilities, session lifecycle |
| 5 | [FUTURE_SCOPE.md](FUTURE_SCOPE.md) | Product and engineering | Five planned improvement areas with problem statements, risks, and direction |

---

## What we built

A multi-turn conversational AI that handles three patient workflows end-to-end: symptom triage with acuity classification (UC1), prescription refill (UC2), and appointment booking (UC3). Built on LangGraph with a two-tier LLM strategy (small LLM for routing/extraction, medium-size LLM for clinical response generation), local DeBERTa NLI for zero-cost guardrails, and a PHI de-identification pipeline that ensures patient data never reaches an LLM.

## Source code

The full source code lives at the root of this repository. Key entry points:

- `main.py` — FastAPI backend (`uvicorn main:app --reload`, then `POST /triage`)
- `chainlit_app.py` — Chainlit chat UI (`chainlit run chainlit_app.py`)
- `graph/main_graph.py` — LangGraph graph assembly (all nodes and routing)
- `eval/evaluate.py` — evaluation harness (`python eval/evaluate.py --cases eval/test_cases_mini.json`)
- `smoke_test.py` — quick 5-scenario smoke test

See the root `README.md` for setup instructions and example API calls.
