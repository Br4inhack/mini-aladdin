"""
apps/portfolio/llm_client.py

Thin wrapper around the OpenAI-compatible SDK for both Google Gemini
and Groq. Primary provider is Gemini; Groq is the automatic fallback.
"""

import logging
import os

from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMAPIError(Exception):
    """Raised when every configured LLM provider fails."""


class LLMClient:
    """
    OpenAI-SDK-compatible client with Gemini as primary and Groq as fallback.

    Models and token limits are read from ``settings.CRPMS`` so they can be
    changed without touching code.
    """

    def __init__(self) -> None:
        gemini_key = os.environ.get('GEMINI_API_KEY', '')
        if not gemini_key:
            logger.warning('LLMClient: GEMINI_API_KEY not set — primary provider will fail')

        groq_key = os.environ.get('GROQ_API_KEY', '')
        if not groq_key:
            logger.warning('LLMClient: GROQ_API_KEY not set — fallback provider will fail')

        self.primary_client = OpenAI(
            api_key=gemini_key,
            base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
        )
        self.fallback_client = OpenAI(
            api_key=groq_key,
            base_url='https://api.groq.com/openai/v1',
        )

        crpms = getattr(settings, 'CRPMS', {})
        self.primary_model  = crpms.get('LLM_PRIMARY_MODEL',  'gemini-2.0-flash')
        self.fallback_model = crpms.get('LLM_FALLBACK_MODEL', 'llama-3.3-70b-versatile')
        self.max_tokens     = crpms.get('LLM_MAX_TOKENS',     800)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """
        Generate a completion via Gemini, falling back to Groq on failure.

        Args:
            system_prompt: Instruction context for the model.
            user_prompt:   The user-facing query or data payload.

        Returns:
            The model's text response.

        Raises:
            LLMAPIError: When both providers fail.
        """
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': user_prompt},
        ]

        # Primary: Gemini
        try:
            resp = self.primary_client.chat.completions.create(
                model=self.primary_model,
                max_tokens=self.max_tokens,
                messages=messages,
            )
            return resp.choices[0].message.content
        except Exception as exc:
            logger.warning('Gemini call failed, trying Groq: %s', exc)

        # Fallback: Groq
        try:
            resp = self.fallback_client.chat.completions.create(
                model=self.fallback_model,
                max_tokens=self.max_tokens,
                messages=messages,
            )
            return resp.choices[0].message.content
        except Exception as exc:
            logger.error('Both LLM providers failed: %s', exc)
            raise LLMAPIError('Both Gemini and Groq failed') from exc


# Module-level singleton — import and use directly:
#   from apps.portfolio.llm_client import llm_client
llm_client = LLMClient()
