"""
Compliance text: disclaimer wording and safe fallback responses.
Centralised here so any wording change is a single edit.
"""

DISCLAIMER = (
    "This is not a medical diagnosis. "
    "Please consult a licensed healthcare provider for personalised medical advice."
)

# Used when a compliance violation is detected in a generated response.
# The LLM response is discarded and this is shown instead.
SAFE_FALLBACK = (
    "I wasn't able to generate an appropriate response at this time. "
    "Please consult a licensed healthcare provider for medical advice. "
    f"{DISCLAIMER}"
)
