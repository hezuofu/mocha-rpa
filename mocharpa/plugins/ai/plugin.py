"""AI plugin — unified interface to LLM providers for RPA automation.

Supports Anthropic Claude (built-in) and OpenAI (optional).  Uses the
respective SDK when available, with automatic fallback to the
``anthropic`` package.

API keys are resolved in order:
    1. Constructor argument ``api_key``
    2. Environment variable (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``)
    3. Config file via :class:`MocharpaConfig`

Usage::

    from mocharpa.plugins.ai.plugin import AIPlugin, AnthropicProvider

    ai = AIPlugin(provider=AnthropicProvider(model="claude-sonnet-4-6"))
    ai.initialize(None)

    result = ai.generate("Summarise this page", content=page_text)
    data = ai.extract(page_text, schema={"name": "str", "price": "float"})
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from mocharpa.plugins.base import Plugin

logger = logging.getLogger("rpa.ai")


# ======================================================================
# Provider abstraction
# ======================================================================

class AIProvider(ABC):
    """Abstract provider for LLM backends.

    Subclass to add new providers (OpenAI, local models, etc.).
    """

    def __init__(self, model: str = "", **kwargs: Any) -> None:
        self.model = model

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        """Send a prompt and return the generated text."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider's dependencies are installed."""


# ======================================================================
# Anthropic (Claude)
# ======================================================================

class AnthropicProvider(AIProvider):
    """Provider for Anthropic Claude models.

    Args:
        model: Claude model ID (default ``"claude-sonnet-4-6"``).
        api_key: Anthropic API key (defaults to ``ANTHROPIC_API_KEY`` env var).
        max_retries: Number of retries on transient errors.
        base_url: Optional custom API base URL.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str = "",
        max_retries: int = 3,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, **kwargs)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._max_retries = max_retries
        self._base_url = base_url
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic  # type: ignore
                kwargs: Dict[str, Any] = {"api_key": self.api_key, "max_retries": self._max_retries}
                if self._base_url:
                    kwargs["base_url"] = self._base_url
                self._client = anthropic.Anthropic(**kwargs)
            except ImportError:
                raise ImportError(
                    "Anthropic provider requires 'anthropic' package.\n"
                    "Install with: pip install anthropic"
                ) from None
        return self._client

    def is_available(self) -> bool:
        try:
            import anthropic  # noqa: F401
            return bool(self.api_key)
        except ImportError:
            return False

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        client = self._get_client()
        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

        kwargs: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=messages,
            temperature=temperature,
        )
        if system:
            kwargs["system"] = system

        logger.debug("Anthropic call: model=%s prompt_len=%d system_len=%d",
                     self.model, len(prompt), len(system))

        response = client.messages.create(**kwargs)
        text = response.content[0].text

        # If JSON mode requested, try to extract JSON from response
        if json_mode:
            text = _extract_json(text)

        return text


# ======================================================================
# OpenAI (optional)
# ======================================================================

class OpenAIProvider(AIProvider):
    """Provider for OpenAI models (GPT-4, GPT-4o, etc.).

    Args:
        model: OpenAI model ID (default ``"gpt-4o"``).
        api_key: OpenAI API key (defaults to ``OPENAI_API_KEY`` env var).
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, **kwargs)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI  # type: ignore
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "OpenAI provider requires 'openai' package.\n"
                    "Install with: pip install openai"
                ) from None
        return self._client

    def is_available(self) -> bool:
        try:
            from openai import OpenAI  # noqa: F401
            return bool(self.api_key)
        except ImportError:
            return False

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        client = self._get_client()
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: Dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""


# ======================================================================
# AIPlugin
# ======================================================================

