# Research Digest Agent v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자별 설정으로 매일 3~5편을 선별하고 팔로우한 논문·연구자의 중요한 변화를 알리는 셀프호스팅 오픈소스 CLI를 공개한다.

**Architecture:** Python CLI의 수집 어댑터가 공통 Paper 모델을 만들고 SQLite에 정규화한다. 선정기는 근거를 남기는 LLM 평가와 관측된 관심 신호를 결합하며, 별도 watch 서비스가 연구자 새 논문과 의미 있는 인용을 찾는다. 전달·스케줄·설정은 핵심 로직과 분리한다.

**Tech Stack:** Python 3.11+, Typer, Pydantic 2, PyYAML, httpx, huggingface_hub, SQLite 표준 라이브러리, pytest, Docker Compose, GitHub Actions CI.

**Spec:** `docs/superpowers/specs/2026-09-30-research-digest-agent-design.md`

**추천 설계 변경 안내 (2026-09-30):** [PaperFlow 참고 수정안](../specs/2026-09-30-recommendation-pipeline-design.md)이 사용자 검토 중이다. 이 수정안 승인 후 Task 1·2·7·8·10·11에 의미 검색·상위 후보 본문 확인·다양성·명시적 피드백을 반영한다. 현재 Task 7의 초록 전용 평가와 단순 주제 상한은 이전 설계이므로 그대로 구현하지 않는다. 구현은 수정안 검토 및 실행 방식 선택 후 시작한다.

## Global Constraints

- Python 3.11 이상; CI는 Python 3.11·3.12에서 실행한다.
- 사용자 설정은 YAML과 안내형 CLI에서 바꾸며, 개인 설정·비밀정보·SQLite는 공개 Git에 넣지 않는다.
- 일일 추천은 기본 3편, 강한 후보가 있을 때 최대 5편, 기준 미달이면 0~2편이다.
- Google Scholar는 알림 메일 IMAP만 읽으며 웹페이지를 자동 수집하거나 알림을 자동 생성하지 않는다.
- v1 수집은 arXiv, Hugging Face Daily Papers, 선택적 Scholar 메일이다. Semantic Scholar는 팔로우 대상 추적·인용 신호에 쓴다. alphaXiv/deeplearn.org는 이후 어댑터다.
- 후속 이벤트는 연구자의 새 논문과 팔로우 논문의 새 인용이다. 새 인용이라는 사실만으로 알리지 않는다.
- 알림 채널은 이메일 SMTP, Slack 웹훅, Discord 웹훅, 로컬 Markdown이다.
- arXiv API는 공식 제한인 단일 연결·요청 사이 최소 3초를 지킨다. 사용한 메타데이터의 원문 링크를 제공하고 PDF를 재배포하지 않는다.
- SMTP/일반 웹훅은 원격 수신 확인 직후 프로세스가 종료되면 정확히 한 번 전달을 보장할 수 없다. 채널별 성공 기록과 재시도로 통상적인 재시작 중복을 막고, 이 드문 경계 조건은 README에 명시한다.
- 브라우저 UI와 가입형 웹서비스, PDF 전체 분석, 자동 프로필 학습은 v1 범위 밖이다.

## Review Focus

1. 두 출처가 같은 논문의 arXiv 버전 URL과 DOI를 다르게 줄 때 한 번만 추천하는가? Task 2의 교차 ID 테스트로 확인한다.
2. 오래된 Scholar 메일과 손상된 HTML 메일이 갑자기 추천·알림을 폭증시키지 않는가? Task 5의 날짜·파서 테스트로 확인한다.
3. Hugging Face 반응이 없는 갓 나온 논문을 0점 취급하거나 근거 없는 실험 결과를 요약하지 않는가? Task 7의 결측·근거 테스트로 확인한다.
4. 알림 발송 도중 한 채널만 실패한 뒤 재시작해도 성공 채널에 다시 보내지 않는가? Task 8의 채널별 outbox 테스트로 확인한다.
5. 시간대 변경·일시 중단·재시작이 중복 발송이나 여러 날치 이메일을 만들지 않는가? Task 10의 시계·복구 테스트로 확인한다.

---

## File map

