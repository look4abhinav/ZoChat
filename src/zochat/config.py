"""Runtime configuration for ZoChat.

Loads environment variables from a local ``.env`` file with python-dotenv and
builds the default LLM model ``minimax-m3`` served by the OpenAI-compatible
Opencode Go gateway.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from pydantic_ai.models.openai import OpenAIChatModel

DEFAULT_MODEL_NAME = "minimax-m3"
# OpenAI-compatible base URL for the Opencode Go gateway. Used only when
# OPENCODE_BASE_URL is not otherwise configured. See .env.example.
DEFAULT_OPENCODE_BASE_URL = "https://opencode.ai/zen/go/v1"


def get_opencode_model() -> OpenAIChatModel:
    """Build the default pydantic-ai model wired to the Opencode Go provider.

    The Opencode Go gateway is OpenAI-compatible, so it is mounted via
    :class:`pydantic_ai.models.openai.OpenAIChatModel` + an
    :class:`~pydantic_ai.providers.openai.OpenAIProvider` configured with
    ``OPENCODE_API_KEY`` and ``OPENCODE_BASE_URL`` loaded from the environment.

    ``load_dotenv()`` is called here (not at module import) so importing this
    module stays side-effect-free — the test suite and other importers don't
    get ``.env`` secrets leaking into ``os.environ``. Real env vars keep
    precedence over ``.env`` values via python-dotenv's default ``override=False``.

    Raises:
        RuntimeError: If ``OPENCODE_API_KEY`` is not in the environment or ``.env``.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    load_dotenv()

    api_key = os.environ.get("OPENCODE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENCODE_API_KEY is not set. Add it to a .env file in the project "
            "root (see .env.example) or export it in your shell."
        )

    base_url = os.environ.get("OPENCODE_BASE_URL") or DEFAULT_OPENCODE_BASE_URL
    provider = OpenAIProvider(api_key=api_key, base_url=base_url)
    return OpenAIChatModel(DEFAULT_MODEL_NAME, provider=provider)
