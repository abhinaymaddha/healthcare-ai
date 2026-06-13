# Executive Email — Healthcare AI Triage Concierge

**To:** Dr. Samantha Okafor, Chief Medical Information Officer  
**From:** AI Engineering, EY Healthcare Innovation Lab  
**Subject:** Healthcare AI Patient Triage Concierge — Project Summary and Strategic Recommendation  
**Date:** June 13, 2026

---

Dr. Okafor,

I am writing to share the results of our Healthcare AI Patient Triage Concierge prototype and our recommendation for next steps.

**What we built.** We developed a multi-turn conversational AI system that handles three high-volume patient workflows end-to-end: symptom triage with acuity classification, prescription refill requests, and appointment booking. The system completes each workflow in a single conversation session, automatically transitions between workflows as patient needs evolve, and escalates emergencies — including cardiac events, respiratory distress, and suicidal ideation — to 911 and mental health crisis services without requiring human intervention in the routing decision.

**How we protected patient privacy.** Before any message reaches the AI model, our PHI detection pipeline strips and hashes all personally identifiable information — Social Security numbers, medical record numbers, insurance IDs, names, and dates of birth. The underlying language model never sees a patient's real data. This architecture is designed to support HIPAA audit requirements and is documented in our compliance design review.

**What makes this approach operationally viable.** We used a small, cost-efficient model (Claude Haiku 4.5 via OpenRouter at approximately $0.002 per conversation) together with a locally hosted NLI classifier for all routing and safety decisions. Emergency escalation runs entirely on local rule-based logic — no LLM call, no latency, no cost. The architecture is horizontally scalable and model-agnostic; switching to a different AI provider requires a single configuration change.

**Recommendation.** We recommend a 90-day pilot in one specialty clinic, starting with appointment booking only (lowest risk, highest volume) and expanding to symptom triage in month two. A Human-in-the-Loop reviewer dashboard for emergency escalation cases should be in place before go-live.

I am available to present the full technical design and evaluation results at your convenience.

Warm regards,  
EY Healthcare Innovation Lab
