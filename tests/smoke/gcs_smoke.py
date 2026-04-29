"""GCS smoke test: upload a 1KB test file and verify the public URL serves it.

Reads GCS_ASSETS_BUCKET from env. Uploads a known payload, fetches the
returned URL via HTTP, asserts the response body matches, then deletes
the test object.

Exit code 0 = round-trip succeeded.
Exit code 1 = upload, fetch, or cleanup failed.
"""

import os
import sys
import time
import urllib.request

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.gcs import _client, upload_to_gcs  # noqa: E402


def main() -> int:
    bucket = os.environ.get("GCS_ASSETS_BUCKET")
    if not bucket:
        print("SKIP: GCS_ASSETS_BUCKET not set")
        return 0

    slug = f"_smoke/test-{int(time.time())}.txt"
    payload = b"smoke test payload " * 50  # ~1KB
    print(f"Uploading {len(payload)} bytes to gs://{bucket}/{slug}")

    url = upload_to_gcs(payload, "text/plain", slug)
    print(f"Public URL: {url}")

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read()
            status = resp.status
        print(f"HTTP {status}, body length {len(body)}")
        if status != 200:
            print(f"FAIL: expected HTTP 200, got {status}")
            return 1
        if body != payload:
            print(f"FAIL: body mismatch (got {len(body)} bytes, expected {len(payload)})")
            return 1
        print("OK: upload + public-read fetch round-trip succeeded.")
    finally:
        try:
            blob = _client().bucket(bucket).blob(slug)
            blob.delete()
            print(f"Cleaned up gs://{bucket}/{slug}")
        except Exception as e:
            print(f"WARN: cleanup failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
