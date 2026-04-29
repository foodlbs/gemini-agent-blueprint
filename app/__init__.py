"""Vertex AI Agent CLI discovery wrapper.

The agent-cli (``adk deploy agent_engine`` and other Vertex AI tooling)
expects ``app.agent.root_agent``. This package re-exports ``root_agent``
from the project's ``main.py`` so deploy tooling resolves it without
requiring main.py to live inside an ``app/`` package.

Note: ``pipeline/`` provides the same wrapper for ``adk web``. We keep
both so each tool's discovery convention is satisfied without
restructuring the rest of the project.
"""

from .agent import root_agent

__all__ = ["root_agent"]