| 파일 | 단일 책임 |
| --- | --- |
| `pyproject.toml`, `.gitignore` | 설치·의존성·개인 데이터 제외 |
| `src/research_digest/config.py` | YAML 스키마·기본값·환경변수 검증 |
| `src/research_digest/models.py`, `identity.py` | 공통 Paper/Event 모델·논문 식별 |
| `src/research_digest/store.py` | SQLite 논문·이벤트·실행·채널별 발송 상태 |
| `src/research_digest/sources/arxiv.py` | arXiv API 수집·Atom 파싱·호출 간격 |
| `src/research_digest/sources/huggingface.py` | Daily Papers 수집·관심 신호 정규화 |
| `src/research_digest/sources/scholar_mail.py` | IMAP·Scholar 알림 메일 파싱 |
| `src/research_digest/sources/semantic_scholar.py` | 저자 논문·논문 인용 조회 |
| `src/research_digest/llm.py`, `selection.py` | 근거 기반 평가·점수·다양성·상한 |
| `src/research_digest/render.py`, `delivery.py` | 다이제스트/이벤트 표시와 채널별 발송 |
| `src/research_digest/watch.py`, `runner.py` | 팔로우 이벤트 판정·일일/비정기 흐름 |
| `src/research_digest/cli.py`, `schedule.py` | 안내형 CLI·실행 시계·복구 |
| `tests/`, `README.md`, `config.example.yaml`, `Dockerfile`, `compose.yaml`, `.github/workflows/ci.yml`, `LICENSE`, `CONTRIBUTING.md` | 검증·온보딩·공개 |

## Task 1: 패키지, 설정 스키마, 안내형 초기화

**Files:** Create `pyproject.toml`, `.gitignore`, `src/research_digest/__init__.py`, `src/research_digest/config.py`, `src/research_digest/cli.py`, `tests/test_config.py`.

**Interfaces:** `load_config(path: Path) -> AppConfig`, `write_initial_config(path: Path, answers: dict[str, str]) -> None`, `validate_secrets(config: AppConfig, env: Mapping[str,str]) -> list[str]`. `Topic(id: str, description: str, priority: int = 1, include: list[str] = [], exclude: list[str] = [])`; `SelectionConfig(min_relevance: int = 3, min_importance: int = 3, min_evidence: int = 3, unknown_attention_min: int = 4, base_count: int = 3, max_count: int = 5, extra_min_score: float = 4.0, max_per_topic: int = 2, weights: dict[str,float])`; `Watchlist(papers: list[PaperWatch], authors: list[AuthorWatch])`; `NotificationPolicy(max_immediate_per_day: int = 3, event_policy: dict[str, Literal["immediate", "next_digest"]])`. `AppConfig` exposes `profile` with `topics: list[Topic]`, `sources`, `selection: SelectionConfig`, `schedule`, `watchlist: Watchlist`, `notifications` containing `NotificationPolicy`, `llm`; list fields use `default_factory`.

- [ ] **Step 1: Write failing configuration tests.**

```python
def test_config_rejects_invalid_timezone(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("schedule:\n  timezone: Mars/Olympus\n")
    with pytest.raises(ValueError, match="timezone"):
        load_config(p)

def test_secrets_are_named_not_embedded(valid_config):
    valid_config.notifications.email.password_env = "SMTP_PASSWORD"
    assert validate_secrets(valid_config, {}) == ["SMTP_PASSWORD"]
```

- [ ] **Step 2: Run `python -m pytest tests/test_config.py -q`; expect import/validation failure.**
- [ ] **Step 3: Implement Pydantic models with exact defaults, strict unknown-field handling, IANA timezone validation via `ZoneInfo`, and environment-variable-name fields.**

```python
class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "Asia/Seoul"
    digest_at: time = time(9, 0)
    watch_poll_minutes: int = Field(default=60, ge=5)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

def load_config(path: Path) -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(path.read_text()) or {})
```

- [ ] **Step 4: Add `init` and `doctor` commands using the interface above; `init` writes outside the repo, `doctor` reports missing secrets without printing values. Run the config tests and CLI smoke help.**
- [ ] **Step 5: Commit `feat: add configurable CLI foundation`.**

## Task 2: 공통 논문 ID와 영속 상태

**Files:** Create `src/research_digest/models.py`, `identity.py`, `store.py`, `tests/test_identity_store.py`.

**Interfaces:** `Paper(title: str, abstract: str = "", authors: tuple[str, ...] = (), url: str = "", published_at: datetime | None = None, seen_at: datetime | None = None, doi: str | None = None, arxiv_id: str | None = None, s2_id: str | None = None, sources: set[str] = set(), signals: dict[str, float] = {}, metadata: dict[str, str] = {})` uses `default_factory` for containers and derives `canonical_id` through `canonicalize(p) -> str`; `merge_papers(papers: Iterable[Paper]) -> list[Paper]`; `Store(path: Path)` provides `upsert_papers`, `seen`, `mark_seen`, `create_notification`, `pending_notifications`, `reserve_delivery`, `mark_delivered`, `was_delivered`, `last_success`, `set_last_success`, `get_watch_cursor`, `set_watch_cursor`, `watch_item_seen`, `mark_watch_item_seen`, `queue_event`, `pending_events`, `immediate_count`, `llm_requests_today`, `record_llm_request`, `snapshot_counts`. `create_notification(id, subject, body, channels)` saves immutable content before the first send; `pending_notifications()` resumes unfinished channel sends.

