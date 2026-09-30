# Configuration reference

`research-digest init` writes all defaults. YAML uses strict validation; unknown fields are rejected. Paths may use `~`. Secrets are environment-variable names, never inline values. The complete machine-readable schema is [config-schema.json](config-schema.json).

Descriptions/include hints drive topic retrieval and assessment. Global/topic excludes are supplied to the evaluator, without automatically excluding alignment-related preference optimization. Priorities break selection ties and control topic coverage order. Lenses affect fit reasoning; no exact keyword match is required.

Each `watchlist.papers` entry has `id` and `policy`; `watchlist.authors` also has `topic_filter` (true by default). Use stable IDs accepted by `follow`. API model names are provider-specific and required. With `llm.backend: codex_cli`, an empty model uses the installed CLI's built-in default; set a model explicitly to pin it.

| Setting | Default |
| --- | --- |
| `profile.topics` | `four broad topic objects; see config.example.yaml` |
| `profile.lenses` | `["Trustworthy decisions under uncertainty", "Robustness under changing conditions", "Efficient use of data and computation"]` |
| `profile.exclude` | `["Diffusion language model decoding without broader reasoning or reliability contributions"]` |
| `profile.summary_language` | `"ko"` |
| `sources.arxiv.enabled` | `true` |
| `sources.arxiv.categories` | `["cs.AI", "cs.LG", "cs.CL"]` |
| `sources.arxiv.queries` | `[]` |
| `sources.arxiv.max_results` | `200` |
| `sources.huggingface.enabled` | `true` |
| `sources.huggingface.limit` | `100` |
| `sources.scholar_mail.enabled` | `false` |
| `sources.scholar_mail.host` | `"imap.gmail.com"` |
| `sources.scholar_mail.port` | `993` |
| `sources.scholar_mail.mailbox` | `"INBOX"` |
| `sources.scholar_mail.username_env` | `"SCHOLAR_IMAP_USERNAME"` |
| `sources.scholar_mail.password_env` | `"SCHOLAR_IMAP_PASSWORD"` |
| `sources.scholar_mail.allowed_senders` | `["scholaralerts-noreply@google.com"]` |
| `sources.scholar_mail.max_messages` | `100` |
| `sources.semantic_scholar.enabled` | `true` |
| `sources.semantic_scholar.api_key_env` | `"SEMANTIC_SCHOLAR_API_KEY"` |
| `sources.semantic_scholar.max_pages` | `10` |
| `selection.min_relevance` | `3` |
| `selection.min_importance` | `3` |
| `selection.min_evidence` | `3` |
| `selection.unknown_attention_min` | `4` |
| `selection.base_min_score` | `3.5` |
| `selection.base_count` | `3` |
| `selection.max_count` | `5` |
| `selection.extra_min_score` | `4.0` |
| `selection.max_per_topic` | `2` |
| `selection.max_adjacent` | `1` |
| `selection.mmr_relevance_weight` | `0.85` |
| `selection.duplicate_semantic_threshold` | `0.9` |
| `selection.duplicate_jaccard_threshold` | `0.8` |
| `selection.weights.importance` | `0.3` |
| `selection.weights.evidence` | `0.3` |
| `selection.weights.attention` | `0.25` |
| `selection.weights.fit` | `0.15` |
| `schedule.timezone` | `"Asia/Seoul"` |
| `schedule.digest_at` | `"09:00:00"` |
| `schedule.watch_poll_minutes` | `60` |
| `schedule.catchup` | `true` |
| `watchlist.papers` | `[]` |
| `watchlist.authors` | `[]` |
| `retrieval.top_k_per_topic` | `10` |
| `retrieval.extra_candidates` | `10` |
| `retrieval.max_evaluations` | `50` |
| `retrieval.lookback_hours` | `72` |
| `retrieval.catchup_days` | `7` |
| `retrieval.embeddings_enabled` | `false` |
| `retrieval.embedding_base_url` | `null` |
| `retrieval.embedding_model` | `null` |
| `retrieval.embedding_key_env` | `"DIGEST_EMBEDDING_API_KEY"` |
| `retrieval.fulltext_enabled` | `true` |
| `retrieval.fulltext_top_k` | `8` |
| `retrieval.fulltext_max_chars` | `8000` |
| `feedback.enabled` | `true` |
| `feedback.suggestions_enabled` | `true` |
| `feedback.min_explicit_signals` | `3` |
| `notifications.max_immediate_per_day` | `3` |
| `notifications.default_watch_policy` | `"next_digest"` |
| `notifications.max_chars_per_paper` | `400` |
| `notifications.email.enabled` | `false` |
| `notifications.email.host` | `""` |
| `notifications.email.port` | `587` |
| `notifications.email.sender` | `""` |
| `notifications.email.recipients` | `[]` |
| `notifications.email.username_env` | `null` |
| `notifications.email.password_env` | `"SMTP_PASSWORD"` |
| `notifications.email.security` | `"starttls"` |
| `notifications.slack.enabled` | `false` |
| `notifications.slack.url_env` | `"DIGEST_SLACK_WEBHOOK"` |
| `notifications.slack.transport` | `"webhook"` |
| `notifications.slack.workspace_name` | `""` |
| `notifications.slack.channel_name` | `""` |
| `notifications.slack.channel_id` | `null` |
| `notifications.discord.enabled` | `false` |
| `notifications.discord.url_env` | `"DIGEST_DISCORD_WEBHOOK"` |
| `notifications.markdown.enabled` | `true` |
| `notifications.markdown.directory` | `"~/.local/share/research-digest/digests"` |
| `llm.enabled` | `true` |
| `llm.backend` | `"api"` |
| `llm.base_url` | `"https://api.openai.com/v1"` |
| `llm.model` | `""` |
| `llm.codex_command` | `"codex"` |
| `llm.codex_timeout_seconds` | `240` |
| `llm.codex_batch_size` | `5` |
| `llm.api_key_env` | `"DIGEST_LLM_API_KEY"` |
| `llm.max_requests_per_day` | `80` |
| `llm.max_output_tokens` | `1800` |
| `llm.json_mode` | `true` |
| `state_path` | `"~/.local/share/research-digest/state.db"` |

Channel details: email supports `starttls`/`ssl`, optional `username_env`, and required sender/recipients/host when enabled. Webhooks use `url_env`. Markdown uses a directory. External Slack delivery uses a trusted connected-app sender and adds no webhook secret. Its workspace/channel metadata belong in private config. `outbox --claim` leases messages for five minutes; `ack` requires a confirmed Slack permalink and rejects a different configured channel. S2 API key is optional, but unauthenticated requests may be limited.

Positive weights are normalized proportionally; omitted attention does not become zero. Request caps count API chat attempts or Codex CLI invocations across all runs using this state file. Codex batch entries do not each consume a request; CLI output limits are independent of API `max_output_tokens`. The date for chat quota is UTC; digest/watch dates use the configured local time zone. Embeddings have separate costs.

Edit config only when no other process is modifying it. `follow`/`unfollow` use atomic replacement; comments are not preserved. `serve` uses a state-file lock to avoid overlapping real runs. `preview` may run alongside it and shares the transactional chat cap.
