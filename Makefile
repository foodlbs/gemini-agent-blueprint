.PHONY: setup run-local run-web eval deploy trigger logs clean

setup:
	uv sync

run-local:
	uv run adk run main:root_agent

run-web:
	uv run adk web

eval:
	uv run adk eval main:root_agent eval/eval_set.evalset.json

deploy:
	bash deploy/deploy.sh

trigger:
	gcloud scheduler jobs run ai-release-pipeline-hourly --location=$$GOOGLE_CLOUD_LOCATION

logs:
	gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine"' --limit=50 --format=json

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	rm -rf .venv build dist *.egg-info