- [ ] **Step 1: Write failing tests for arXiv version stripping, DOI merging, and notification persistence across reopened SQLite connections.**

```python
def test_arxiv_version_and_doi_merge():
    a = Paper(arxiv_id="2605.21849v1", title="GAE", sources={"arxiv"})
    b = Paper(arxiv_id="2605.21849v2", doi="10.1/gae", title="GAE", sources={"hf"})
    merged = merge_papers([a, b])
    assert len(merged) == 1
    assert merged[0].sources == {"arxiv", "hf"}
    assert merged[0].doi == "10.1/gae"

def test_delivered_channel_survives_restart(tmp_path):
    Store(tmp_path / "state.db").mark_delivered("paper:42", "email")
    assert Store(tmp_path / "state.db").was_delivered("paper:42", "email")
```

- [ ] **Step 2: Run `python -m pytest tests/test_identity_store.py -q`; expect failures.**
- [ ] **Step 3: Implement stable IDs and SQLite schema with UNIQUE keys for papers, paper ID aliases, watch-item IDs, events, notifications and `(notification_id, channel)` deliveries; merge transitive DOI/arXiv/S2 aliases before choosing the display ID, persist immutable notification content, and use transactions for state transitions.**

```python
def canonicalize(paper: Paper) -> str:
    if paper.doi:
        return "doi:" + paper.doi.strip().lower().removeprefix("https://doi.org/")
    if paper.arxiv_id:
        return "arxiv:" + re.sub(r"v\d+$", "", paper.arxiv_id.lower())
    if paper.s2_id:
        return "s2:" + paper.s2_id.lower()
    return "title:" + slug(paper.title) + ":" + slug(paper.authors[0] if paper.authors else "")
```

- [ ] **Step 4: Run identity/store tests; include a restart test for an interrupted delivery reservation.**
- [ ] **Step 5: Commit `feat: persist paper and notification identities`.**

## Task 3: arXiv 수집 어댑터

**Files:** Create `src/research_digest/sources/__init__.py`, `sources/arxiv.py`, `tests/test_arxiv.py`, `tests/fixtures/arxiv.xml`.

**Interfaces:** `ArxivSource(client: httpx.Client, clock: Callable[[], float], sleep: Callable[[float], None]).fetch(queries: list[str], since: datetime) -> list[Paper]`; `SourceError(safe_message: str)` from `sources/__init__.py` is the common per-source exception. Returns UTC-aware timestamps and arXiv ID without version for identity, while preserving the source URL.

- [ ] **Step 1: Write a test with two Atom entries, one with `v2`, one older than `since`; assert only the fresh paper and its abstract/author are returned. Add a fake clock test asserting >=3 seconds between HTTP requests.**

```python
def test_arxiv_since_and_version(mock_arxiv_client):
    papers = ArxivSource(mock_arxiv_client, clock=lambda: 0.0, sleep=lambda _: None).fetch(
        ["cat:cs.AI"], datetime(2026, 9, 29, tzinfo=timezone.utc)
    )
    assert [p.arxiv_id for p in papers] == ["2609.12345"]
    assert papers[0].abstract
```

- [ ] **Step 2: Run `python -m pytest tests/test_arxiv.py -q`; expect failure.**
- [ ] **Step 3: Parse Atom via `ElementTree`, percent-encode query parameters with `httpx`, bound results, retry 429/5xx with backoff, and serialize requests with a shared 3-second throttle.**

```python
def _throttle(self) -> None:
    wait = 3.0 - (self.clock() - self.last_request_at)
    if wait > 0:
        self.sleep(wait)
    self.last_request_at = self.clock()
```

- [ ] **Step 4: Run adapter tests with recorded fixtures; check malformed Atom returns a source error rather than terminating all discovery.**
- [ ] **Step 5: Commit `feat: collect arxiv metadata responsibly`.**

## Task 4: Hugging Face Daily Papers와 관심 신호

**Files:** Create `src/research_digest/sources/huggingface.py`, `tests/test_huggingface.py`, `tests/fixtures/hf_daily.json`.

**Interfaces:** `HuggingFaceSource(client: httpx.Client).fetch(dates: list[date]) -> list[Paper]`; each paper has `signals["hf_upvotes"]` and `signals["hf_daily_rank"]`; `normalize_attention(paper: Paper, cohort: list[Paper]) -> float | None` compares only same-day candidates.

- [ ] **Step 1: Write a fixture test that preserves upvotes, arXiv ID and title, and a missing-upvote test that returns unknown rather than zero.**

