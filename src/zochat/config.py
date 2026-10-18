"""Runtime configuration for ZoChat.

Loads environment variables from a local ``.env`` file with python-dotenv and
builds the default LLM model served through the Groq cloud's OpenAI-compatible
API.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from pydantic_ai.models.openai import OpenAIChatModel

DEFAULT_MODEL_NAME = "qwen/qwen3.8-27b"
# OpenAI-compatible base URL for the Groq cloud API.
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def get_groq_model() -> OpenAIChatModel:
    """Build the default pydantic-ai model wired to the Groq cloud provider.

    Groq exposes an OpenAI-compatible endpoint, so it is mounted via
    :class:`pydantic_ai.models.openai.OpenAIChatModel` + an
    :class:`~pydantic_ai.providers.openai.OpenAIProvider` configured with
    ``GROQ_API_KEY`` and ``GROQ_BASE_URL`` loaded from the environment.

    Reasoning is disabled by default (``reasoning_effort=none``) so the model
    emits its structured JSON reply directly rather than a chain-of-thought.

    ``load_dotenv()`` is called here (not at module import) so importing this
    module stays side-effect-free -- the test suite and other importers don't
    get ``.env`` secrets leaking into ``os.environ``. Real env vars keep
    precedence over ``.env`` values via python-dotenv's default
    ``override=False``.

    Raises:
        RuntimeError: If ``GROQ_API_KEY`` is not in the environment or ``.env``.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.settings import ModelSettings

    load_dotenv()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to a .env file in the project "
            "root (see .env.example) or export it in your shell."
        )

    base_url = os.environ.get("GROQ_BASE_URL") or DEFAULT_GROQ_BASE_URL
    provider = OpenAIProvider(api_key=api_key, base_url=base_url)
    from pydantic_ai.profiles import ModelProfile, merge_profile

    return OpenAIChatModel(
        DEFAULT_MODEL_NAME,
        provider=provider,
        profile=lambda base: merge_profile(
            base, ModelProfile(supports_json_object_output=False)
        ),
        settings=ModelSettings(extra_body={"reasoning_effort": "none"}),
    )
