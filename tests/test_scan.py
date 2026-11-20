import datetime as dt
import json
from pathlib import Path

import pytest

from model_sunset import cli, scan

EXAMPLE = Path(__file__).parent.parent / "examples" / "acme-support"
TODAY = dt.date(2026, 11, 19)
SCHEDULE = scan.load_schedule()


def models_in(text: str, tmp_path: Path) -> list[str]:
    (tmp_path / "f.py").write_text(text)
    return [hit.model for hit in scan.scan(tmp_path, SCHEDULE, TODAY)]


def test_example_repo_hits_are_sorted_by_urgency():
    hits = scan.scan(EXAMPLE, SCHEDULE, TODAY)
    assert [(h.file, h.line, h.model, h.days_left) for h in hits] == [
        ("config/models.yaml", 5, "o4-mini", -27),
        ("config/models.yaml", 3, "claude-sonnet-4-5", 11),
        ("app/router.py", 5, "o3", 22),
        ("app/triage.py", 14, "gpt-5-mini", 22),
        (".env.example", 2, "gpt-4.1-mini", 56),
        ("app/summarize.ts", 8, "gpt-4o-2024-11-20", 56),
    ]


def test_example_repo_leaves_living_model_alone():
    assert "gpt-6-luna" in (EXAMPLE / "config" / "models.yaml").read_text()
    assert all(h.model != "gpt-6-luna" for h in scan.scan(EXAMPLE, SCHEDULE, TODAY))


@pytest.mark.parametrize("text", [
    'model="gpt-5.1"', 'model="gpt-5-codex"', 'model="gpt-4o-mini-tts"', 'model="o3-deep-research"',
    'model="gpt-6-luna"', "photo3 = load()", 'model="my-o3"', 'model="gpt-5x"', "version = 'gpt-4.10'",
])
def test_different_models_are_not_flagged(text, tmp_path):
    assert models_in(text, tmp_path) == []


@pytest.mark.parametrize("text,expected", [
    ('model="gpt-5"', "gpt-5"),
    ("We still call gpt-5.", "gpt-5"),
    ('model: "openai/gpt-5-nano"', "gpt-5-nano"),
    ('MODEL = "ft:gpt-4o-mini-2024-07-18:acme::abc123"', "gpt-4o-mini-2024-07-18"),
    ('model="gpt-4o-mini"', "gpt-4o-mini"),
    ('model="gpt-5-2025-08-07"', "gpt-5-2025-08-07"),
    ("MODEL=o3", "o3"),
])
def test_retiring_models_are_flagged(text, expected, tmp_path):
    assert models_in(text, tmp_path) == [expected]


def test_alias_and_suggestion_come_from_the_schedule(tmp_path):
    (tmp_path / "f.py").write_text('a = "gpt-4o"\nb = "gpt-4o-2024-08-06"\n')
    alias, snapshot = scan.scan(tmp_path, SCHEDULE, TODAY)
    assert (alias.alias, snapshot.alias) == (True, False)
    assert alias.suggested == snapshot.suggested == "gpt-6-luna"


def test_exclude_and_skipped_dirs(tmp_path):
    for rel in ("src/a.py", "sunset/report.md", "node_modules/x/index.js"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text('m = "gpt-5"')
    assert [h.file for h in scan.scan(tmp_path, SCHEDULE, TODAY, exclude=["sunset/*"])] == ["src/a.py"]


def test_schedule_is_well_formed():
    rows = json.loads(scan.DEFAULT_SCHEDULE.read_text())["models"]
    ids = [model_id for row in rows for model_id in row["ids"]]
    assert len(ids) == len(set(ids)), "an id appears in two rows"
    for row in rows:
        dt.date.fromisoformat(row["shutdown"])
        dt.date.fromisoformat(row["notice"])
        assert row["provider"] in ("openai", "anthropic")


def test_cli_json_and_fail_flag(capsys, tmp_path):
    assert cli.main(["scan", str(EXAMPLE), "--json", "--today", "2026-11-19"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert len(hits) == 6 and hits[0]["days_left"] == -27
    assert cli.main(["scan", str(EXAMPLE), "--fail"]) == 1
    assert cli.main(["scan", str(tmp_path), "--fail"]) == 0            # empty directory: nothing found
    assert cli.main(["scan", str(tmp_path / "missing")]) == 2          # not a directory: usage error
    capsys.readouterr()


def test_cli_text_output(capsys):
    cli.main(["scan", str(EXAMPLE), "--today", "2026-11-19"])
    out = capsys.readouterr().out
    assert "app/triage.py:14  gpt-5-mini  shuts down 2026-12-11 (22d left)  provider suggests: gpt-6.1-terra" in out
    assert "PAST SHUTDOWN, 27d ago" in out