```python
def test_missing_upvotes_are_unknown(hf_source):
    papers = hf_source.fetch([date(2026, 9, 30)])
    assert papers[0].signals.get("hf_upvotes") is None
    assert normalize_attention(papers[0], papers) is None
```

- [ ] **Step 2: Run `python -m pytest tests/test_huggingface.py -q`; expect failure.**
- [ ] **Step 3: Request `/api/daily_papers` with `date` and `limit`, map the nested `paper` fields, and compute percentile only from entries with measured reactions.**

```python
def normalize_attention(paper: Paper, cohort: list[Paper]) -> float | None:
    votes = paper.signals.get("hf_upvotes")
    observed = sorted(p.signals["hf_upvotes"] for p in cohort if isinstance(p.signals.get("hf_upvotes"), (int, float)))
    if not isinstance(votes, (int, float)) or not observed:
        return None
    return 5.0 * bisect_right(observed, votes) / len(observed)
```

- [ ] **Step 4: Run tests for date pagination, HTTP 429 and malformed/empty responses.**
- [ ] **Step 5: Commit `feat: collect Hugging Face daily papers`.**

## Task 5: Scholar 알림 메일 가져오기

**Files:** Create `src/research_digest/sources/scholar_mail.py`, `tests/test_scholar_mail.py`, `tests/fixtures/scholar_alert.eml`.

**Interfaces:** `parse_scholar_message(raw: bytes, received_at: datetime) -> list[Paper]`; `ScholarMailSource(imap_factory).fetch(since: datetime, allowed_senders: set[str]) -> list[Paper]`. Parsed papers preserve the alert subject in source metadata; a Scholar-derived watch claim is only accepted after Semantic Scholar confirms the followed author/citation relationship. IMAP은 UID로만 식별하고 서버의 읽음 상태를 바꾸지 않는다.

- [ ] **Step 1: Write tests for multipart HTML/plain text mail, multiple paper links, stale `received_at`, malformed HTML, and non-Scholar sender rejection.**

```python
def test_old_or_untrusted_mail_is_ignored(fake_imap):
    source = ScholarMailSource(lambda: fake_imap)
    assert source.fetch(datetime(2026, 9, 29, tzinfo=timezone.utc), {"scholaralerts-noreply@google.com"}) == []
    assert fake_imap.marked_seen is False
```

- [ ] **Step 2: Run `python -m pytest tests/test_scholar_mail.py -q`; expect failure.**
- [ ] **Step 3: Use stdlib `email` and `imaplib` with `BODY.PEEK[]`, validate sender/date, parse anchors with a bounded HTML parser, unwrap Scholar redirect links, and ignore links without a plausible paper title.**

```python
message = email.message_from_bytes(raw, policy=email.policy.default)
sender = email.utils.parseaddr(message["from"] or "")[1].lower()
if sender not in allowed_senders or received_at < since:
    return []
```

- [ ] **Step 4: Run fixtures and a repeated-UID test proving unchanged mail creates no new candidate after the first scan.**
- [ ] **Step 5: Commit `feat: ingest Scholar alert emails without scraping`.**

## Task 6: Semantic Scholar 메타데이터와 팔로우 조회

**Files:** Create `src/research_digest/sources/semantic_scholar.py`, `tests/test_semantic_scholar.py`, `tests/fixtures/s2_author.json`, `tests/fixtures/s2_citations.json`.

**Interfaces:** `SemanticScholarSource(client: httpx.Client, api_key: str | None).author_papers(author_id: str, since: datetime) -> list[Paper]`, `.paper_citations(paper_id: str, since: datetime) -> list[Paper]`, `.paper_metrics(paper_ids: list[str]) -> dict[str, CitationMetric]`; `CitationMetric(count: int, publication_date: date | None, observed_at: datetime)`. S2 ID, `ARXIV:` ID, DOI를 허용하며 `Paper`에 실제 원문 URL과 ID를 저장한다.

- [ ] **Step 1: Write failing fixture tests for author pages, a citing paper, an empty page, pagination, and 429 backoff.**

```python
def test_author_pagination_and_since(s2_source):
    papers = s2_source.author_papers("12345", datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert [p.title for p in papers] == ["New Safety Paper", "New Reasoning Paper"]
    assert all(p.s2_id for p in papers)

def test_citation_carries_citing_paper_id(s2_source):
    papers = s2_source.paper_citations("ARXIV:2605.21849", datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert papers[0].s2_id == "citing-paper-id"
```

- [ ] **Step 2: Run `python -m pytest tests/test_semantic_scholar.py -q`; expect missing module failures.**
- [ ] **Step 3: Implement `/author/{id}/papers`, `/paper/{id}/citations` with explicit fields and offset pagination; use bounded pages, request timeout and `Retry-After` for 429.**

