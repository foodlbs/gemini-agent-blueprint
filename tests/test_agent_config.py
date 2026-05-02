import importlib
import os
from unittest.mock import patch


def test_workflow_name_default_is_gemini_agent_blueprint():
    with patch.dict(os.environ, {}, clear=True):
        # Re-import agent so module-level Workflow() uses the patched env.
        import agent
        importlib.reload(agent)
        assert agent.root_agent.name == "gemini_agent_blueprint"


def test_workflow_name_overrides_via_env():
    with patch.dict(os.environ, {"PROJECT_APP_NAME": "my_workflow"}, clear=True):
        import agent
        importlib.reload(agent)
        assert agent.root_agent.name == "my_workflow"
