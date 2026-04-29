"""Imagen smoke test: generate one 16:9 illustration.

Reads GOOGLE_CLOUD_PROJECT (and optionally GOOGLE_CLOUD_LOCATION). Calls
``generate_image`` with a small fixed prompt, writes the resulting bytes
to ``/tmp/imagen_smoke.png``, prints the file size.

Exit code 0 = generated and saved (size > 10KB).
Exit code 1 = no image returned, or image too small to be real.
"""

import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.imagen import generate_image, reset_client  # noqa: E402


def main() -> int:
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        print("SKIP: GOOGLE_CLOUD_PROJECT not set")
        return 0

    reset_client(None)  # ensure fresh client picks up env vars
    print("Generating one 16:9 illustration via Vertex AI Imagen...")
    try:
        png = generate_image(
            prompt="a small green cube on a white background",
            aspect_ratio="16:9",
            style="illustration",
        )
    except Exception as e:
        print(f"FAIL: generate_image: {e}")
        return 1

    out = "/tmp/imagen_smoke.png"
    with open(out, "wb") as f:
        f.write(png)
    size = len(png)
    print(f"Wrote {size} bytes to {out}")
    if size < 10_000:
        print(f"FAIL: image suspiciously small ({size} bytes < 10KB)")
        return 1
    print("OK: Imagen smoke test succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