```python
FIELDS = "paperId,externalIds,title,abstract,authors,publicationDate,url,citationCount"

def _request_page(self, path: str, offset: int) -> dict:
    response = self.client.get(path, params={"fields": FIELDS, "offset": offset, "limit": 100})
    response.raise_for_status()
    return response.json()
```

- [ ] **Step 4: Run the adapter tests; assert a paper lacking an abstract remains a candidate with `abstract == ""` and one unavailable S2 endpoint raises a source-specific error.**
- [ ] **Step 5: Commit `feat: query Semantic Scholar follow-up metadata`.**

## Task 7: 근거 기반 평가와 3~5편 선정

**Files:** Create `src/research_digest/llm.py`, `selection.py`, `tests/test_selection.py`, `tests/fixtures/evaluations.json`.

**Interfaces:** `Topic` and `SelectionConfig` come from Task 1. `Evaluator(client: httpx.Client, base_url: str, model: str, api_key: str, store: Store, max_requests_per_day: int).evaluate(paper: Paper, topics: list[Topic]) -> Evaluation`; `Evaluation(topic_id: str | None, relevance: int, importance: int, evidence: int, fit: int, reason: str, contribution: str, limitation: str, cited_abstract_spans: list[str])`; `ScoredPaper(paper: Paper, evaluation: Evaluation, score: float, attention_label: str)`; `Rejection(paper: Paper, reason: str)`; `SelectionResult(selected: list[ScoredPaper], scored: list[ScoredPaper], rejected: list[Rejection])`; `select_daily(papers: list[Paper], evaluations: Mapping[str, Evaluation], config: SelectionConfig, attention: Mapping[str, float | None]) -> SelectionResult`. `importance`, `evidence`, `fit`, `relevance` are 1–5; LLM output is validated, abstract excerpts must be substrings of the supplied abstract, and invalid output fails that paper closed with a recorded reason. `max_requests_per_day` is checked against SQLite before each model call.

- [ ] **Step 1: Write failing tests for topical exclusions, hard thresholds, unknown attention, age-normalized S2 citations, 3 base/5 max, extra score >=4, at most two per topic, and the daily model-request cap.**

```python
def test_unknown_attention_requires_stronger_importance_and_evidence(selection_config):
    paper = Paper(title="Fresh work", abstract="We study robust generalization.")
    evaluation = Evaluation(topic_id="generalization", relevance=5, importance=4, evidence=3,
                            fit=5, reason="Relevant", contribution="Method", limitation="Small test",
                            cited_abstract_spans=["robust generalization"])
    result = select_daily([paper], {canonicalize(paper): evaluation}, selection_config,
                          {canonicalize(paper): None})
    assert result.selected == []
    assert "unknown attention" in result.rejected[0].reason

def test_never_invents_abstract_evidence(fake_llm):
    with pytest.raises(InvalidEvaluation, match="abstract"):
        fake_llm.evaluate(Paper(title="X", abstract="We test on one benchmark."), [])
```

- [ ] **Step 2: Run `python -m pytest tests/test_selection.py -q`; expect missing symbols.**
- [ ] **Step 3: Implement OpenAI-compatible `/chat/completions` JSON response parsing, escaped paper text as untrusted data, Pydantic score validation, request cap, and no model invocation for papers with no abstract.**

```python
payload = {"model": self.model, "response_format": {"type": "json_object"},
           "messages": [{"role": "system", "content": EVALUATION_RULES},
                        {"role": "user", "content": json.dumps({"title": paper.title,
                         "abstract": paper.abstract, "topics": [t.model_dump() for t in topics]})}]}
raw = self.client.post(f"{self.base_url}/chat/completions", json=payload,
                       headers={"Authorization": f"Bearer {self.api_key}"}).json()
evaluation = Evaluation.model_validate_json(raw["choices"][0]["message"]["content"])
```

- [ ] **Step 4: Implement configurable deterministic gates, proportional reweighting when attention is absent, within-day/topic attention normalization using Task 4 and age-normalized S2 citations, sorting and diversity; run tests including adversarial abstract instructions, empty candidate list, and ranking ties.**

```python
if ev.relevance < config.min_relevance or ev.importance < config.min_importance or ev.evidence < config.min_evidence:
    reject("minimum score")
elif attention_score is None and (ev.importance < config.unknown_attention_min or ev.evidence < config.unknown_attention_min):
    reject("unknown attention")
else:
    weights = {"importance": .30, "evidence": .30, "attention": .25, "fit": .15}
    if attention_score is None:
        weights = {k: v / .75 for k, v in weights.items() if k != "attention"}
```

