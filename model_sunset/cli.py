"""Command line: model-sunset scan | capture | diff | obituary | devin | playbook"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__, devin, golden, obituary, scan


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="model-sunset", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_scan_options(p):
        p.add_argument("repo", nargs="?", default=".", help="directory to scan (default: .)")
        p.add_argument("--schedule", default=str(scan.DEFAULT_SCHEDULE), help="schedule JSON to use")
        p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                       help="skip paths matching this glob, e.g. 'sunset/*' (repeatable)")
        p.add_argument("--today", type=dt.date.fromisoformat, default=None,
                       help="count days from this date instead of today (YYYY-MM-DD)")

    def add_endpoint_options(p):
        p.add_argument("--base-url", help="OpenAI-compatible base URL (default: $OPENAI_BASE_URL or api.openai.com)")
        p.add_argument("--api-key-env", default="OPENAI_API_KEY", metavar="VAR",
                       help="name of the environment variable holding the API key (default: OPENAI_API_KEY)")

    p = sub.add_parser("scan", help="find retiring model ids")
    add_scan_options(p)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--fail", action="store_true", help="exit 1 if anything is found (for CI)")

    p = sub.add_parser("capture", help="run inputs on the old model and freeze its outputs")
    p.add_argument("inputs", help="JSONL file of requests")
    p.add_argument("--model", required=True, help="the retiring model to record")
    p.add_argument("--out", required=True, help="golden JSONL file to write")
    add_endpoint_options(p)

    p = sub.add_parser("diff", help="run a golden set on a replacement model and compare")
    p.add_argument("golden", help="golden JSONL file written by capture")
    p.add_argument("--to", required=True, help="replacement model (your choice)")
    p.add_argument("--judge-model", help="model for the pairwise judge on free text (omit to skip judging)")
    p.add_argument("--report", help="write a markdown report here")
    p.add_argument("--schedule", default=str(scan.DEFAULT_SCHEDULE))
    p.add_argument("--json", action="store_true", help="print results as JSON")
    p.add_argument("--fail", action="store_true", help="exit 1 if any case fails")
    add_endpoint_options(p)

    p = sub.add_parser("obituary", help="write an obituary for each retiring model in a repo")
    add_scan_options(p)
    p.add_argument("--golden", action="append", default=[], help="golden JSONL to quote last words from (repeatable)")

    p = sub.add_parser("devin", help="start a Devin session that runs the migration playbook")
    p.add_argument("--hits", required=True, help="file with `model-sunset scan --json` output")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name (default: $GITHUB_REPOSITORY)")
    p.add_argument("--replace", action="append", default=[], metavar="OLD=NEW", help="replacement choice (repeatable)")
    p.add_argument("--max-acu", type=int, help="ACU cap for the session")
    p.add_argument("--playbook-id", help="use a playbook stored in your Devin org instead of sending it inline")
    p.add_argument("--dry-run", action="store_true", help="print the request and do not call Devin")

    sub.add_parser("playbook", help="print the Devin playbook (it is also a valid SKILL.md)")
    return parser.parse_args(argv)


def run_scan(args) -> int:
    today = args.today or dt.date.today()
    hits = scan.scan(Path(args.repo), scan.load_schedule(args.schedule), today, args.exclude)
    print(json.dumps([asdict(h) for h in hits], indent=2) if args.json else scan.format_text(hits, today))
    return 1 if (args.fail and hits) else 0


def run_capture(args) -> int:
    ask = golden.make_chat(args.base_url, os.environ.get(args.api_key_env))
    records = golden.capture(golden.read_jsonl(args.inputs), args.model, ask)
    golden.write_jsonl(args.out, records)
    print(f"Froze {len(records)} output(s) from {args.model} into {args.out}")
    return 0


def run_diff(args) -> int:
    schedule = scan.load_schedule(args.schedule)
    golden.ensure_alive(args.to, schedule, "replacement")
    if args.judge_model:
        golden.ensure_alive(args.judge_model, schedule, "judge")
    api_key = os.environ.get(args.api_key_env)
    judge = golden.make_judge(args.judge_model, args.base_url, api_key) if args.judge_model else None
    records = golden.read_jsonl(args.golden)
    results = golden.diff(records, args.to, golden.make_chat(args.base_url, api_key), judge)
    report = golden.render_report(records, results, args.to, args.judge_model)
    if args.report:
        Path(args.report).write_text(report)
    print(json.dumps(results, indent=2) if args.json else report)
    return 1 if (args.fail and any(r["status"] == "fail" for r in results)) else 0


def run_obituary(args) -> int:
    today = args.today or dt.date.today()
    hits = scan.scan(Path(args.repo), scan.load_schedule(args.schedule), today, args.exclude)
    records = [record for path in args.golden for record in golden.read_jsonl(path)]
    sources = json.loads(Path(args.schedule).read_text()).get("sources", {})
    print(obituary.render(hits, records, sources), end="")
    return 0


def run_devin(args) -> int:
    hits = json.loads(Path(args.hits).read_text())
    if not hits:
        print("No retiring model ids in the scan results. Nothing to hand to Devin.")
        return 0
    if not args.repo:
        raise ValueError("pass --repo owner/name (or set GITHUB_REPOSITORY)")
    replacements = dict(pair.split("=", 1) for pair in args.replace)
    payload = devin.build_payload(args.repo, hits, replacements, args.max_acu, args.playbook_id)
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0
    api_key, org_id = os.environ.get("DEVIN_API_KEY"), os.environ.get("DEVIN_ORG_ID")
    if not api_key or not org_id:
        raise ValueError("set DEVIN_API_KEY and DEVIN_ORG_ID, or pass --dry-run")
    session = devin.start_session(payload, org_id, api_key)
    print(f"Started Devin session {session.get('session_id')}: {session.get('url')}")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.command == "playbook":
        print(devin.PLAYBOOK.read_text(), end="")
        return 0
    run = {"scan": run_scan, "capture": run_capture, "diff": run_diff,
           "obituary": run_obituary, "devin": run_devin}[args.command]
    try:
        return run(args)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"model-sunset: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
