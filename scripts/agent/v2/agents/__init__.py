"""v2 phase prompt library.

The runtime uses one Claude SDK agent. The modules here provide phase prompts:

    - ``single.identity_prompt()`` — the single runtime agent identity.
    - ``researcher`` / ``developer`` / ``analyst`` — phase task builders.
    - Task-prompt builders — dynamic per-iteration instructions.

Prompts deliberately reference the bounded enums from ``config/`` so the
single agent has a single authoritative vocabulary.
"""

from . import analyst, developer, researcher, single  # noqa: F401
