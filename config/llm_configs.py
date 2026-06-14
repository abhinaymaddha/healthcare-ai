"""
LLM provider constants — two-tier model strategy.

Small LLM  : fast, cheap — used for intent confirmation, clarification,
             medication extraction, and summarization.
Medium LLM : higher quality — used for clinical response generation (UC1)
             where nuance, empathy, and compliance accuracy matter most.
Large LLM  : reserved for future high-complexity tasks (e.g., multi-step
             reasoning, LLM-as-judge evaluation).

System prompts, request configs, and output schemas live in prompts/.
"""
from models.llm import LLMConfig

SMALL_MODEL  = "anthropic/claude-haiku-4-5"
MEDIUM_MODEL = "anthropic/claude-sonnet-4-6"
DEFAULT_PROVIDER = "openrouter"

_SMALL  = dict(provider=DEFAULT_PROVIDER, model=SMALL_MODEL)
_MEDIUM = dict(provider=DEFAULT_PROVIDER, model=MEDIUM_MODEL)

REPLY_GENERATION_CONFIG      = LLMConfig(**_MEDIUM, max_tokens=450, temperature=0.4)
MEDICATION_EXTRACTION_CONFIG = LLMConfig(**_SMALL,  max_tokens=300, temperature=0.0)
SUMMARIZATION_CONFIG         = LLMConfig(**_SMALL,  max_tokens=200, temperature=0.0)
INTENT_CLASSIFICATION_CONFIG = LLMConfig(**_SMALL,  max_tokens=20,  temperature=0.0)