- [ ] **Step 5: Commit `feat: select evidence-backed daily papers`.**

## Task 8: 읽기 쉬운 요약과 채널별 전달

**Files:** Create `src/research_digest/render.py`, `delivery.py`, `tests/test_render_delivery.py`.

**Interfaces:** `render_digest(result: SelectionResult, queued_events: list[WatchEvent], language: str) -> str`; `render_event(event: WatchEvent, language: str) -> str`; `Dispatcher(store: Store, transports: Mapping[str, Transport]).send(notification_id: str, subject: str, body: str, channels: list[str]) -> DeliveryReport`; `DeliveryReport(delivered: list[str], failed: dict[str, str])`; `Transport.send(subject: str, body: str) -> None`. Transports: `SmtpTransport`, `SlackWebhookTransport`, `DiscordWebhookTransport`, `MarkdownTransport`.

- [ ] **Step 1: Write failing tests for the `정독 후보`/`빠르게 훑어볼 후보` layout, source links, unknown attention and abstract-only caveat, secret-free errors, and partial channel failure after restart.**

```python
def test_partial_delivery_retries_only_failed_channel(tmp_path):
    store = Store(tmp_path / "state.db")
    ok, flaky = RecordingTransport(), FailOnceTransport()
    Dispatcher(store, {"email": ok, "slack": flaky}).send("digest:2026-09-30", "Papers", "Body", ["email", "slack"])
    Dispatcher(Store(tmp_path / "state.db"), {"email": ok, "slack": flaky}).send(
        "digest:2026-09-30", "Papers", "Body", ["email", "slack"])
    assert ok.calls == 1
    assert flaky.calls == 2
```

- [ ] **Step 2: Run `python -m pytest tests/test_render_delivery.py -q`; expect failure.**
- [ ] **Step 3: Render each selected paper's importance, actual contribution/evidence, observed attention or `미확인`, topic fit, limitation and URL; strip HTML from untrusted metadata; label abstract-only judgments.**

```python
def render_paper(item: ScoredPaper, label: str) -> str:
    return (f"### {label}: {escape(item.paper.title)}\n"
            f"문제: {escape(item.evaluation.reason)}\n"
            f"기여와 근거: {escape(item.evaluation.contribution)}\n"
            f"관심 신호: {item.attention_label}\n"
            f"한계: {escape(item.evaluation.limitation)}\n"
            f"초록 기반 평가 · [원문]({safe_url(item.paper.url)})")
```

- [ ] **Step 4: Implement SMTP/webhooks/atomic Markdown file writes; save subject/body before sending, reserve and mark each `(notification_id, channel)` in SQLite, retry transient failures at most three times, sanitize exception strings, and run the partial-failure test plus all rendering tests.**

```python
self.store.create_notification(notification_id, subject, body, channels)
for channel in channels:
    if self.store.was_delivered(notification_id, channel):
        continue
    if not self.store.reserve_delivery(notification_id, channel):
        continue
    try:
        self.transports[channel].send(subject, body)
    except DeliveryError as exc:
        report.failed[channel] = exc.safe_message
    else:
        self.store.mark_delivered(notification_id, channel)
```

- [ ] **Step 5: Commit `feat: deliver concise digests across configured channels`.**

## Task 9: 팔로우 이벤트 판정과 알림 제한

**Files:** Create `src/research_digest/watch.py`, `tests/test_watch.py`.

**Interfaces:** `WatchService(source: SemanticScholarSource, store: Store, evaluator: Evaluator).scan(watchlist: Watchlist, now: datetime, scholar_candidates: list[Paper] = []) -> list[WatchEvent]`; `WatchEvent(id: str, kind: Literal["author_paper", "paper_citation"], subject_id: str, paper: Paper, discovered_at: datetime, evaluation: Evaluation, delivery_policy: Literal["immediate", "next_digest"])`; `route_events(events: list[WatchEvent], policy: NotificationPolicy, store: Store, now: datetime, selected_today_ids: set[str]) -> tuple[list[WatchEvent], list[WatchEvent]]` returns immediate and queued. `Watchlist` and `NotificationPolicy(max_immediate_per_day: int = 3)` are config models from Task 1. First scan stores existing item IDs per watch and suppresses historical records; a new watch must not flood the inbox. Scholar candidates may enrich matching papers, but S2's author/citation relationship validates the event.

- [ ] **Step 1: Write failing tests for the first-run baseline, an actual new author paper, a relevant citing paper, an irrelevant citation, and a paper appearing in both digest and watch.**

