"""Tests for deploy.py configuration reads. We import the helpers so that
deploy.py's main() does not run at import time — main() requires Vertex
SDK init and a GCP project."""

import importlib
import os
from unittest.mock import patch


def _reload_deploy():
    import deploy
    return importlib.reload(deploy)


def test_display_name_default_is_blueprint():
    with patch.dict(os.environ, {}, clear=True):
        deploy = _reload_deploy()
        assert deploy.DISPLAY == "gemini-agent-blueprint"


def test_display_name_overrides_via_env():
    with patch.dict(os.environ, {"PROJECT_DISPLAY_NAME": "my-agent"}, clear=True):
        deploy = _reload_deploy()
        assert deploy.DISPLAY == "my-agent"


def test_app_name_default_is_blueprint():
    with patch.dict(os.environ, {}, clear=True):
        deploy = _reload_deploy()
        assert deploy.APP_NAME == "gemini_agent_blueprint"


def test_app_name_overrides_via_env():
    with patch.dict(os.environ, {"PROJECT_APP_NAME": "my_agent"}, clear=True):
        deploy = _reload_deploy()
        assert deploy.APP_NAME == "my_agent"


def test_project_name_default_is_gab():
    with patch.dict(os.environ, {}, clear=True):
        deploy = _reload_deploy()
        assert deploy.PROJECT_PREFIX == "gab"


def test_project_name_overrides_via_env():
    with patch.dict(os.environ, {"TF_VAR_project_name": "myagent"}, clear=True):
        deploy = _reload_deploy()
        assert deploy.PROJECT_PREFIX == "myagent"
