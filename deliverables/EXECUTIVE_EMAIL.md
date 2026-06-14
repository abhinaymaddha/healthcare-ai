# Executive Email — Healthcare AI Triage Concierge

**To:** Dr. Samantha Okafor, Chief Medical Information Officer  
**From:** AI Engineering, EY Healthcare Innovation Lab  
**Subject:** Healthcare AI Patient Triage Concierge
**Date:** June 13, 2026

---

Dr. Okafor,

We have completed our Healthcare AI Patient Triage Concierge prototype and would like to share our findings and recommendation.

**What it does.** The system handles the three highest-volume patient requests before a clinical interaction begins — all within a single continuous conversation:

- **Symptom triage** — assesses urgency, classifies acuity, and guides the patient to the appropriate next step
- **Prescription refills** — collects and confirms medication details, verifies the prescription, and submits the refill request
- **Appointment scheduling** — gathers patient preferences, presents available slots, and confirms the booking

If a patient's needs shift mid-conversation — for example, reporting symptoms and then requesting a refill — the system transitions without requiring them to start over.

**How it keeps patients safe:**

- Multi-layered detection identifies emergency signals — cardiac, respiratory, stroke, overdose, and suicidal ideation — and immediately asks the patient whether to dispatch emergency services
- A clinical reviewer is notified in parallel; the AI generates no clinical response during escalation
- Every symptom response is independently checked for diagnosis language and medication advice before it reaches the patient; if either check fails, a safe fallback is sent instead

**How it protects patient privacy:**

- All identifying information — names, SSNs, medical record numbers, insurance IDs — is removed before any message is processed
- The AI never sees real patient data at any point in the conversation
- Designed to support HIPAA audit requirements; full compliance review available on request

I am available to present the full design and evaluation results at your convenience.

Warm regards,  
EY Healthcare Innovation Lab
