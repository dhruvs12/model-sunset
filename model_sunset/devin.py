"""Start a Devin session that runs the migration playbook on a repo.

Uses the Devin API v3: POST /v3/organizations/{org_id}/sessions with a service-user key.
Reference: https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.devin.ai/v3"
PLAYBOOK = Path(__file__).with_name("playbook.md")


def build_payload(repo: str, hits: list[dict], replacements: dict[str, str],
                  max_acu: int | None = None, playbook_id: str | None = None) -> dict:
    nearest = min(hit["days_left"] for hit in hits)
    chosen = json.dumps(replacements, indent=2) if replacements else (
        "none set. Use the `suggested` value on each scan hit. If a hit has none, stop and ask.")
    prompt = "\n".join([
        f"Migrate the repository {repo} off LLM models that are scheduled for shutdown.",
        "Follow the model-sunset playbook exactly. It is attached to this session." if playbook_id
        else "Follow the model-sunset playbook at the end of this message exactly.",
        "",
        f"Repository: {repo}",
        f"Replacement models chosen by the repo owner: {chosen}",
        "",
        "Scan results (`model-sunset scan --json`):",
        json.dumps(hits, indent=2),
    ])
    if not playbook_id:
        prompt += "\n\n----- PLAYBOOK -----\n" + PLAYBOOK.read_text()
    when = f"{-nearest}d past shutdown" if nearest < 0 else f"first shutdown in {nearest}d"
    payload: dict = {
        "prompt": prompt,
        "title": f"model-sunset: {repo} ({len(hits)} retiring model reference(s), {when})",
        "tags": ["model-sunset"],
    }
    if max_acu is not None:
        payload["max_acu_limit"] = max_acu  # hard cap on what this one session may consume
    if playbook_id:
        payload["playbook_id"] = playbook_id
    return payload


def start_session(payload: dict, org_id: str, api_key: str, api_base: str = API_BASE) -> dict:
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/organizations/{org_id}/sessions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Devin API returned HTTP {error.code}: {detail}") from None
