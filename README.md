# model-sunset

OpenAI shuts down `gpt-5`, `gpt-5-mini` and `o3` on **Dec 11, 2026**, and its `gpt-4o` and `gpt-4.1` snapshots on **Jan 14, 2027**. Changing the model id takes a minute; knowing your prompts still work takes a test suite you don't have.

model-sunset builds that suite from the dying model itself: it records the old model's answers while it can still give them, then makes the replacement match. A Devin Bot runs it across your repos and opens the PRs.

## Shutdown dates

| Date | Provider | Models | Replacement the provider names |
|---|---|---|---|
| Nov 30, 2026 | Anthropic | `claude-sonnet-4-5` (`claude-sonnet-4-5-20250929`) | `claude-sonnet-5-5` |
| Dec 11, 2026 | OpenAI | `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5-pro`, `o3`, `o3-pro` and their dated snapshots | `gpt-6.1-sol`, `gpt-6.1-terra` or `gpt-6-luna`, depending on the model |
| Jan 14, 2027 | OpenAI | `gpt-4o-2024-08-06`, `gpt-4o-2024-11-20`, `gpt-4o-mini-2024-07-18`, `gpt-4.1-2025-04-14`, `gpt-4.1-mini-2025-04-14` | `gpt-6-luna` |

Already gone since Oct 23, 2026: `gpt-3.5-turbo`, `gpt-4`, `gpt-4-turbo`, `gpt-4.1-nano`, `gpt-4o-2024-05-13`, `o1`, `o1-pro`, `o3-mini`, `o4-mini`. The scanner flags these as `PAST SHUTDOWN`.

Sources, read on Nov 19, 2026: [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations), [Anthropic model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations). Google's [Gemini deprecations page](https://ai.google.dev/gemini-api/docs/deprecations) lists nothing dated in the next 90 days. The full schedule, one row per row of the provider's table, is in [`model_sunset/retirements.json`](model_sunset/retirements.json).

## Try it

```bash
pip install "git+https://github.com/dhruvs12/model-sunset" && model-sunset scan .
```

Python 3.11+, no dependencies. On the example app in this repo (`model-sunset scan examples/acme-support --today 2026-11-19`):

```
6 retiring model reference(s) as of 2026-11-19:

  config/models.yaml:5  o4-mini  shut down 2026-10-23 (PAST SHUTDOWN, 27d ago)  provider suggests: gpt-5.6-terra
      model: o4-mini
  config/models.yaml:3  claude-sonnet-4-5  shuts down 2026-11-30 (11d left)  provider suggests: claude-sonnet-5-5
      model: claude-sonnet-4-5
  app/router.py:5  o3  shuts down 2026-12-11 (22d left)  provider suggests: gpt-6.1-sol
      ROUTER_MODEL = "o3"
  app/triage.py:14  gpt-5-mini  shuts down 2026-12-11 (22d left)  provider suggests: gpt-6.1-terra
      model="gpt-5-mini",
  .env.example:2  gpt-4.1-mini  shuts down 2027-01-14 (56d left)  provider suggests: gpt-6-luna
      note: alias not named on the provider's page; every dated snapshot of it is
      SEARCH_RERANK_MODEL=gpt-4.1-mini
  app/summarize.ts:8  gpt-4o-2024-11-20  shuts down 2027-01-14 (56d left)  provider suggests: gpt-6-luna
      model: "gpt-4o-2024-11-20",
```

`--json` gives the same hits as data. `--fail` exits 1 when anything is found, for CI.

## The old model is the oracle

```bash
# 1. While the old model still answers, freeze its outputs on real inputs.
model-sunset capture inputs.jsonl --model gpt-5-mini --out golden.jsonl

# 2. Run the same inputs on the replacement you chose and compare.
model-sunset diff golden.jsonl --to <replacement> --judge-model <judge> --report report.md --fail
```

`inputs.jsonl` has one request per line (`id`, `messages`, and optionally `tools`, `response_format`). The request is sent to both models untouched. The check for each case is picked from what the old model produced:

| Old model returned | Check | Fails when |
|---|---|---|
| Tool calls | `tool-calls` | Tool names or order change, or an argument's keys or types change |
| A JSON object or array | `schema` | A key disappears or appears, a type changes, or the output stops parsing |
| Free text | `text` | A blind pairwise judge prefers the old output in both orders |

The judge sees the two outputs as A and B, is asked twice with the positions swapped, and is never told which is old. If it changes its mind when the order changes, the case is marked `review`, not `pass`.

Any OpenAI-compatible `/chat/completions` endpoint works: set `--base-url` and `--api-key-env` per command, so the old and new models can sit behind different providers or a gateway. `--to` is always your choice. The tool refuses a replacement or judge that is itself on the shutdown list.

