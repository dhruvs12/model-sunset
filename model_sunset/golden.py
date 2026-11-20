"""Golden sets: freeze the old model's outputs, then diff a replacement model against them.

Input file (JSONL), one request per line:
    {"id": "refund-1", "messages": [...], "tools": [...], "response_format": {...}, "meta": {...}}
Everything except "id" and "meta" is sent to the model as-is.

Golden file (JSONL), one record per line:
    {"id", "request", "model", "output": {"content", "tool_calls"}, "captured_at"}
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Callable

from .llm import chat

Chat = Callable[[str, dict], dict]  # (model, request) -> {"content", "tool_calls"}

JUDGE_PROMPT = """You are comparing two responses to the same request.
Decide which response serves the person who sent the request better.
Judge correctness, completeness and whether the instructions in the request were followed.
Ignore differences in wording that would not matter to that person.

Request:
{request}

Response A:
{a}

Response B:
{b}

Reply with JSON only: {{"winner": "A" or "B" or "tie", "reason": "one sentence"}}"""


def read_jsonl(path: Path | str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_jsonl(path: Path | str, records: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))


def ensure_alive(model: str, schedule: dict[str, dict], role: str) -> None:
    """Refuse to migrate onto (or judge with) a model that is itself on the shutdown list."""
    if model in schedule:
        raise ValueError(f"{role} model {model!r} is itself scheduled for shutdown on "
                         f"{schedule[model]['shutdown']}. Pick a model that is not on the list.")


# ---------- capture ----------

def capture(inputs: list[dict], model: str, ask: Chat) -> list[dict]:
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    records = []
    for case in inputs:
        request = {key: value for key, value in case.items() if key not in ("id", "meta")}
        records.append({"id": case["id"], "request": request, "model": model,
                        "output": ask(model, request), "captured_at": stamp})
    return records


# ---------- checks ----------

def kind(value) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "null" if value is None else "string"


def structure_diff(old, new, path: str = "$") -> list[str]:
    """Compare the shape of two JSON values: keys and types, never the values themselves."""
    if old is None or new is None:
        return []  # a null says nothing about the field's type, so it matches anything
    if kind(old) != kind(new):
        return [f"{path}: {kind(old)} -> {kind(new)}"]
    if isinstance(old, dict):
        problems = []
        for key in sorted(old.keys() | new.keys()):
            if key not in new:
                problems.append(f"{path}.{key}: missing")
            elif key not in old:
                problems.append(f"{path}.{key}: new key")
            else:
                problems += structure_diff(old[key], new[key], f"{path}.{key}")
        return problems
    if isinstance(old, list) and old and new:
        return structure_diff(old[0], new[0], f"{path}[]")  # first element stands for the rest
    return []


def parse_structured(text: str | None):
    """Return the parsed value if `text` is a JSON object or array, else None. Deliberately strict:
    if the old output parsed with json.loads and the new one arrives wrapped in a code fence,
    the caller's parser breaks, and that is a regression."""
    try:
        value = json.loads(text or "")
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) else None


def tool_call_diff(old_calls: list[dict], new_calls: list[dict]) -> list[str]:
    old_names = [call["name"] for call in old_calls]
    new_names = [call["name"] for call in new_calls]
    if old_names != new_names:
        return [f"tool calls: {old_names} -> {new_names}"]
    problems = []
    for old, new in zip(old_calls, new_calls):
        new_args = parse_structured(new["arguments"])
        if new_args is None:
            problems.append(f"{new['name']}(): arguments are not a JSON object")
        else:
            problems += structure_diff(parse_structured(old["arguments"]) or {}, new_args, f"{old['name']}()")
    return problems


