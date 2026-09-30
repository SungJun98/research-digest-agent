"""Validated public configuration. Secret values belong in environment variables."""
from __future__ import annotations

import json
import re
from datetime import time
from pathlib import Path
from typing import Annotated, Literal, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EnvName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
Policy = Literal['immediate', 'next_digest']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Topic(StrictModel):
    id: str = Field(min_length=1, pattern=r'^[a-zA-Z0-9_-]+$')
    description: str = Field(min_length=1)
    priority: int = Field(default=2, ge=1, le=5)
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


def default_topics() -> list[Topic]:
    return [
        Topic(id='safety', priority=3, description='AI safety and alignment: risk evaluation, oversight, control, reward hacking, robust alignment and substantive preference optimization.', include=['AI safety', 'alignment', 'oversight', 'reward hacking', 'preference optimization']),
        Topic(id='reasoning', priority=3, description='Reasoning and decision-making: verification, search, candidate comparison, reliable agents, adaptive computation and test-time scaling.', include=['reasoning', 'verification', 'agents', 'test-time scaling']),
        Topic(id='learning', description='Learning and generalization: uncertainty, probabilistic learning, transfer, distribution shift and learning principles.', include=['generalization', 'uncertainty', 'Bayesian', 'distribution shift']),
        Topic(id='interpretability', description='Interpretability and model behavior: mechanisms, faithful explanations, causal interventions and understanding failures.', include=['interpretability', 'mechanistic', 'faithfulness', 'model behavior']),
    ]


class ProfileConfig(StrictModel):
    topics: list[Topic] = Field(default_factory=default_topics, min_length=1)
    lenses: list[str] = Field(default_factory=lambda: ['Trustworthy decisions under uncertainty', 'Robustness under changing conditions', 'Efficient use of data and computation'])
    exclude: list[str] = Field(default_factory=lambda: ['Diffusion language model decoding without broader reasoning or reliability contributions'])
    summary_language: str = 'ko'

    @field_validator('topics')
    @classmethod
    def unique_topics(cls, topics):
        if len({t.id for t in topics}) != len(topics):
            raise ValueError('duplicate topic IDs')
        return topics


