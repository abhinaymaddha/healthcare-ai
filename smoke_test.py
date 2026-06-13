import urllib.request
import json

BASE = "http://localhost:8000"

def post(message, session_id):
    data = json.dumps({"message": message, "session_id": session_id}).encode()
    req = urllib.request.Request(
        BASE + "/triage", data=data,
        headers={"Content-Type": "application/json"}
    )
    r = urllib.request.urlopen(req, timeout=30)
    return json.loads(r.read())

def show(resp):
    print(f"  intent    : {resp.get('intent')}")
    print(f"  acuity    : {resp.get('acuity')}")
    print(f"  escalated : {resp.get('escalated')}")
    print(f"  llm_calls : {resp.get('llm_calls')}")
    print(f"  cost      : ${resp.get('estimated_cost_usd')}")
    print(f"  latency   : {resp.get('latency_ms')}ms")
    print(f"  response  : {resp.get('response', '')[:180]}")

# --- /health ---
print("=== /health ===")
r = urllib.request.urlopen(BASE + "/health")
print(json.loads(r.read()))

# --- Not health related ---
print("\n=== NOT HEALTH RELATED (should block) ===")
resp = post("What is the weather like today?", "smoke-1")
show(resp)

# --- Symptom check ---
print("\n=== SYMPTOM CHECK (persistent headache) ===")
resp = post("I have had a persistent headache on the right side for 3 days, Tylenol is not helping", "smoke-2")
show(resp)

# --- Emergency escalation ---
print("\n=== EMERGENCY ESCALATION (chest pain) ===")
resp = post("I am having severe chest pain radiating to my left arm, started 10 minutes ago", "smoke-3")
show(resp)

# --- Prescription refill ---
print("\n=== PRESCRIPTION REFILL ===")
resp = post("I need to refill my metformin 500mg please", "smoke-4")
show(resp)
