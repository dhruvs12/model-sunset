import json
from pathlib import Path

import pytest

from model_sunset import cli, golden, scan
from tests import stub

INPUTS = Path(__file__).parent.parent / "examples" / "acme-support" / "inputs.jsonl"


@pytest.fixture(scope="module")
def base_url():
    server = stub.serve(port=0)
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


@pytest.fixture()
def golden_file(base_url, tmp_path):
    out = tmp_path / "golden.jsonl"
    assert cli.main(["capture", str(INPUTS), "--model", "gpt-5-mini", "--base-url", base_url, "--out", str(out)]) == 0
    return out


def statuses(golden_file, base_url, capsys, *extra) -> dict:
    capsys.readouterr()
    cli.main(["diff", str(golden_file), "--base-url", base_url, "--json", *extra])
    return {r["id"]: (r["check"], r["status"], r["notes"]) for r in json.loads(capsys.readouterr().out)}


def test_capture_freezes_request_and_output(golden_file):
    records = golden.read_jsonl(golden_file)
    assert [r["id"] for r in records] == ["triage-refund", "triage-bug", "route-order", "summary-thread"]
    assert all(r["model"] == "gpt-5-mini" and "meta" not in r["request"] for r in records)
    assert json.loads(records[0]["output"]["content"])["priority"] == "high"
    assert records[2]["output"]["tool_calls"][0]["name"] == "lookup_order"


def test_same_behaviour_passes_every_check(golden_file, base_url, capsys):
    result = statuses(golden_file, base_url, capsys, "--to", "stub-same")
    assert {check for check, _, _ in result.values()} == {"schema", "tool-calls", "text"}
    assert all(status == "pass" for _, status, _ in result.values())


def test_drift_is_caught_by_each_check(golden_file, base_url, capsys):
    result = statuses(golden_file, base_url, capsys, "--to", "stub-drift", "--judge-model", "stub-judge")
    assert result["triage-refund"] == ("schema", "fail", ["$.priority: missing"])
    assert result["route-order"][:2] == ("tool-calls", "fail")
    assert result["summary-thread"][:2] == ("text", "fail")


def test_text_without_a_judge_needs_review(golden_file, base_url, capsys):
    result = statuses(golden_file, base_url, capsys, "--to", "stub-drift")
    assert result["summary-thread"][:2] == ("text", "review")


def test_better_text_passes_the_judge(golden_file, base_url, capsys):
    result = statuses(golden_file, base_url, capsys, "--to", "stub-better", "--judge-model", "stub-judge")
    assert result["summary-thread"][:2] == ("text", "pass")


def test_fail_flag_and_report_file(golden_file, base_url, tmp_path, capsys):
    report = tmp_path / "report.md"
    args = ["diff", str(golden_file), "--base-url", base_url, "--report", str(report), "--fail"]
    assert cli.main([*args, "--to", "stub-same"]) == 0
    assert cli.main([*args, "--to", "stub-drift", "--judge-model", "stub-judge"]) == 1
    text = report.read_text()
    assert "# model-sunset diff: gpt-5-mini -> stub-drift" in text
    assert "**0 pass, 4 fail, 0 need review**" in text
    capsys.readouterr()


def test_replacement_and_judge_must_not_be_retiring(golden_file, base_url, capsys):
    assert cli.main(["diff", str(golden_file), "--base-url", base_url, "--to", "gpt-4o"]) == 2
    assert "itself scheduled for shutdown on 2027-01-14" in capsys.readouterr().err
    assert cli.main(["diff", str(golden_file), "--base-url", base_url, "--to", "stub-same", "--judge-model", "o3"]) == 2
    with pytest.raises(ValueError):
        golden.ensure_alive("gpt-5", scan.load_schedule(), "replacement")


@pytest.mark.parametrize("old,new,expected", [
    ({"a": 1, "b": "x"}, {"a": 2, "b": "y"}, []),
    ({"a": 1}, {"a": "1"}, ["$.a: number -> string"]),
    ({"a": 1}, {}, ["$.a: missing"]),
    ({}, {"a": 1}, ["$.a: new key"]),
    ({"items": [{"id": 1}]}, {"items": [{"id": 2}, {"id": 3}]}, []),
    ({"items": [{"id": 1}]}, {"items": [{"sku": 1}]}, ["$.items[].id: missing", "$.items[].sku: new key"]),
    ({"a": None}, {"a": "now set"}, []),
    ([1], {"a": 1}, ["$: array -> object"]),
])
def test_structure_diff(old, new, expected):
    assert golden.structure_diff(old, new) == expected


def test_fenced_json_counts_as_a_regression():
    record = {"id": "x", "request": {}, "output": {"content": '{"a": 1}', "tool_calls": []}}
    result = golden.check_case(record, {"content": '```json\n{"a": 1}\n```', "tool_calls": []}, None)
    assert (result["check"], result["status"]) == ("schema", "fail")


def scripted_judge(*winners):
    replies = iter(json.dumps({"winner": w, "reason": "r"}) for w in winners)
    return lambda prompt: next(replies)


@pytest.mark.parametrize("winners,expected", [
    (("A", "B"), "fail"),      # old output shown as A, then as B: preferred both times
    (("B", "A"), "pass"),      # new output preferred both times
    (("tie", "tie"), "pass"),
    (("A", "A"), "review"),    # the judge just likes position A
    (("A", "tie"), "review"),
])
def test_judge_is_asked_twice_with_positions_swapped(winners, expected):
    status, _ = golden.judge_pair({"messages": []}, "old text", "new text", scripted_judge(*winners))
    assert status == expected


def test_judge_sees_swapped_order_and_garbage_reply_needs_review():
    prompts = []
    def judge(prompt):
        prompts.append(prompt)
        return '{"winner": "tie", "reason": ""}'
    golden.judge_pair({"messages": []}, "OLD", "NEW", judge)
    assert "Response A:\nOLD" in prompts[0] and "Response A:\nNEW" in prompts[1]
    assert golden.judge_pair({}, "a", "b", lambda prompt: "I cannot decide")[0] == "review"
