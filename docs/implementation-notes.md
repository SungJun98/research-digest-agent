# Implementation decisions and verification

These decisions were recorded while executing the approved v0.1 plan.

## Decisions

The following is the complete decision log; the cost if mistaken is included.

- Ruling: Topic/notification config and several fixture helpers are illustrative plan interfaces; retain the documented behavior while making callable APIs internally consistent — prevents duplicate models; cost if wrong: adjust public config before release.
- Ruling: Public repository creation/push is already authorized by the user's explicit GitHub-publication request and approved plan; proceed after verification if authenticated access exists — cost if wrong: public release can be removed, but publication was intended.
- Task 2: Ruling: Use atomic reserve_llm_request instead of separate count and record — concurrent requests cannot exceed the configured cap — cost if wrong: caller API rename.
- Task 7C: Ruling: Add optional topic_priorities mapping to select_daily — tie-break needs profile priorities absent from the planned signature — cost if wrong: one optional caller argument.
- Task 9: Ruling: Watch baselines fetch bounded complete ID sets from the epoch — newly indexed older papers must not be lost to publication-date filtering — cost if wrong: more S2 requests and explicit page-limit errors on very large watches.
- Task 9: Ruling: NotificationConfig is the planned NotificationPolicy and route_events receives timezone_name — use existing config model and local-day timezone explicitly — cost if wrong: caller parameter migration.
- Task 10: Ruling: Store all per-channel digest payloads atomically before sending, with channel-specific same-paper dedup — a prior immediate event may already have reached only one channel — cost if wrong: extra notification rows per digest.
- Task 10: Ruling: Config example and packaged synthetic JSON are introduced here for the specified offline smoke command — Task 11 extends packaging/docs — cost if wrong: task boundary only.
- Task 10: Ruling: A pending daily outbox blocks creating a later daily digest until retry succeeds; total evaluator failure is retryable and sends no misleading empty success — favors bounded backlog and truthful completion — cost if wrong: other channels wait during a persistent channel failure.
- Task 12: Ruling: Perform fresh whole-branch review before public repo push — code is complete after Task 11 and publication should follow review — cost if wrong: task-order bookkeeping only.
- Final: Ruling: An older immutable failed digest counts as today's catch-up; fresh daily recommendations resume the next day — preserve original retries while honoring one digest/max-five per day — cost if wrong: a fresh digest waits one day after recovery.

## Final review and verification

A fresh reviewer identified 11 integration failures. All were reproduced by failing tests and fixed in one pass: overlapping outboxes, baseline contamination, alias state migration, arXiv DOI parsing, atomic IMAP ingestion, mailbox starvation, recovery overload, malformed provider/source output, partial delivery progress, YAML watch validation and candidate inspection.

71 offline tests pass. A read-only live arXiv/HF smoke test passes. The sdist/wheel build and a clean installed-wheel offline run away from the checkout pass. Python 3.11/3.12 and a real Docker build/offline smoke are also configured in GitHub Actions.

No deferred minor review findings. Remote acceptance before a local progress commit remains an at-least-once delivery boundary. Actual paid LLM evaluation and private mail/webhook delivery have not been exercised; they require the user’s provider and channel configuration.