```python
def test_first_scan_baselines_without_alerts(watch_service, watchlist, store, now):
    assert watch_service.scan(watchlist, now) == []
    assert store.get_watch_cursor("author:12345") is not None

def test_citation_is_not_an_alert_without_substantive_followup(watch_service, watchlist, store, now):
    store.set_watch_cursor("paper:ARXIV:2605.21849", now.isoformat())
    assert watch_service.scan(watchlist, now) == []
    assert store.watch_item_seen("paper:ARXIV:2605.21849", "irrelevant-citation-id")
```

- [ ] **Step 2: Run `python -m pytest tests/test_watch.py -q`; expect failure.**
- [ ] **Step 3: Compare S2 author and citation IDs against per-watch saved IDs; evaluate new citing papers against the followed paper's problem and user topic, apply author's optional topic filter, and store stable event IDs.**

```python
event_id = f"{kind}:{subject_id}:{canonicalize(candidate)}"
if store.watch_item_seen(subject_id, canonicalize(candidate)):
    continue
store.mark_watch_item_seen(subject_id, canonicalize(candidate))
if kind == "paper_citation" and (evaluation.relevance < 3 or evaluation.importance < 3):
    continue
if not store.seen(event_id):
    store.queue_event(event_id, event)
```

- [ ] **Step 4: Route each event by `immediate` or `next_digest`, cap immediate notifications at three per local calendar day, queue overflow, and suppress a watch item already selected in today's digest. Run tests across midnight and after reopening SQLite.**

```python
if event.paper.canonical_id in selected_today_ids:
    event.delivery_policy = "next_digest"
elif event.delivery_policy == "immediate" and store.immediate_count(local_day) < policy.max_immediate_per_day:
    immediate.append(event)
else:
    queued.append(event)
```

- [ ] **Step 5: Commit `feat: notify on meaningful follow-up research`.**

## Task 10: 실행 파이프라인, 시간표와 CLI 연결

**Files:** Create `src/research_digest/runner.py`, `schedule.py`, `tests/test_runner_schedule.py`; Modify `src/research_digest/cli.py`, `config.py`.

**Interfaces:** `Runner(config: AppConfig, store: Store, sources: list[Source], evaluator: Evaluator, dispatcher: Dispatcher, clock: Callable[[], datetime]).preview() -> PreviewReport`, `.run_digest(local_day: date) -> RunReport`, `.run_watch() -> RunReport`, `.tick(now: datetime) -> list[RunReport]`; `due_digest(now: datetime, timezone_name: str, digest_at: time, last_success_day: date | None) -> date | None`; `serve(runner_factory: Callable[[], Runner], sleep: Callable[[float], None]) -> None`. `Source.fetch(since: datetime) -> list[Paper]` is a thin wrapper around each Task 3–5 adapter's own fetch signature. `PreviewReport(scored: list[ScoredPaper], rejected: list[Rejection], sample_message: str)` and `RunReport(kind: str, source_failures: dict[str,str], delivery: DeliveryReport | None)` contain no credentials. `--offline-fixtures` injects local sample papers and recorded evaluations for `preview` only.

- [ ] **Step 1: Write failing tests for 09:00 local dispatch, one catch-up after a three-day pause, timezone change, DST repeated hour, `preview` read-only behavior, and one failed source not preventing other sources from running.**

```python
def test_catchup_is_one_digest_not_three(fake_runner, store):
    store.set_last_success("digest", date(2026, 9, 26))
    fake_runner.tick(datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc))  # 11:00 Seoul
    assert fake_runner.digest_calls == [date(2026, 9, 30)]

def test_preview_does_not_mutate_or_send(fake_runner, store):
    before = store.snapshot_counts()
    report = fake_runner.preview()
    assert report.scored
    assert store.snapshot_counts() == before
    assert fake_runner.sent == []
```

- [ ] **Step 2: Run `python -m pytest tests/test_runner_schedule.py -q`; expect failure.**
- [ ] **Step 3: Implement `due_digest` with `ZoneInfo`, local calendar date as idempotency key and `last_success_day`, `serve` with config reload at every poll, and one digest for the latest due day after downtime. Before new work, resend only pending notification channels from Task 2's saved payload; mark the digest day complete only after all enabled channels succeed.**

```python
def due_digest(now: datetime, timezone_name: str, digest_at: time,
               last_success_day: date | None) -> date | None:
    local = now.astimezone(ZoneInfo(timezone_name))
    today = local.date()
    if local.timetz().replace(tzinfo=None) < digest_at or last_success_day == today:
        return None
    return today
```

- [ ] **Step 4: Wire `preview`, `run --once`, `serve`, `follow paper|author <ID>`, and `unfollow paper|author <ID>` to config/store/runner; update YAML via temp file and atomic replace. Add `--offline-fixtures` to preview, loading local sample papers/evaluations without API keys. Continue other sources after a per-source exception.**