class AIPlugin:
    """Plugin providing AI/LLM capabilities to RPA pipelines.

    Attributes:
        name: Plugin identifier (``"ai"``).
        provider: The underlying :class:`AIProvider` instance.

    Usage::

        ai = AIPlugin(provider=AnthropicProvider(model="claude-sonnet-4-6"))
        ai.initialize(ctx)

        # Generate text
        reply = ai.generate("Write a summary", content=page_text)

        # Extract structured data
        data = ai.extract(html, schema={"title": "str", "price": "float"})

        # Classify
        label = ai.classify(text, categories=["positive", "negative", "neutral"])

        # Make a decision
        ok = ai.decide("Does this page contain a login form?", content=page_text)
    """

    name = "ai"

    def __init__(
        self,
        provider: Optional[AIProvider] = None,
        *,
        default_model: str = "claude-sonnet-4-6",
        api_key: str = "",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self._provider = provider
        self._default_model = default_model
        self._api_key = api_key
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._context: Any = None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def initialize(self, context: Any) -> None:
        self._context = context
        if self._provider is None:
            # Auto-detect: try Anthropic first, then OpenAI
            self._provider = _auto_detect_provider(
                self._default_model, self._api_key, self._max_retries
            )
        logger.info("AIPlugin initialized (provider=%s, model=%s)",
                    type(self._provider).__name__, self._provider.model)

    def cleanup(self) -> None:
        logger.info("AIPlugin cleaned up")

    @property
    def provider(self) -> AIProvider:
        if self._provider is None:
            raise RuntimeError("AIPlugin not initialized")
        return self._provider

    # ------------------------------------------------------------------
    # High-level API
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        content: str = "",
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Generate text from a prompt.

        Args:
            prompt: The instruction or question.
            content: Optional context / data to include (appended to prompt).
            system: System prompt.
            temperature: Creativity (0–1).
            max_tokens: Max output length.

        Returns:
            Generated text.
        """
        full_prompt = prompt
        if content:
            full_prompt = f"{prompt}\n\nContent:\n{content}"

        return self._call_with_retry(
            lambda: self.provider.complete(
                full_prompt, system=system,
                temperature=temperature, max_tokens=max_tokens,
            )
        )

    def extract(
        self,
        content: str,
        schema: Dict[str, str],
        *,
        system: str = "",
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """Extract structured data from *content* according to a *schema*.

        Args:
            content: The text to extract from (HTML, plain text, etc.).
            schema: Dict mapping field names to type descriptions, e.g.
                ``{"name": "str", "age": "int", "emails": "list[str]"}``.
            system: Optional system prompt override.
            temperature: Set to 0 for deterministic extraction.

        Returns:
            Parsed dict matching the schema, or empty dict on failure.

        Usage::

            data = ai.extract(page_text, schema={"title": "str", "price": "float"})
            # → {"title": "Widget", "price": 9.99}
        """
        schema_desc = ", ".join(f"{k}: {v}" for k, v in schema.items())
        default_system = (
            "You are a data extraction tool. Extract the requested fields "
            "from the content and return ONLY valid JSON. Do not add commentary."
        )
        prompt = (
            f"Extract the following fields as JSON:\n{schema_desc}\n\n"
            f"Return ONLY a JSON object with these keys. "
            f"If a field is not found, use null.\n\n"
            f"Content:\n{content}"
        )

        result = self._call_with_retry(
            lambda: self.provider.complete(
                prompt, system=system or default_system,
                temperature=temperature, json_mode=True,
            )
        )

        try:
            parsed = json.loads(result)
            return {k: parsed.get(k) for k in schema}
        except json.JSONDecodeError:
            logger.warning("extract: failed to parse JSON from response")
            return {}

    def classify(
        self,
        content: str,
        categories: List[str],
        *,
        system: str = "",
        temperature: float = 0.0,
    ) -> str:
        """Classify *content* into one of the given *categories*.

        Args:
            content: Text to classify.
            categories: List of possible labels.
            system: Optional system prompt.
            temperature: Use 0 for consistency.

        Returns:
            The matched category (guaranteed to be one of *categories*),
            or the first category as fallback.
        """
        cats_str = ", ".join(categories)
        default_system = (
            "You are a classification tool. Reply with EXACTLY ONE of the "
            f"following words and nothing else: {cats_str}."
        )
        prompt = f"Classify this content: {content}"

        result = self._call_with_retry(
            lambda: self.provider.complete(
                prompt, system=system or default_system,
                temperature=temperature, max_tokens=50,
            )
        )

        result = result.strip().lower()
        for cat in categories:
            if cat.lower() in result:
                return cat
        return categories[0]

    def decide(
        self,
        question: str,
        *,
        content: str = "",
        system: str = "",
        temperature: float = 0.0,
    ) -> bool:
        """Make a yes/no decision.

        Args:
            question: The decision question.
            content: Optional context to base the decision on.
            system: Optional system prompt.
            temperature: Use 0 for consistency.

        Returns:
            ``True`` or ``False``.
        """
        default_system = (
            "You are a decision-making tool. Reply with EXACTLY 'yes' or 'no' "
            "and nothing else."
        )
        prompt = question
        if content:
            prompt = f"{question}\n\nContext:\n{content}"

        result = self._call_with_retry(
            lambda: self.provider.complete(
                prompt, system=system or default_system,
                temperature=temperature, max_tokens=10,
            )
        )

        return result.strip().lower().startswith("yes")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_with_retry(self, fn) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    wait = self._retry_delay * (2 ** attempt)
                    logger.debug("AI call retry %d/%d after %.1fs (%s)",
                                 attempt + 1, self._max_retries, wait, exc)
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]


# ======================================================================
# Helpers
# ======================================================================

def _auto_detect_provider(
    default_model: str,
    api_key: str,
    max_retries: int,
) -> AIProvider:
    """Try Anthropic first, then OpenAI.  Raise if neither is available."""
    ant_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if ant_key:
        try:
            import anthropic  # noqa: F401
            return AnthropicProvider(
                model=default_model, api_key=ant_key, max_retries=max_retries,
            )
        except ImportError:
            pass

    oai_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if oai_key:
        try:
            from openai import OpenAI  # noqa: F401
            model = "gpt-4o" if default_model.startswith("claude") else default_model
            return OpenAIProvider(model=model, api_key=oai_key)
        except ImportError:
            pass

    raise RuntimeError(
        "No AI provider available. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, "
        "or install the corresponding SDK (pip install anthropic / openai)."
    )


def _extract_json(text: str) -> str:
    """Try to extract a JSON object from model output."""
    # Try direct parse first
    text = text.strip()
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    # Try code block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Try brace matching
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return m.group(0)
    return text
