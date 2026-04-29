"""ADK web discovery wrapper.

``adk web <agents_dir>`` expects each subdirectory of ``agents_dir`` to be
one agent with ``__init__.py`` and ``agent.py`` exposing ``root_agent``.
The actual ``root_agent`` for this pipeline lives in the project's
``main.py``; this package re-exports it so ``adk web .`` (run from the
project root) discovers the pipeline as a single agent named ``pipeline``.
"""

from .agent import root_agent

__all__ = ["root_agent"]