To try the whole loop with no API key, run the stub endpoint from the tests (`python -m tests.stub`) and add `--base-url http://127.0.0.1:8089/v1`. This table is from the stub's deliberately broken model `stub-drift`, not from a real model:

```
**0 pass, 4 fail, 0 need review**

| case | check | result | notes |
|---|---|---|---|
| triage-refund | schema | fail | $.priority: missing |
| triage-bug | schema | fail | $.priority: missing |
| route-order | tool-calls | fail | tool calls: ['lookup_order'] -> [] |
| summary-thread | text | fail | judge preferred the old output in both orders: stub judge rule |
```

## Obituaries

`model-sunset obituary .` writes one for every retiring model in the repo, for the top of the migration PR. Each line is data: the provider's date, the call sites it leaves behind, and its last words, quoted from the golden set. (The last words below came from the stub.)

> ### 🪦 gpt-5-mini
>
> Shuts down on 2026-12-11. 22 days left. ([openai schedule](https://developers.openai.com/api/docs/deprecations))
>
> Survived by 1 call site(s) in 1 file(s): `app/triage.py:14`
>
> Successor named by the provider: `gpt-6.1-terra`
>
> Last words (golden case `triage-refund`):
>
> > {"category": "refund", "priority": "high", "needs_human": false}

## Why this is a Devin Bot

The scanner is a regex. The migration is not: someone has to read each call site, find real inputs in a repo they have never seen, and fix the prompt when the replacement drifts. That is agent work with a hard deadline, repeated once per repo.

- **One outcome to own.** [`BOT.md`](BOT.md) is the Bot's instructions: "No repository in this organization calls an LLM model after that model's shutdown date." A Devin Bot plans the work and starts a child session for each piece, each on its own machine ([Bots docs](https://docs.devin.ai/work-with-devin/bots)). Here a piece is a repo.
- **A playbook Devin can follow.** [`model_sunset/playbook.md`](model_sunset/playbook.md) uses the sections Devin's [playbook guide](https://docs.devin.ai/product-guides/creating-playbooks) recommends: Procedure, Specifications, Advice, Forbidden Actions, Required from User. Devin is moving Playbooks to [Skills](https://docs.devin.ai/product-guides/skills), so the same file carries Skill frontmatter: `model-sunset playbook > .agents/skills/model-sunset/SKILL.md` installs it in a repo.
- **A trigger.** [`.github/workflows/model-sunset.yml`](.github/workflows/model-sunset.yml) scans every Monday. When it finds hits and no migration PR is open, it calls the [Devin API](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions) (`POST /v3/organizations/{org_id}/sessions`) with the scan results and the playbook. The key is read from the `DEVIN_API_KEY` secret. With no key it prints the request and stops.
- **Evidence in the PR.** Devin commits the inputs, the golden set and the diff report next to the model swap, so a reviewer sees what was tested. It never merges.

## What it costs to run across N repos

Devin's session API meters work in ACUs: it takes a per-session cap (`max_acu_limit`) and reports `acus_consumed`. The workflow sets the cap on every session it starts (default 10, variable `SUNSET_MAX_ACU`).

```
Devin cost  =  repos with hits  x  ACUs per migration  x  your rate
worst case  =  repos with hits  x  cap
```

| Repos with hits | Worst case at a 10 ACU cap |
|---|---|
| 10 | 100 ACUs |
| 100 | 1,000 ACUs |
| 1,000 | 10,000 ACUs |

Two honest gaps. I have not measured a real migration yet, so 10 is a cap and not an estimate; the first run's `acus_consumed` replaces it. And Devin publishes no per-ACU price for self-serve plans: Pro ($20/month) and Max ($200/month) include a usage quota and bill on-demand credits past it, while Enterprise pays a contract rate per ACU ([pricing](https://devin.ai/pricing), [self-serve billing](https://docs.devin.ai/admin/billing/self-serve), [enterprise billing](https://docs.devin.ai/admin/billing/enterprise)).

Model API calls are billed separately by your provider: one call per input on the old model, one on the replacement, and two judge calls per free-text case.

## Status and limits

- v0.1, built Nov 19, 2026. 52 tests pass on Python 3.11, 3.12 and 3.13 against a local stub endpoint. It has not yet been run against a live provider API or a live Devin session.
- `capture` and `diff` speak `/chat/completions` only. OpenAI points `gpt-5-pro` and `o3-pro` at the Responses API, so those two need a human.
- The scanner finds ids written in files. It cannot see an id assembled at runtime or stored in a secret manager.
- The default schedule covers text models. OpenAI's page also lists image, speech, realtime and transcription shutdowns between Dec 1, 2026 and Feb 26, 2027; add rows with `--schedule your.json`.
- Azure OpenAI retires models on its own dates, which are not in the schedule.
- An undated alias such as `gpt-4o` is flagged with a note: OpenAI's page lists the dated snapshots, not the alias.

MIT licensed.
