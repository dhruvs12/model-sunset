import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from model_sunset import cli, devin, obituary, scan

EXAMPLE = Path(__file__).parent.parent / "examples" / "acme-support"


def example_hits(tmp_path) -> Path:
    import datetime as dt
    from dataclasses import asdict
    hits = scan.scan(EXAMPLE, scan.load_schedule(), dt.date(2026, 11, 19))
    path = tmp_path / "hits.json"
    path.write_text(json.dumps([asdict(h) for h in hits]))
    return path


def test_payload_carries_playbook_hits_and_cap(tmp_path):
    hits = json.loads(example_hits(tmp_path).read_text())
    payload = devin.build_payload("acme/support", hits, {"gpt-5-mini": "my-model"}, max_acu=10)
    assert payload["title"] == "model-sunset: acme/support (6 retiring model reference(s), 27d past shutdown)"
    assert payload["tags"] == ["model-sunset"] and payload["max_acu_limit"] == 10
    assert "## Forbidden actions" in payload["prompt"] and '"gpt-5-mini": "my-model"' in payload["prompt"]
    assert "app/triage.py" in payload["prompt"]
    assert "playbook_id" not in payload


def test_stored_playbook_id_replaces_inline_text(tmp_path):
    hits = json.loads(example_hits(tmp_path).read_text())
    payload = devin.build_payload("acme/support", hits, {}, playbook_id="playbook-123")
    assert payload["playbook_id"] == "playbook-123"
    assert "## Forbidden actions" not in payload["prompt"] and "max_acu_limit" not in payload


def test_start_session_calls_the_v3_endpoint():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"], seen["auth"] = self.path, self.headers["Authorization"]
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = json.dumps({"session_id": "devin-abc", "url": "https://app.devin.ai/sessions/abc"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        session = devin.start_session({"prompt": "hi"}, "org-123", "cog_test",
                                      api_base=f"http://127.0.0.1:{server.server_address[1]}/v3")
    finally:
        server.shutdown()
    assert seen == {"path": "/v3/organizations/org-123/sessions", "auth": "Bearer cog_test", "body": {"prompt": "hi"}}
    assert session["session_id"] == "devin-abc"


def test_cli_dry_run_needs_no_key_and_real_run_refuses_without_one(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DEVIN_API_KEY", raising=False)
    hits = str(example_hits(tmp_path))
    assert cli.main(["devin", "--hits", hits, "--repo", "acme/support", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["tags"] == ["model-sunset"]
    assert cli.main(["devin", "--hits", hits, "--repo", "acme/support"]) == 2
    assert "DEVIN_API_KEY" in capsys.readouterr().err


def test_cli_devin_with_no_hits_does_nothing(tmp_path, capsys):
    empty = tmp_path / "hits.json"
    empty.write_text("[]")
    assert cli.main(["devin", "--hits", str(empty), "--repo", "acme/support"]) == 0
    assert "Nothing to hand to Devin" in capsys.readouterr().out


def test_playbook_is_packaged_and_is_a_valid_skill_file(capsys):
    assert cli.main(["playbook"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("---\nname: model-sunset\ndescription: ")
    for section in ("## Procedure", "## Specifications", "## Advice and pointers",
                    "## Forbidden actions", "## Required from user"):
        assert section in text


def test_obituary_uses_only_scan_and_golden_data(tmp_path, capsys):
    golden_file = tmp_path / "golden.jsonl"
    golden_file.write_text(json.dumps({
        "id": "triage-refund", "model": "gpt-5-mini", "request": {},
        "output": {"content": '{"category": "refund"}', "tool_calls": []}, "captured_at": "t"}) + "\n")
    assert cli.main(["obituary", str(EXAMPLE), "--today", "2026-11-19", "--golden", str(golden_file)]) == 0
    text = capsys.readouterr().out
    assert "### 🪦 gpt-5-mini" in text and "Shuts down on 2026-12-11. 22 days left." in text
    assert "Survived by 1 call site(s) in 1 file(s): `app/triage.py:14`" in text
    assert 'Last words (golden case `triage-refund`):\n\n> {"category": "refund"}' in text
    assert "Shut down on 2026-10-23, 27 days ago." in text          # o4-mini
    assert "Last words: not captured yet." in text                  # o3 has no golden record
    assert obituary.render([], [], {}) == "No retiring models here. Nobody to mourn.\n"
