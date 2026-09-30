# Research Digest Agent

A self-hosted paper-reading assistant: a small daily digest and meaningful updates from papers or researchers you follow. Set your own subjects, quality thresholds, schedule and notification channels in YAML or the guided CLI.

The default profile covers AI safety/alignment, reasoning/decision-making, learning/generalization and interpretability. Subjects are broad research problems, rather than similarity to one researcher's previous papers.

## Quick start

Python 3.11+ on macOS or Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install .
research-digest init
```

Setup asks for topics, language, time zone, daily time, LLM endpoint/model, channels, follow policy and polling interval. It preserves an existing configuration. Defaults are stored at `~/.config/research-digest/config.yaml`.

Before configuring any provider, try the **synthetic offline demonstration**:

```sh
research-digest preview --config config.example.yaml --offline-fixtures
```

These are fictional examples with recorded evaluations, not today's real papers. Offline preview uses temporary state and makes no network calls or deliveries. Your configured selection thresholds still apply.

For real recommendations, choose a provider supporting OpenAI-compatible Chat Completions and JSON output. Set its model in `llm.model`, then set the named API-key environment variable locally:

```sh
export DIGEST_LLM_API_KEY='your-provider-key'
research-digest doctor
research-digest preview
research-digest run --once
research-digest serve
```

`serve` must remain running on an awake host. It reloads configuration each minute, sends the digest at 09:00 in the selected IANA time zone, and polls watches hourly by default. A restart produces one catch-up digest, not every missed day. An older saved failed digest uses that day’s digest slot; fresh picks resume the next day. The tool does not install a background service for you.

### Use a local Codex login

You can use an installed, signed-in Codex CLI instead of an API key:

```yaml
llm:
  backend: codex_cli
  codex_command: codex
  model: '' # Uses the CLI's built-in default; set a supported model to pin it.
  codex_batch_size: 5
