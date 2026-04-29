# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0

"""Scaffold-generated chat-agent integration test.

This file was added by ``agents-cli scaffold enhance`` from a generic chat-agent
template. It does not apply to this project: ``root_agent`` is a polling
``SequentialAgent`` (Scout -> Triage -> Topic Gate -> ... -> Editor) triggered
by Cloud Scheduler, not a conversational agent that responds to ad-hoc user
questions like "Why is the sky blue?".

For the canonical end-to-end coverage of this pipeline, see:
- ``tests/test_root_agent.py`` (eight-stage SequentialAgent composition)
- ``tests/test_*.py`` (per-agent contract tests, 189 cases)
- ``tests/eval/evalsets/full_pipeline.evalset.json`` (live Telegram + Imagen + Veo)
- ``tests/eval/evalsets/triage_skip.evalset.json`` (low-significance filter)
"""

import pytest

pytest.skip(
    "Scaffold chat-agent template; this pipeline is polling-triggered, not "
    "conversational. See module docstring for the real coverage entry points.",
    allow_module_level=True,
)
