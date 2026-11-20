"""Minimal client for any OpenAI-compatible /chat/completions endpoint. Standard library only."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def chat(model: str, request: dict, base_url: str | None = None, api_key: str | None = None,
         timeout: int = 300) -> dict:
    """Send {"model": model, **request} and return {"content": str | None, "tool_calls": [...]}.

    `request` is passed through untouched (messages, tools, response_format, ...), so the
    replacement model sees exactly what the old model saw.
    """
    base = (base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = json.dumps({"model": model, **request}).encode()
    http_request = urllib.request.Request(f"{base}/chat/completions", data=body, headers=headers)
    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        raise RuntimeError(f"{model}: HTTP {error.code} from {base}: {detail}") from None
    message = data["choices"][0]["message"]
    tool_calls = [{"name": call["function"]["name"], "arguments": call["function"]["arguments"]}
                  for call in message.get("tool_calls") or []]
    return {"content": message.get("content"), "tool_calls": tool_calls}
