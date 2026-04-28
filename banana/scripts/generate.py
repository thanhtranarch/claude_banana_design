#!/usr/bin/env python3
"""Banana Claude -- Direct API Fallback: Image Generation

Generate images via Gemini REST API when MCP is unavailable.
Uses only Python stdlib (no pip dependencies).

Usage:
    generate.py --prompt "a cat in space" [--aspect-ratio 16:9] [--resolution 1K]
                [--model MODEL] [--api-key KEY] [--thinking LEVEL] [--image-only]
                [--project PROJECT_NAME]

Token rotation: if no --api-key is given, reads from ~/.banana/tokens.json
and automatically switches to the next token when daily quota is hit.
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import token_manager as tm

DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_RESOLUTION = "2K"  # Must be uppercase -- lowercase values are silently rejected by the API
DEFAULT_RATIO = "1:1"
OUTPUT_BASE = Path.home() / "Documents" / "nanobanana_generated"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

VALID_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2",
                "4:5", "5:4", "1:4", "4:1", "1:8", "8:1", "21:9"}
VALID_RESOLUTIONS = {"512", "1K", "2K", "4K"}


def resolve_output_dir(project: str | None) -> Path:
    """Build output path: OUTPUT_BASE/<project>/<YYYY-MM-DD>/"""
    if not project:
        project = Path.cwd().name
    project = re.sub(r"[^\w\-]", "_", project).strip("_") or "default"
    date_str = datetime.now().strftime("%Y-%m-%d")
    return OUTPUT_BASE / project / date_str


def _call_api(url: str, data: bytes) -> dict:
    """Single API call, returns parsed JSON or raises HTTPError/URLError."""
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _is_daily_quota(error_body: str) -> bool:
    return "GenerateRequestsPerDayPerProjectPerModel" in error_body


def generate_image(prompt, model, aspect_ratio, resolution, api_key,
                   thinking_level=None, image_only=False, project=None):
    """Call Gemini API to generate an image, with token rotation on daily quota."""

    modalities = ["IMAGE"] if image_only else ["TEXT", "IMAGE"]
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": modalities,
            "imageConfig": {"aspectRatio": aspect_ratio, "imageSize": resolution},
        },
    }
    if thinking_level:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking_level}
    data = json.dumps(body).encode("utf-8")

    # Build token list: explicit key first, then pool
    keys_to_try = []
    if api_key:
        keys_to_try.append(("explicit", api_key))
    pool_key = tm.get_active_key()
    if pool_key and pool_key != api_key:
        keys_to_try.append(("pool", pool_key))

    if not keys_to_try:
        print(json.dumps({"error": True, "message": "No API key available. Add keys with: token_manager.py add KEY"}))
        sys.exit(1)

    for source, key in keys_to_try:
        url = f"{API_BASE}/{model}:generateContent?key={key}"
        rpm_retries = 3

        for attempt in range(rpm_retries):
            try:
                result = _call_api(url, data)
                # Success — extract and save image
                candidates = result.get("candidates", [])
                if not candidates:
                    reason = result.get("promptFeedback", {}).get("blockReason", "UNKNOWN")
                    print(json.dumps({"error": True, "message": f"No candidates. Reason: {reason}"}))
                    sys.exit(1)

                parts = candidates[0].get("content", {}).get("parts", [])
                image_data, text_response = None, ""
                for part in parts:
                    if "inlineData" in part:
                        image_data = part["inlineData"]["data"]
                    elif "text" in part:
                        text_response = part["text"]

                if not image_data:
                    finish_reason = candidates[0].get("finishReason", "UNKNOWN")
                    print(json.dumps({"error": True, "message": f"No image in response. finishReason: {finish_reason}"}))
                    sys.exit(1)

                output_dir = resolve_output_dir(project)
                output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                output_path = (output_dir / f"banana_{timestamp}.png").resolve()
                with open(output_path, "wb") as f:
                    f.write(base64.b64decode(image_data))

                return {
                    "path": str(output_path),
                    "model": model,
                    "aspect_ratio": aspect_ratio,
                    "resolution": resolution,
                    "token_used": key[:12] + "...",
                    "text": text_response,
                }

            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8") if e.fp else ""

                if e.code == 429:
                    if _is_daily_quota(error_body):
                        # Daily quota exhausted — rotate to next token
                        print(json.dumps({"info": f"Daily quota exhausted on {key[:12]}..., rotating token"}), file=sys.stderr)
                        if source == "pool":
                            next_key = tm.mark_exhausted(key)
                            if next_key:
                                key = next_key
                                url = f"{API_BASE}/{model}:generateContent?key={key}"
                                print(json.dumps({"info": f"Switched to next token: {key[:12]}..."}), file=sys.stderr)
                                attempt = 0  # reset RPM retries for new key
                                continue
                        break  # No more pool keys, try next in keys_to_try

                    elif attempt < rpm_retries - 1:
                        # RPM limit — wait and retry same key
                        wait = 2 ** (attempt + 1)
                        print(json.dumps({"retry": True, "attempt": attempt + 1, "wait_seconds": wait, "reason": "rpm_limit"}), file=sys.stderr)
                        time.sleep(wait)
                        continue

                if e.code == 400 and "FAILED_PRECONDITION" in error_body:
                    print(json.dumps({"error": True, "status": 400, "message": "Billing not enabled. Enable at https://aistudio.google.com/apikey"}))
                    sys.exit(1)

                print(json.dumps({"error": True, "status": e.code, "message": error_body}))
                sys.exit(1)

            except urllib.error.URLError as e:
                print(json.dumps({"error": True, "message": str(e.reason)}))
                sys.exit(1)

    print(json.dumps({"error": True, "message": "All tokens exhausted for today. Add more keys: token_manager.py add KEY"}))
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Generate images via Gemini REST API")
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--aspect-ratio", default=DEFAULT_RATIO, help=f"Aspect ratio (default: {DEFAULT_RATIO})")
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION, help=f"Resolution: 512, 1K, 2K, 4K (default: {DEFAULT_RESOLUTION})")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--api-key", default=None, help="Override API key (bypasses token pool)")
    parser.add_argument("--thinking", default=None, choices=["minimal", "low", "medium", "high"], help="Thinking level")
    parser.add_argument("--image-only", action="store_true", help="Return image only (no text)")
    parser.add_argument("--project", default=None, help="Project name for output folder (default: current directory name)")

    args = parser.parse_args()

    if args.aspect_ratio not in VALID_RATIOS:
        print(json.dumps({"error": True, "message": f"Invalid aspect ratio '{args.aspect_ratio}'. Valid: {sorted(VALID_RATIOS)}"}))
        sys.exit(1)
    if args.resolution not in VALID_RESOLUTIONS:
        print(json.dumps({"error": True, "message": f"Invalid resolution '{args.resolution}'. Valid: {sorted(VALID_RESOLUTIONS)}"}))
        sys.exit(1)

    api_key = args.api_key or os.environ.get("GOOGLE_AI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    result = generate_image(
        prompt=args.prompt,
        model=args.model,
        aspect_ratio=args.aspect_ratio,
        resolution=args.resolution,
        api_key=api_key,
        thinking_level=args.thinking,
        image_only=args.image_only,
        project=args.project,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