```

Run `codex login`, then `research-digest doctor`. The backend runs ephemeral, read-only structured assessments with shell, app, plugin, hook, browser, image, goal and subagent tools disabled. Unexpected tool events invalidate the assessment. It validates the same evidence spans and selection criteria as the API backend. Abstracts are assessed in batches; failed or missing batch entries are omitted without an individual retry storm. Request caps count CLI invocations, not papers. API `max_output_tokens` does not set the CLI model's output limit; response files are bounded separately. This uses your Codex account's access and limits. Never copy account credentials into this repository or public CI. See [official Codex automation documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

### Deliver through a connected Slack agent

For a trusted scheduler with access to the Slack plugin, set `notifications.slack.enabled: true` and `notifications.slack.transport: external`. Set `workspace_name`, `channel_name`, and the verified `channel_id` in your private configuration. This requires no webhook key; ordinary webhook delivery remains supported.

The scheduler runs `research-digest tick` each hour. Only the due daily digest and watch polls run. It then uses `research-digest outbox --claim` to reserve pending Slack payloads for five minutes, sends their saved subject/body to the verified destination, and calls `research-digest ack ID --message-url CONFIRMED_SLACK_URL` only after a successful send. `outbox` without `--claim` is read-only. Authentication or send failures leave the original payload pending. The sender must preserve message receipts before acknowledging; remote acceptance before acknowledgment retains the documented at-least-once delivery boundary.

Claims honor the Slack enable switch, skip papers already delivered through another alias, and reserve only one digest day. Acknowledgment atomically saves the receipt and delivery state; a recovered digest occupies the current day's slot, and repeating an acknowledgment is harmless.

Live preview can call the LLM, consume your daily request quota and write caches. It does not send notifications or change delivery records, mail UIDs, watch state, feedback, configuration or last-run dates.

## How recommendations work

1. Collect arXiv metadata, Hugging Face Daily Papers and optional Scholar alert email; merge DOI, arXiv versions and Semantic Scholar aliases.
2. Shortlist up to 10 papers per topic plus up to 10 attention/adjacent candidates, at most 50 total. Optional embeddings compare broad descriptions with paper title/abstract. Without them, source queries/categories and lexical topic coverage provide the explicit fallback.
3. Assess relatedness, problem importance, contribution/evidence and philosophy fit. Each assessment needs exact source excerpts. Invalid scores, unknown topics and unsupported numeric claims are rejected. Papers are untrusted data, not agent instructions.
4. Read up to 8 preliminary candidates' public arXiv HTML introductions, results, discussion and limitations. Each context is at most 8,000 characters; no claim of having read the full PDF. Unavailable HTML retains the abstract assessment.
5. Apply quality gates and diversity. Return 3 papers normally, up to 5 when extra candidates are strong. A day may have fewer than 3 or zero.

Default weights: importance **30%**, contribution/evidence **30%**, measured attention **25%**, philosophy fit **15%**. Relevance, importance and evidence must each be at least 3/5, with composite score at least 3.5. Extra picks need 4.0. Missing attention requires importance and evidence at least 4, and the remaining factors are proportionally reweighted.

HF reactions are normalized only within a date/topic cohort containing at least 10 measured values. S2 citations require age at least 14 days and a topic/age cohort of at least 10, using citations per day. Age bins are 14–30, 31–180 and over 180 days. Small cohorts stay **unknown**, with raw counts retained. A measured zero is a real observation. Author, institution and venue prestige add no score.

Greedy MMR uses `0.85 × score/5 − 0.15 × redundancy`, with at most 2 picks per broad topic and 1 adjacent pick. Near duplicates are suppressed only when both problem and contribution similarities exceed the thresholds. Adjacent papers are optional. No thresholds are lowered to fill slots.

Each paper has five brief reading cues within 400 characters, source links and an actual coverage label:

```text
정독 후보: [paper title]
문제: Why the problem matters.
기여·근거: The concrete contribution and available evidence.
관심 주제: Why it fits your interests.
관심·한계: Observed attention and an important limitation.
읽을 질문: What to check when reading.
초록 기반 / 본문 일부 확인 · [paper ID]
```

Assessment scores remain model judgments. The source excerpts and limits make them inspectable; the tool cannot establish scientific correctness from metadata alone.

## Follow papers and researchers

Use a stable ID, rather than an ambiguous name:

```sh
research-digest follow paper ARXIV:2605.21849 --policy next_digest
research-digest follow paper 'DOI:10.1234/example' --policy immediate
research-digest follow author 12345678 --policy immediate
research-digest unfollow author 12345678
```

The author ID is the numeric identifier in a Semantic Scholar author URL. Paper IDs may be arXiv IDs/URLs, DOIs or 40-character S2 IDs. All examples are illustrative.

The first successful scan establishes a quiet baseline. Later scans compare complete bounded ID sets, so newly indexed older papers can be found. Large watches that exceed `sources.semantic_scholar.max_pages` report failure and preserve their cursor; raise the limit deliberately.

Author watches apply topic relevance unless `--no-topic-filter` is selected. Citation alerts need a substantive extension, comparison, correction or new evidence on the followed problem, assessed from the citing paper; an incidental citation is insufficient. Scholar email may enrich metadata, but S2 confirms author/citation relationships.

Immediate alerts are capped at 3 per local day. Overflow waits for the next digest. Multiple watches and daily recommendations coalesce the same paper per channel. A paper already delivered is not repeated solely for a new arXiv version. Unfollowing changes future scans; already-created outbox messages remain durable.

## Notifications and state

Markdown is enabled by default at `~/.local/share/research-digest/digests`. Email uses authenticated SMTP with STARTTLS or SSL. Slack and Discord use webhook URLs stored in environment variables. Enable any combination in `notifications`.

The private SQLite file is at `~/.local/share/research-digest/state.db`. Payloads are saved before delivery, with each channel's success recorded independently. A restart retries the original failed payload, without resending successful channels. A daily digest is complete only when all its configured channels succeed. An unfinished daily outbox delays later daily digests to keep the backlog bounded; restore its transport before removing that channel from configuration.

SMTP/webhooks cannot provide exactly-once delivery: a crash or timeout after remote acceptance but before the local success record can cause a duplicate. Completed webhook chunks and SMTP recipients are saved individually and skipped on ordinary retry/restart. Only the remote-acceptance/local-record crash window remains. Markdown writes are atomic.

## Explicit feedback

Use a paper ID from a digest:

```sh
research-digest feedback arxiv:2609.12345 --kind useful
research-digest feedback arxiv:2609.12345 --kind weak_evidence
```

Kinds: `useful`, `not_relevant`, `already_known`, `weak_evidence`. Only the latest explicit response per paper counts. At least 3 distinct, consistent responses are required before preview proposes a topic-priority or evidence-threshold change. Suggestions never edit YAML automatically. No-open/no-response is not negative feedback, and `already_known` is paper-specific.

## Configuration

Start with [config.example.yaml](config.example.yaml); `init` writes every default so all options can be edited. See the complete [configuration reference](docs/configuration.md).

- `profile`: descriptions, priorities, include/exclude hints, philosophy lenses and language.
- `sources`: arXiv categories/queries, HF limit, optional IMAP and S2 pagination.
- `selection`: quality gates, weights, counts, diversity and duplicate thresholds.
- `retrieval`: shortlist budgets, lookback, embeddings and HTML limits.
- `schedule`: IANA time zone, wall-clock time, watch interval and catch-up.
- `watchlist`: papers/authors and per-item immediate/next-digest policy.
- `notifications`: channel enablement, SMTP details, webhook variable names, Markdown path and alert cap.
- `feedback`, `llm`, `state_path`: explicit suggestions, provider/request limits and private storage.

### Optional Scholar email

Enable `sources.scholar_mail`, configure IMAP host/mailbox, and set `SCHOLAR_IMAP_USERNAME` and `SCHOLAR_IMAP_PASSWORD` locally. Use the provider's supported IMAP authentication method; this adapter uses a password or app password, not an OAuth flow. Keep the sender allowlist limited to your Scholar sender.

The adapter reads MIME HTML/plain-text alerts with `BODY.PEEK[]`, in a read-only mailbox. It uses UIDVALIDITY/UID and server arrival time and never changes server read flags. It does not scrape Google Scholar pages. Sender checks do not replace the email provider's authentication/security controls.

### Optional embeddings and provider costs

Set `retrieval.embeddings_enabled`, `embedding_base_url`, `embedding_model` and `DIGEST_EMBEDDING_API_KEY`. Failed embeddings fall back explicitly, without fabricated vectors. Provider endpoints must support `/embeddings` or `/chat/completions` as appropriate. The chat payload uses `max_completion_tokens`; provider compatibility should be checked with live preview.

By default at most **80 chat attempts per UTC day** are reserved transactionally; failed requests and retries count. Cached assessments do not call the provider. Inputs and outputs are bounded, but the request cap is **not a monetary spending limit**. Optional embedding requests have separate provider costs and are not counted in the chat cap. Keep provider-side spending limits appropriate to your model.

### Docker

```sh
cp config.example.yaml config.yaml
cp .env.example .env
# Edit model/channels/config; put private environment values in .env.
docker compose build
docker compose run --rm digest doctor --config /config/config.yaml
docker compose run --rm digest preview --config /config/config.yaml --offline-fixtures
docker compose up -d
```

Compose mounts user configuration read-only and keeps state/digests in a named volume. Edit YAML on the host; `serve` reloads it. Disable or configure every enabled remote channel before starting.

## Development

```sh
pip install -e '.[dev]'
pytest -q
python -m build
```

Fixtures are packaged in the wheel, so offline preview works outside the source checkout. CI covers Python 3.11/3.12 without provider keys. Optional read-only public API checks are excluded by default:

```sh
DIGEST_LIVE_SMOKE=1 pytest -m live -q
```

IMAP/SMTP and paid LLM delivery are tested with injected transports; real mail/webhook sending requires your configured `run --once`. Docker execution requires Docker/Compose on your host.

## Credits and scope

The staged retrieval/scoring/diversity flow was informed by [PaperFlow](https://github.com/OpenRaiser/PaperFlow/tree/4a835e737490785b3ce51025c85b630cd224318c). This implementation is independent; no PaperFlow modules were copied. Its attention normalization, source provenance, explicit feedback and watch/outbox rules are implemented here.

Source references: [arXiv API](https://info.arxiv.org/help/api/user-manual.html), [HF Daily Papers](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api#huggingface_hub.HfApi.list_daily_papers), [S2 Graph API](https://api.semanticscholar.org/api-docs/graph), [OpenAI JSON mode](https://developers.openai.com/api/docs/guides/structured-outputs).

alphaXiv/deeplearn adapters, a hosted multi-user service and a web UI are outside v0.1. Contributions are welcome under the MIT license.
