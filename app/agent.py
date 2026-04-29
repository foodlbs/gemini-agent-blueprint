"""agent-cli entry point — re-exports ``root_agent`` from ``main``.

See ``../main.py`` for the actual ``SequentialAgent`` composition.
"""

from main import root_agent

__all__ = ["root_agent"]
