"""Cloud Function: kick off one Cloud Run pipeline run.

Triggered by Pub/Sub (Cloud Scheduler hourly cron). The function POSTs to the
deployed Cloud Run service (``--no-allow-unauthenticated``) using an OIDC ID
token, opens a streaming run, drains the first few events to confirm the
pipeline started, then closes the connection. Cloud Run continues processing
the request until completion or its configured request timeout.

DESIGN.md note: The pipeline has 24-hour Telegram approval timeouts. Cloud
Run's max request timeout is 60 minutes. If a human gate blocks longer than
the deployed service timeout (currently 15 min), Cloud Run will terminate the
request and the pipeline state is lost. Agent Runtime is the architecturally
correct backend for 24-hour-blocking gates; Cloud Run is acceptable when
approval latency is short.
"""

import base64
import json
import logging
import os

import functions_framework
import google.auth.transport.requests
import requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@functions_framework.cloud_event
def trigger_pipeline(cloud_event):
    """Pub/Sub trigger entry point — POSTs to the Cloud Run service."""
    service_url = os.environ["CLOUD_RUN_SERVICE_URL"].rstrip("/")
    app_name = os.environ.get("APP_NAME", "app")

    payload = _decode_pubsub_payload(cloud_event)
    logger.info("Triggering Cloud Run service %s; payload=%s", service_url, payload)

    auth_req = google.auth.transport.requests.Request()
    token = id_token.fetch_id_token(auth_req, service_url)
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    user_id = "scheduler"
    session_url = f"{service_url}/apps/{app_name}/users/{user_id}/sessions"
    session_resp = requests.post(
        session_url,
        headers=auth_headers,
        json={"state": {"trigger": "scheduler", "source": payload.get("source", "scheduler")}},
        timeout=30,
    )
    session_resp.raise_for_status()
    session_id = session_resp.json()["id"]
    logger.info("Created session=%s", session_id)

    run_body = {
        "app_name": app_name,
        "user_id": user_id,
        "session_id": session_id,
        "new_message": {"role": "user", "parts": [{"text": "Run a polling cycle."}]},
        "streaming": True,
    }

    streamed = 0
    with requests.post(
        f"{service_url}/run_sse",
        headers=auth_headers,
        json=run_body,
        stream=True,
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if decoded.startswith("data: "):
                logger.info("event[%d]: %s", streamed, decoded[6:300])
                streamed += 1
                if streamed >= 5:
                    break

    logger.info(
        "Pipeline kicked off (session=%s, %d events streamed before detach).",
        session_id, streamed,
    )
    return "ok"


def _decode_pubsub_payload(cloud_event) -> dict:
    """Decode the Pub/Sub message body. Returns {} if absent or unparseable."""
    if not cloud_event.data or "message" not in cloud_event.data:
        return {}
    encoded = cloud_event.data["message"].get("data", "")
    if not encoded:
        return {}
    try:
        return json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, TypeError):
        return {"raw": encoded}
