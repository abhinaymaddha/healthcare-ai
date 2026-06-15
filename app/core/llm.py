"""LLM abstraction layer — provider-agnostic, Pydantic-based."""
from __future__ import annotations
import os
import logging
from abc import ABC, abstractmethod
from typing import Literal, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "openai", "openrouter", "gemini"]
    model: str
    max_tokens: int = 500
    temperature: float = 0.3
    system_prompt: Optional[str] = None


class LLMMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    config: LLMConfig
    messages: list[LLMMessage]
    system_prompt: Optional[str] = None   # overrides config.system_prompt when set
    json_mode: bool = False               # instructs provider to return valid JSON only


class LLMResponse(BaseModel):
    content: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str

    @property
    def estimated_cost_usd(self) -> float:
        COST_MAP = {
            # Small LLM — fast tasks (intent, extraction, clarification, summarization)
            ("anthropic",   "claude-haiku-4-5"):                    (1.0,   5.0),
            ("openrouter",  "anthropic/claude-haiku-4-5"):          (1.0,   5.0),
            ("openrouter",  "anthropic/claude-3-5-haiku"):          (1.0,   5.0),
            ("openrouter",  "anthropic/claude-3-5-haiku-20241022"): (1.0,   5.0),
            # Medium-size LLM — clinical response generation (UC1)
            ("anthropic",   "claude-sonnet-4-6"):                   (3.0,  15.0),
            ("openrouter",  "anthropic/claude-sonnet-4-6"):         (3.0,  15.0),
            # Large LLM — reserved for future high-complexity tasks
            ("anthropic",   "claude-opus-4-8"):                     (5.0,  25.0),
            ("openrouter",  "anthropic/claude-opus-4-8"):           (5.0,  25.0),
            ("openai",      "gpt-4o-mini"):                         (0.15,  0.60),
        }
        inp_rate, out_rate = COST_MAP.get((self.provider, self.model), (0.0, 0.0))
        return (self.input_tokens * inp_rate + self.output_tokens * out_rate) / 1_000_000


# --- Provider implementations ---

class BaseLLMProvider(ABC):
    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        pass


class AnthropicProvider(BaseLLMProvider):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        sys_prompt = request.system_prompt or request.config.system_prompt
        kwargs = dict(
            model=request.config.model,
            max_tokens=request.config.max_tokens,
            messages=[m.model_dump() for m in request.messages],
        )
        if sys_prompt:
            kwargs["system"] = sys_prompt
        response = await client.messages.create(**kwargs)
        return LLMResponse(
            content=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=request.config.model,
            provider="anthropic",
        )


class OpenRouterProvider(BaseLLMProvider):
    """OpenAI-compatible provider pointing at OpenRouter."""
    async def complete(self, request: LLMRequest) -> LLMResponse:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )
        # request-level system_prompt takes priority over config-level
        sys_prompt = request.system_prompt or request.config.system_prompt
        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages += [m.model_dump() for m in request.messages]

        kwargs: dict = dict(
            model=request.config.model,
            messages=messages,
            max_tokens=request.config.max_tokens,
            temperature=request.config.temperature,
        )
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await client.chat.completions.create(**kwargs)
        return LLMResponse(
            content=response.choices[0].message.content,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            model=request.config.model,
            provider="openrouter",
        )


class OpenAIProvider(BaseLLMProvider):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError("Direct OpenAI provider not yet implemented — use openrouter")


class GeminiProvider(BaseLLMProvider):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError("Gemini provider not yet implemented")


# --- LLMClient — single entry point for all nodes ---

class LLMClient:
    _providers: dict[str, BaseLLMProvider] = {
        "anthropic":  AnthropicProvider(),
        "openrouter": OpenRouterProvider(),
        "openai":     OpenAIProvider(),
        "gemini":     GeminiProvider(),
    }

    async def complete(self, request: LLMRequest) -> LLMResponse:
        provider = self._providers.get(request.config.provider)
        if not provider:
            raise ValueError(f"Unknown provider: {request.config.provider}")
        return await provider.complete(request)


# Module-level singleton
_client: Optional[LLMClient] = None

def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
