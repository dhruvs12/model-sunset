"""Scan a repo for hard-coded model ids that are scheduled for shutdown."""
from __future__ import annotations

import datetime as dt
import fnmatch
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SCHEDULE = Path(__file__).with_name("retirements.json")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".tox"}
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".go", ".rb", ".java", ".kt", ".rs",
            ".json", ".yaml", ".yml", ".toml", ".env", ".ini", ".cfg", ".md", ".txt", ".sh", ".ipynb"}
MAX_BYTES = 1_000_000  # skip minified bundles and data dumps


@dataclass
class Hit:
    file: str
    line: int
    model: str
    provider: str
    shutdown: str
    days_left: int        # negative once the shutdown date has passed
    suggested: str | None  # replacement named on the provider's page, if any
    alias: bool           # undated alias the page does not name; its dated snapshots are listed
    snippet: str


def load_schedule(path: Path | str = DEFAULT_SCHEDULE) -> dict[str, dict]:
    """Return {model id: schedule row}. One row can cover several ids."""
    rows = json.loads(Path(path).read_text())["models"]
    return {model_id: row for row in rows for model_id in row["ids"]}


def build_pattern(ids) -> re.Pattern:
    # Longest ids first, so "gpt-4o-mini" wins over "gpt-4o".
    # The id must stand alone: "gpt-5.1", "gpt-5-codex" and "gpt-4o-mini-tts" are different models,
    # but "openai/gpt-5", "ft:gpt-4o-mini-2024-07-18:acme" and "gpt-5." at the end of a sentence match.
    alternatives = "|".join(sorted(map(re.escape, ids), key=len, reverse=True))
    return re.compile(rf"(?<![\w.\-])({alternatives})(?![\w\-]|\.\w)")


def iter_files(root: Path, exclude: list[str]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel, pattern) for pattern in exclude):
                continue
            if (path.suffix in TEXT_EXT or name.startswith(".env")) and path.stat().st_size <= MAX_BYTES:
                yield path, rel


def scan(root: Path | str, schedule: dict[str, dict], today: dt.date | None = None,
         exclude: list[str] | None = None) -> list[Hit]:
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"{root} is not a directory")
    today = today or dt.date.today()
    pattern = build_pattern(schedule)
    hits: list[Hit] = []
    for path, rel in iter_files(root, exclude or []):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in pattern.finditer(line):
                row = schedule[match.group(1)]
                hits.append(Hit(
                    file=rel,
                    line=lineno,
                    model=match.group(1),
                    provider=row["provider"],
                    shutdown=row["shutdown"],
                    days_left=(dt.date.fromisoformat(row["shutdown"]) - today).days,
                    suggested=row.get("suggested"),
                    alias=bool(row.get("alias")),
                    snippet=line.strip()[:160],
                ))
    return sorted(hits, key=lambda h: (h.days_left, h.file, h.line))


def countdown(shutdown: str, days_left: int) -> str:
    if days_left < 0:
        return f"shut down {shutdown} (PAST SHUTDOWN, {-days_left}d ago)"
    return f"shuts down {shutdown} ({days_left}d left)"


def format_text(hits: list[Hit], today: dt.date) -> str:
    if not hits:
        return "No retiring model ids found."
    lines = [f"{len(hits)} retiring model reference(s) as of {today}:", ""]
    for h in hits:
        hint = f"  provider suggests: {h.suggested}" if h.suggested else ""
        lines.append(f"  {h.file}:{h.line}  {h.model}  {countdown(h.shutdown, h.days_left)}{hint}")
        if h.alias:
            lines.append("      note: alias not named on the provider's page; every dated snapshot of it is")
        lines.append(f"      {h.snippet}")
    return "\n".join(lines)
