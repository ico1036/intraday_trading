"""v2 agent prompt library.

Each agent module exposes:

    - ``identity_prompt()`` — static system prompt (what the agent IS).
    - Task-prompt builders — dynamic per-iteration instructions.

Prompts deliberately reference the bounded enums from ``config/`` so the
agents have a single authoritative vocabulary.
"""

from . import analyst, developer, researcher  # noqa: F401
