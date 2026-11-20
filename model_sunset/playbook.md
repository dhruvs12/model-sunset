---
name: model-sunset
description: Migrate a repo off LLM models that are scheduled for shutdown, using the old model's frozen outputs as the test suite. Use when `model-sunset scan` reports hits.
---

# model-sunset migration playbook

## Overview

A provider is shutting down models this repo calls. Move every call to a replacement model
without changing behaviour. The old model is the oracle: while it can still answer, record its
outputs on real inputs, then prove the replacement matches them. Deliver one pull request with
the model swap, the golden set and the diff report.

## Procedure

1. Install the tool: `pip install "git+https://github.com/dhruvs12/model-sunset"`.
2. Run `model-sunset scan . --exclude "sunset/*" --json > /tmp/hits.json`. If the list is empty, report "nothing to migrate" and stop.
3. Look for an open pull request whose title starts with `model-sunset:`. If one exists, check out its branch and continue there. Otherwise create the branch `model-sunset/<earliest-shutdown-date>`.
4. Decide the replacement for each retiring model. Use the owner's choice from the session prompt. If there is none, use the `suggested` value from the scan hit. If there is neither, stop and ask.
   - A `suggested` value with a note in brackets (for example `reasoning.mode: pro, Responses API`) means the call must change API surface. Flag it in the PR and do not attempt it without confirmation.
5. For each call site in the hits, read the code until you know exactly what request it sends: system prompt, message template, `tools`, `response_format`, sampling parameters.
6. Collect 10 to 30 real inputs per call site and write them to `sunset/inputs/<call-site>.jsonl`, one request per line: `{"id": "...", "messages": [...], "tools": [...], "response_format": {...}, "meta": {"source": "..."}}`. Take inputs from the first source that exists:
   1. recorded requests or logs in the repo or its fixtures
   2. test fixtures and eval sets
   3. example payloads in docs
   4. the prompt template filled with realistic values. Mark these `"meta": {"source": "synthetic"}`.
   - Remove names, emails, tokens and other personal data before writing any input to disk.
7. Freeze the oracle: `model-sunset capture sunset/inputs/<call-site>.jsonl --model <old-model> --out sunset/golden/<call-site>.jsonl`.
   - If the scan says PAST SHUTDOWN, the old model cannot answer. Build the golden file from logged outputs if the repo has them. If it has none, write "no oracle" for that call site in the PR and continue.
8. Write the obituaries while the old ids are still in the code: `model-sunset obituary . --exclude "sunset/*" --golden sunset/golden/<call-site>.jsonl > /tmp/obituary.md`.
9. Compare: `model-sunset diff sunset/golden/<call-site>.jsonl --to <replacement> --judge-model <judge> --report sunset/report-<call-site>.md`.
10. Change the model id at every hit, and nothing else. Run the repo's own tests and linters.
11. For each case the report marks `fail`, try to fix it in the prompt or request (restate the JSON schema, set `tool_choice`, tighten an instruction). Rerun step 9 after each attempt. Stop after two attempts per call site.
12. Open one pull request titled `model-sunset: <old> -> <new> (shutdown <date>)`. Put in the body, in this order: the obituaries, the pass / fail / review counts per call site, every case still marked `fail` or `review`, which inputs were synthetic, and anything that needs a human decision.
13. Report the PR link and the counts, and stop. A human merges.

## Specifications

- `model-sunset scan . --exclude "sunset/*" --fail` exits 0 on the branch.
- `sunset/inputs/`, `sunset/golden/` and `sunset/report-*.md` are committed.
- Every golden file is byte-identical to what `capture` wrote.
- The repo's existing tests pass.
- The PR body lists every `fail` and `review` case. Zero is a valid number; hiding one is not.

## Advice and pointers

- Model ids hide in config files, `.env.example`, Helm values, notebooks and docs, not only in code. Trust the scan over your own search.
- A hit marked `alias` is an undated alias such as `gpt-4o`. The provider's page lists its dated snapshots, not the alias. Migrate it and say in the PR that the alias itself is not named on the page.
- Structured output and tool calls are checked by shape (keys and types), not by value. Free text goes to a blind pairwise judge that is asked twice with the order swapped.
- A `review` result means the judge disagreed with itself or no judge was set. It is not a pass.
- Golden capture costs model API calls: one per input on the old model, one on the replacement, and two judge calls per free-text case. Keep input sets small and real.
- The old and new models can live on different endpoints. Use `--base-url` and `--api-key-env` on each command.

## Forbidden actions

- Do not edit, regenerate or delete a golden file to make a diff pass.
- Do not choose a replacement model that is not the owner's choice or the provider's suggestion.
- Do not use a replacement or judge model that is itself on the shutdown list. The tool refuses; do not work around it.
- Do not change model ids that the scan did not report.
- Do not commit API keys, or inputs that contain personal data.
- Do not merge the pull request or push to the default branch.

## Required from user

- Access to the repository through Devin's GitHub integration, with permission to open pull requests.
- An API key for the old and the replacement model, stored as a Devin secret (`OPENAI_API_KEY`, plus `OPENAI_BASE_URL` if the endpoint is not OpenAI's).
- The judge model to use for free text. If none is given, run the diff without `--judge-model` and report text cases as `review`.
