"""Gemini 2.5 Flash call helper.

Pure POST-and-extract. No Splunk dependency, no secret fetching — the
caller supplies the API key (Splunk path: storage/passwords lookup;
offline path: os.environ["GOOGLE_API_KEY"]).

Vendored to /Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/llm.py.
"""

from __future__ import annotations

import json
import time
import urllib.request


GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)


def call_gemini(prompt: str, api_key: str, timeout: int = 30) -> tuple[str, int]:
    """POST a prompt to Gemini 2.5 Flash. Returns (text, latency_ms).

    Raises urllib.error.HTTPError on non-2xx response, or KeyError /
    IndexError if the response shape is unexpected. Caller decides
    whether to retry or surface the error.
    """
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(
        f"{GEMINI_ENDPOINT}?key={api_key}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    latency_ms = int((time.time() - start) * 1000)
    text = payload["candidates"][0]["content"]["parts"][0]["text"]
    return text.strip(), latency_ms
