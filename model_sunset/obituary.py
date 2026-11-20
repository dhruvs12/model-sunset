"""Write an obituary for each retiring model found in a repo.

Every line comes from data: the provider's schedule, the scan hits, and (if a golden set
exists) the old model's literal last words. It is meant for the top of the migration PR.
"""
from __future__ import annotations

from .scan import Hit


def last_words(model: str, golden: list[dict], limit: int = 280) -> tuple[str, str] | None:
    for record in golden:
        if record["model"] == model:
            output = record["output"]
            text = output["content"] or ", ".join(f"{c['name']}({c['arguments']})" for c in output["tool_calls"])
            text = " ".join(text.split())
            return record["id"], text if len(text) <= limit else text[:limit] + " ..."
    return None


def render(hits: list[Hit], golden: list[dict], sources: dict[str, str]) -> str:
    if not hits:
        return "No retiring models here. Nobody to mourn.\n"
    by_model: dict[str, list[Hit]] = {}
    for hit in hits:
        by_model.setdefault(hit.model, []).append(hit)
    sections = []
    for model, group in by_model.items():  # hits arrive sorted by days left, so the nearest death comes first
        first = group[0]
        files = {hit.file for hit in group}
        sites = ", ".join(f"`{hit.file}:{hit.line}`" for hit in group)
        if first.days_left < 0:
            fate = f"Shut down on {first.shutdown}, {-first.days_left} days ago. Every call below is already failing."
        else:
            fate = f"Shuts down on {first.shutdown}. {first.days_left} days left."
        lines = [
            f"### 🪦 {model}",
            "",
            f"{fate} ([{first.provider} schedule]({sources.get(first.provider, '')}))",
            "",
            f"Survived by {len(group)} call site(s) in {len(files)} file(s): {sites}",
            "",
            f"Successor named by the provider: `{first.suggested}`" if first.suggested
            else "The provider names no successor.",
            "",
        ]
        words = last_words(model, golden)
        if words:
            lines += [f"Last words (golden case `{words[0]}`):", "", f"> {words[1]}"]
        elif first.days_left < 0:
            lines += ["Last words: none. It was gone before anyone wrote them down."]
        else:
            lines += ["Last words: not captured yet. Run `model-sunset capture` while it can still answer."]
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + "\n"