```python
for source in sources:
    try:
        candidates.extend(source.fetch(since))
    except SourceError as exc:
        report.source_failures[source.name] = exc.safe_message

for notification in store.pending_notifications():
    dispatcher.send(notification.id, notification.subject, notification.body,
                    notification.pending_channels)
```

- [ ] **Step 5: Run `python -m pytest tests/test_runner_schedule.py -q`, `python -m research_digest.cli --help`, and `python -m research_digest.cli preview --config config.example.yaml --offline-fixtures`; confirm no external send or state changes in preview.**
- [ ] **Step 6: Commit `feat: schedule daily and follow-up runs`.**

## Task 11: 공개용 문서, 배포와 재현 검증

**Files:** Create `README.md`, `config.example.yaml`, `LICENSE`, `CONTRIBUTING.md`, `Dockerfile`, `compose.yaml`, `.github/workflows/ci.yml`, `tests/test_cli_smoke.py`; Modify `.gitignore`, `pyproject.toml`.

**Interfaces:** `pip install .` exposes the `research-digest` console script; `python -m research_digest.cli preview --config config.example.yaml --offline-fixtures` works with no API keys, IMAP or SMTP; `docker compose up -d` runs `serve` against mounted user config and persistent state. `config.example.yaml` demonstrates AI safety/alignment, reasoning/agents, generalization/learning and interpretability with editable broad descriptions rather than one researcher's papers.

- [ ] **Step 1: Write a failing packaging/smoke test that loads the example config, runs offline preview and checks no secret-like strings or personal addresses in tracked files.**

```python
def test_example_config_and_offline_preview(tmp_path):
    cfg = load_config(Path("config.example.yaml"))
    result = CliRunner().invoke(app, ["preview", "--config", "config.example.yaml", "--offline-fixtures"])
    assert result.exit_code == 0
    assert "선정" in result.stdout
    assert cfg.profile.topics
```

- [ ] **Step 2: Run `python -m pytest tests/test_cli_smoke.py -q`; expect failure.**
- [ ] **Step 3: Write example YAML for configurable topic descriptions, sources, thresholds, IANA time, watchlist, channels and LLM environment-variable names; add MIT license and `.gitignore` for `config.yaml`, `.env*`, `*.db*`, generated digests.**

```yaml
schedule: {timezone: Asia/Seoul, digest_at: '09:00', watch_poll_minutes: 60}
selection: {base_count: 3, max_count: 5, extra_min_score: 4.0, max_per_topic: 2}
notifications: {max_immediate_per_day: 3, default_watch_policy: next_digest}
```

- [ ] **Step 4: Add README quick start (`python -m venv`, `pip install .`, `research-digest init/doctor/preview/serve`), complete config reference, Scholar IMAP setup, sample digest, provider-cost/request-cap note, the rare SMTP/webhook crash-window duplicate caveat, and self-hosting requirement; add Compose volume mounts and Python 3.11/3.12 CI. Keep optional live API/IMAP/SMTP smoke checks behind `pytest -m live`, outside CI.**

```yaml
strategy:
  matrix:
    python-version: ['3.11', '3.12']
steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-python@v5
    with: {python-version: '${{ matrix.python-version }}'}
  - run: pip install -e '.[dev]'
  - run: pytest -q
```

- [ ] **Step 5: Run `python -m pytest -q`, `python -m build`, install the wheel into a clean venv, and run the example offline preview. Verify `git status --short` and `git ls-files` contain no config secrets, database or generated digest.**
- [ ] **Step 6: Commit `docs: prepare public self-hosted release`.**

## Task 12: 공개 저장소 생성과 첫 릴리스 확인

**Files:** Review `README.md`, `config.example.yaml`, `pyproject.toml`, `.github/workflows/ci.yml`; no new source file.

**Interfaces:** Public GitHub repository `SungJun98/research-digest-agent` (or the user's chosen available name), `main` pushed with a usable README and passing CI. Keep the local checkout and remote URL in sync.

- [ ] **Step 1: Run a fresh full test, wheel install and offline preview from the final `main`; inspect `git diff --check`, `git status --short`, `git log -5 --oneline` and `git ls-files` for accidental personal data.**
- [ ] **Step 2: Create a public GitHub repository through an authenticated GitHub interface, add it as `origin`, push `main`, and open the repository page. If no authenticated route is available, preserve the finished local repository and report the exact publication blocker without claiming a public release.**
- [ ] **Step 3: Verify README rendering and first GitHub Actions run; if CI fails, fix the concrete failure locally, rerun the affected tests and push the repair.**
- [ ] **Step 4: Record the public repository URL and a sample installation command in the final handoff.**
