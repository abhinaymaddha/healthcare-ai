"""
LLM provider constants.

System prompts, request configs, and output schemas live in prompts/.
This module only defines the default model and provider so that
prompts/ modules have a single place to update if the model changes.
"""
from models.llm import LLMConfig

DEFAULT_MODEL = "anthropic/claude-haiku-4-5"
DEFAULT_PROVIDER = "openrouter"

# Kept for any code that still references these directly.
# New prompt modules should build their own LLMConfig from the constants above.
_BASE = dict(provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL)

REPLY_GENERATION_CONFIG    = LLMConfig(**_BASE, max_tokens=450, temperature=0.4)
MEDICATION_EXTRACTION_CONFIG = LLMConfig(**_BASE, max_tokens=300, temperature=0.0)
SUMMARIZATION_CONFIG       = LLMConfig(**_BASE, max_tokens=200, temperature=0.0)
INTENT_CLASSIFICATION_CONFIG = LLMConfig(**_BASE, max_tokens=20,  temperature=0.0)