class SelectionConfig(StrictModel):
    min_relevance: int = Field(default=3, ge=1, le=5)
    min_importance: int = Field(default=3, ge=1, le=5)
    min_evidence: int = Field(default=3, ge=1, le=5)
    unknown_attention_min: int = Field(default=4, ge=1, le=5)
    base_min_score: float = Field(default=3.5, ge=0, le=5)
    base_count: int = Field(default=3, ge=1, le=5)
    max_count: int = Field(default=5, ge=1, le=5)
    extra_min_score: float = Field(default=4.0, ge=0, le=5)
    max_per_topic: int = Field(default=2, ge=1, le=5)
    max_adjacent: int = Field(default=1, ge=0, le=5)
    mmr_relevance_weight: float = Field(default=.85, ge=0, le=1)
    duplicate_semantic_threshold: float = Field(default=.9, ge=0, le=1)
    duplicate_jaccard_threshold: float = Field(default=.8, ge=0, le=1)
    weights: dict[str, float] = Field(default_factory=lambda: {'importance': .30, 'evidence': .30, 'attention': .25, 'fit': .15})

    @model_validator(mode='after')
    def valid_selection(self):
        if self.max_count < self.base_count:
            raise ValueError('max_count must be >= base_count')
        if set(self.weights) != {'importance', 'evidence', 'attention', 'fit'} or any(v < 0 for v in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise ValueError('weights must contain four nonnegative factors with a positive sum')
        return self


class ScheduleConfig(StrictModel):
    timezone: str = 'Asia/Seoul'
    digest_at: time = time(9, 0)
    watch_poll_minutes: int = Field(default=60, ge=5)
    catchup: bool = True

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('invalid timezone') from exc
        return value


class ArxivConfig(StrictModel):
    enabled: bool = True
    categories: list[str] = Field(default_factory=lambda: ['cs.AI', 'cs.LG', 'cs.CL'])
    queries: list[str] = Field(default_factory=list)
    max_results: int = Field(default=200, ge=1, le=2000)


class HFConfig(StrictModel):
    enabled: bool = True
    limit: int = Field(default=100, ge=1, le=500)


class ScholarMailConfig(StrictModel):
    enabled: bool = False
    host: str = 'imap.gmail.com'
    port: int = 993
    mailbox: str = 'INBOX'
    username_env: EnvName = 'SCHOLAR_IMAP_USERNAME'
    password_env: EnvName = 'SCHOLAR_IMAP_PASSWORD'
    allowed_senders: list[str] = Field(default_factory=lambda: ['scholaralerts-noreply@google.com'])
    max_messages: int = Field(default=100, ge=1, le=1000)


class S2Config(StrictModel):
    enabled: bool = True
    api_key_env: EnvName = 'SEMANTIC_SCHOLAR_API_KEY'
    max_pages: int = Field(default=10, ge=1, le=100)


class SourcesConfig(StrictModel):
    arxiv: ArxivConfig = Field(default_factory=ArxivConfig)
    huggingface: HFConfig = Field(default_factory=HFConfig)
    scholar_mail: ScholarMailConfig = Field(default_factory=ScholarMailConfig)
    semantic_scholar: S2Config = Field(default_factory=S2Config)


class RetrievalConfig(StrictModel):
    top_k_per_topic: int = Field(default=10, ge=1, le=100)
    extra_candidates: int = Field(default=10, ge=0, le=100)
    max_evaluations: int = Field(default=50, ge=1, le=500)
    lookback_hours: int = Field(default=72, ge=1, le=168)
    catchup_days: int = Field(default=7, ge=1, le=30)
    embeddings_enabled: bool = False
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_key_env: EnvName = 'DIGEST_EMBEDDING_API_KEY'
    fulltext_enabled: bool = True
    fulltext_top_k: int = Field(default=8, ge=0, le=50)
    fulltext_max_chars: int = Field(default=8000, ge=500, le=32000)

    @model_validator(mode='after')
    def valid_embedding(self):
        if self.embeddings_enabled and (not self.embedding_base_url or not self.embedding_model):
            raise ValueError('embedding provider URL and model required')
        return self


class FeedbackConfig(StrictModel):
    enabled: bool = True
    suggestions_enabled: bool = True
    min_explicit_signals: int = Field(default=3, ge=3)


class BaseWatch(StrictModel):
    id: str = Field(min_length=1)
    policy: Policy = 'next_digest'


class PaperWatch(BaseWatch):
    @field_validator('id')
    @classmethod
    def stable_paper_id(cls,value):
        from .identity import normalize_watch_id
        return normalize_watch_id('paper',value)


class AuthorWatch(BaseWatch):
    topic_filter: bool = True

    @field_validator('id')
    @classmethod
    def stable_author_id(cls,value):
        from .identity import normalize_watch_id
        return normalize_watch_id('author',value)


class Watchlist(StrictModel):
    papers: list[PaperWatch] = Field(default_factory=list)
    authors: list[AuthorWatch] = Field(default_factory=list)


class EmailConfig(StrictModel):
    enabled: bool = False
    host: str = ''
    port: int = 587
    sender: str = ''
    recipients: list[str] = Field(default_factory=list)
    username_env: EnvName | None = None
    password_env: EnvName = 'SMTP_PASSWORD'
    security: Literal['starttls', 'ssl'] = 'starttls'

    @model_validator(mode='after')
    def valid_email(self):
        if self.enabled and (not self.host or not self.sender or not self.recipients):
            raise ValueError('email host, sender and recipients required')
        return self


class WebhookConfig(StrictModel):
    enabled: bool = False
    url_env: EnvName


class SlackConfig(WebhookConfig):
    url_env: EnvName = 'DIGEST_SLACK_WEBHOOK'
    transport: Literal['webhook', 'external'] = 'webhook'
    workspace_name: str = ''
    channel_name: str = ''
    channel_id: str | None = Field(default=None, pattern=r'^[CG][A-Z0-9]+$')


class MarkdownConfig(StrictModel):
    enabled: bool = True
    directory: Path = Path('~/.local/share/research-digest/digests')


class NotificationConfig(StrictModel):
    max_immediate_per_day: int = Field(default=3, ge=0, le=20)
    default_watch_policy: Policy = 'next_digest'
    max_chars_per_paper: int = Field(default=400, ge=100, le=2000)
    email: EmailConfig = Field(default_factory=EmailConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    discord: WebhookConfig = Field(default_factory=lambda: WebhookConfig(url_env='DIGEST_DISCORD_WEBHOOK'))
    markdown: MarkdownConfig = Field(default_factory=MarkdownConfig)


class LLMConfig(StrictModel):
    enabled: bool = True
    backend: Literal['api', 'codex_cli'] = 'api'
    base_url: str = 'https://api.openai.com/v1'
    model: str = ''
    codex_command: str = 'codex'
    codex_timeout_seconds: int = Field(default=240, ge=10, le=1800)
    codex_batch_size: int = Field(default=5, ge=1, le=10)
    api_key_env: EnvName = 'DIGEST_LLM_API_KEY'
    max_requests_per_day: int = Field(default=80, ge=1, le=10000)
    max_output_tokens: int = Field(default=1800, ge=200, le=10000)
    json_mode: bool = True


class AppConfig(StrictModel):
    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    watchlist: Watchlist = Field(default_factory=Watchlist)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    state_path: Path = Path('~/.local/share/research-digest/state.db')


def default_config_path() -> Path:
    return Path('~/.config/research-digest/config.yaml').expanduser()


def load_config(path: Path) -> AppConfig:
    try:
        raw = yaml.safe_load(path.expanduser().read_text(encoding='utf-8')) or {}
    except yaml.YAMLError as exc:
        raise ValueError('Invalid YAML') from exc
    return AppConfig.model_validate(raw)


def write_initial_config(path: Path, answers: dict[str, str]) -> None:
    cfg = AppConfig()
    if 'timezone' in answers:
        cfg.schedule.timezone = answers['timezone']
    if 'digest_at' in answers:
        cfg.schedule.digest_at = time.fromisoformat(answers['digest_at'])
    cfg.profile.summary_language = answers.get('language', 'ko')
    cfg.llm.model = answers.get('model', '')
    cfg.llm.base_url = answers.get('base_url', cfg.llm.base_url)
    if answers.get('topics'):
        cfg.profile.topics = [Topic(id=f'topic_{i+1}', description=t.strip()) for i, t in enumerate(answers['topics'].split(';')) if t.strip()]
    if 'channels' in answers:
        channels = {c.strip() for c in answers['channels'].split(',') if c.strip()}
        if not channels or channels-{'email','slack','discord','markdown'}:
            raise ValueError('invalid channels')
        for name in ['email','slack','discord','markdown']:
            getattr(cfg.notifications,name).enabled = name in channels
        if 'email' in channels:
            cfg.notifications.email.host = answers.get('smtp_host','')
            cfg.notifications.email.sender = answers.get('smtp_sender','')
            cfg.notifications.email.recipients = [r.strip() for r in answers.get('smtp_recipients','').split(',') if r.strip()]
    if 'watch_policy' in answers:
        cfg.notifications.default_watch_policy = answers['watch_policy']
    if 'watch_poll_minutes' in answers:
        cfg.schedule.watch_poll_minutes = int(answers['watch_poll_minutes'])
    cfg = AppConfig.model_validate(cfg.model_dump())
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(yaml.safe_dump(cfg.model_dump(mode='json'), allow_unicode=True, sort_keys=False))
    path.chmod(0o600)


def validate_secrets(cfg: AppConfig, env: Mapping[str, str]) -> list[str]:
    required: list[str] = []
    if cfg.llm.enabled and cfg.llm.backend == 'api':
        required.append(cfg.llm.api_key_env)
    if cfg.retrieval.embeddings_enabled:
        required.append(cfg.retrieval.embedding_key_env)
    if cfg.sources.scholar_mail.enabled:
        required += [cfg.sources.scholar_mail.username_env, cfg.sources.scholar_mail.password_env]
    if cfg.notifications.email.enabled:
        required.append(cfg.notifications.email.password_env)
        if cfg.notifications.email.username_env:
            required.append(cfg.notifications.email.username_env)
    if cfg.notifications.slack.enabled and cfg.notifications.slack.transport == 'webhook':
        required.append(cfg.notifications.slack.url_env)
    if cfg.notifications.discord.enabled:
        required.append(cfg.notifications.discord.url_env)
    return sorted({name for name in required if not env.get(name)})


def save_config(path: Path, cfg: AppConfig) -> None:
    """Validate then atomically replace an existing private configuration."""
    import os
    import tempfile
    cfg = AppConfig.model_validate(cfg.model_dump())
    path = path.expanduser()
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w',dir=path.parent,encoding='utf-8',delete=False) as handle:
            temporary = handle.name
            handle.write(yaml.safe_dump(cfg.model_dump(mode='json'),allow_unicode=True,sort_keys=False))
        os.replace(temporary,path)
        path.chmod(0o600)
    finally:
        if temporary and os.path.exists(temporary):os.unlink(temporary)
