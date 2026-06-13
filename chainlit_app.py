"""Chainlit frontend — wraps the FastAPI triage backend."""
import uuid
import httpx
import chainlit as cl

BACKEND_URL = "http://localhost:8000/triage"


@cl.on_chat_start
async def on_start():
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)
    await cl.Message(
        content=(
            "Hello! I'm your healthcare triage assistant.\n\n"
            "I can help you with:\n"
            "• **Symptom check** — describe what you're experiencing\n"
            "• **Prescription refill** — request a medication refill\n"
            "• **Appointment booking** — schedule a doctor's visit\n\n"
            "How can I help you today?"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("session_id")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                BACKEND_URL,
                json={"message": message.content, "session_id": session_id},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            await cl.Message(
                content="I'm having trouble connecting. Please try again.",
                author="System",
            ).send()
            return

    response_text = data.get("response", "")
    escalated = data.get("escalated", False)
    intent = data.get("intent")
    acuity = data.get("acuity")
    cost = data.get("estimated_cost_usd", 0.0)
    latency = data.get("latency_ms", 0)

    # Escalation banner
    if escalated:
        await cl.Message(
            content="🚨 **MEDICAL EMERGENCY DETECTED**\nIf this is life-threatening, call **911** immediately. Mental health crisis: call or text **988**.",
            author="⚠️ Alert",
        ).send()

    # Main response
    await cl.Message(content=response_text).send()

    # Debug panel (collapsed)
    debug_lines = [f"**Intent:** {intent or 'N/A'}"]
    if acuity:
        debug_lines.append(f"**Acuity:** {acuity}")
    debug_lines.append(f"**Latency:** {latency}ms")
    debug_lines.append(f"**Est. cost:** ${cost:.6f}")
    debug_lines.append(f"**LLM calls:** {data.get('llm_calls', 0)}")

    await cl.Message(
        content="\n".join(debug_lines),
        author="🔍 Debug",
    ).send()