def judge_pair(request: dict, old_text: str, new_text: str, judge: Callable[[str], str]) -> tuple[str, list[str]]:
    """Blind pairwise judgement, asked twice with the positions swapped.
    fail = the old output wins in both orders. pass = the old output wins in neither.
    review = the judge changed its mind when the order changed."""
    shown = json.dumps(request.get("messages", request), ensure_ascii=False)[:6000]
    winners, reasons = [], []
    for a_is_old in (True, False):
        a, b = (old_text, new_text) if a_is_old else (new_text, old_text)
        reply = judge(JUDGE_PROMPT.format(request=shown, a=a, b=b))
        try:
            verdict = json.loads(reply[reply.index("{"):reply.rindex("}") + 1])
            letter = str(verdict["winner"]).strip().upper()
        except (ValueError, KeyError, TypeError):
            return "review", ["judge reply was not the requested JSON"]
        if letter not in ("A", "B", "TIE"):
            return "review", [f"judge returned winner={letter!r}"]
        winners.append("tie" if letter == "TIE" else "old" if (letter == "A") == a_is_old else "new")
        reasons.append(str(verdict.get("reason", "")))
    if winners == ["old", "old"]:
        return "fail", ["judge preferred the old output in both orders: " + reasons[0]]
    if "old" not in winners:
        return "pass", [f"judge: {winners[0]} / {winners[1]}"]
    return "review", [f"judge was inconsistent across orders: {winners[0]} / {winners[1]}"]


def check_case(golden: dict, new_output: dict, judge: Callable[[str], str] | None) -> dict:
    """Pick the check from what the old model produced: tool calls, JSON, or free text."""
    old_output = golden["output"]
    if old_output["tool_calls"]:
        name, problems = "tool-calls", tool_call_diff(old_output["tool_calls"], new_output["tool_calls"])
        status = "fail" if problems else "pass"
    elif (old_json := parse_structured(old_output["content"])) is not None:
        name = "schema"
        new_json = parse_structured(new_output["content"])
        problems = ["output is no longer a JSON object or array"] if new_json is None \
            else structure_diff(old_json, new_json)
        status = "fail" if problems else "pass"
    else:
        name = "text"
        old_text, new_text = (old_output["content"] or "").strip(), (new_output["content"] or "").strip()
        if old_text == new_text:
            status, problems = "pass", ["identical"]
        elif judge is None:
            status, problems = "review", ["text differs and no --judge-model was given"]
        else:
            status, problems = judge_pair(golden["request"], old_text, new_text, judge)
    return {"id": golden["id"], "check": name, "status": status, "notes": problems,
            "old": old_output, "new": new_output}


# ---------- diff ----------

def diff(golden: list[dict], to_model: str, ask: Chat, judge: Callable[[str], str] | None = None) -> list[dict]:
    return [check_case(record, ask(to_model, record["request"]), judge) for record in golden]


def show(output: dict, limit: int = 600) -> str:
    text = json.dumps(output["tool_calls"]) if output["tool_calls"] else (output["content"] or "")
    return text if len(text) <= limit else text[:limit] + " ..."


def render_report(golden: list[dict], results: list[dict], to_model: str, judge_model: str | None) -> str:
    old_models = ", ".join(sorted({record["model"] for record in golden}))
    counts = {status: sum(r["status"] == status for r in results) for status in ("pass", "fail", "review")}
    lines = [
        f"# model-sunset diff: {old_models} -> {to_model}",
        "",
        f"{len(results)} golden case(s), captured {golden[0]['captured_at'] if golden else 'n/a'}. "
        f"Judge for free text: {judge_model or 'none'}.",
        "",
        f"**{counts['pass']} pass, {counts['fail']} fail, {counts['review']} need review**",
        "",
        "| case | check | result | notes |",
        "|---|---|---|---|",
    ]
    for r in results:
        notes = "; ".join(r["notes"]).replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['check']} | {r['status']} | {notes} |")
    flagged = [r for r in results if r["status"] != "pass"]
    if flagged:
        lines += ["", "## Cases to look at"]
        for r in flagged:
            lines += ["", f"### {r['id']} ({r['status']})", "", "Old model:", "", "```", show(r["old"]), "```",
                      "", "Replacement:", "", "```", show(r["new"]), "```"]
    return "\n".join(lines) + "\n"


def make_chat(base_url: str | None, api_key: str | None) -> Chat:
    return lambda model, request: chat(model, request, base_url, api_key)


def make_judge(model: str, base_url: str | None, api_key: str | None) -> Callable[[str], str]:
    def judge(prompt: str) -> str:
        return chat(model, {"messages": [{"role": "user", "content": prompt}]}, base_url, api_key)["content"] or ""
    return judge
