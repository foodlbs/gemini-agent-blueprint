"""Veo smoke test: generate one 4-second 16:9 clip. EXPENSIVE.

Veo Fast costs ~$2.40 for an 8s clip (~$1.20 for a 4s clip). Skipped
unless ``--include-veo`` is passed AND ``GOOGLE_CLOUD_PROJECT`` is set.

Usage:
    uv run python tests/smoke/veo_smoke.py --include-veo

Exit code 0 = MP4 received and saved (size > 100KB).
Exit code 1 = no video returned or output too small.
"""

import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.veo import generate_video, reset_client  # noqa: E402


def main() -> int:
    if "--include-veo" not in sys.argv:
        print("SKIP: pass --include-veo to opt into Veo (costs ~$1.20/run)")
        return 0
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        print("SKIP: GOOGLE_CLOUD_PROJECT not set")
        return 0

    reset_client(None)
    print("Generating one 4-second 16:9 clip via Veo (this may take 1–3 minutes)...")
    try:
        mp4 = generate_video(
            prompt="a small green cube rotating on a white background",
            duration_seconds=4,
            aspect_ratio="16:9",
        )
    except Exception as e:
        print(f"FAIL: generate_video: {e}")
        return 1

    out = "/tmp/veo_smoke.mp4"
    with open(out, "wb") as f:
        f.write(mp4)
    size = len(mp4)
    print(f"Wrote {size} bytes to {out}")
    if size < 100_000:
        print(f"FAIL: video suspiciously small ({size} bytes < 100KB)")
        return 1
    print("OK: Veo smoke test succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
