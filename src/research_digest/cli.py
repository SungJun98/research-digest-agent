"""Guided setup and command entry point."""
from __future__ import annotations

import os
from pathlib import Path

import typer
from pydantic import ValidationError

from .config import default_config_path, load_config, validate_secrets, write_initial_config

app = typer.Typer(no_args_is_help=True, help='Personal research digests and meaningful follow-up alerts.')


def read_config(path: Path):
    try:
        return load_config(path)
    except ValidationError as exc:
        fields = ', '.join('.'.join(map(str, e['loc'])) for e in exc.errors(include_input=False))
        typer.echo(f'설정 오류: {fields}', err=True)
        raise typer.Exit(2) from None
    except (OSError, ValueError):
        typer.echo('설정 파일을 읽거나 검증하지 못했습니다.', err=True)
        raise typer.Exit(2) from None


@app.command()
def init(config: Path = typer.Option(default_config_path(), '--config'), non_interactive: bool = typer.Option(False, '--non-interactive')):
    """Create user configuration; existing files are preserved."""
    answers = {}
    if not non_interactive:
        answers = {'timezone': typer.prompt('시간대', default='Asia/Seoul'),
                   'digest_at': typer.prompt('일일 추천 시간', default='09:00'),
                   'language': typer.prompt('요약 언어', default='ko'),
                   'topics': typer.prompt('관심 주제 설명 (세미콜론으로 구분, 빈 값은 기본 주제)', default=''),
                   'base_url': typer.prompt('LLM 호환 API 주소', default='https://api.openai.com/v1'),
                   'model': typer.prompt('모델 이름 (제공자에서 사용 가능한 모델)', default='')}
        answers['channels'] = typer.prompt('알림 채널 (markdown,email,slack,discord 쉼표 구분)', default='markdown')
        if 'email' in answers['channels'].split(','):
            answers['smtp_host'] = typer.prompt('SMTP 호스트')
            answers['smtp_sender'] = typer.prompt('발신 이메일')
            answers['smtp_recipients'] = typer.prompt('수신 이메일 (쉼표 구분)')
        answers['watch_policy'] = typer.prompt('팔로우 알림 방식 (immediate/next_digest)', default='next_digest')
        answers['watch_poll_minutes'] = typer.prompt('팔로우 확인 간격 (분)', default='60')
    try:
        write_initial_config(config, answers)
    except FileExistsError:
        typer.echo('설정 파일이 이미 존재합니다. 직접 편집해 주세요.', err=True)
        raise typer.Exit(2) from None
    except (OSError, ValueError):
        typer.echo('초기 설정을 저장하지 못했습니다. 입력값과 경로를 확인해 주세요.', err=True)
        raise typer.Exit(2) from None
    typer.echo(f'설정 저장: {config.expanduser()}')
    typer.echo('환경변수에 API 키를 설정하고, 설정 파일에서 관심 주제와 알림 채널을 편집하세요.')


@app.command()
def doctor(config: Path = typer.Option(default_config_path(), '--config')):
    """Check configuration and environment variable names without exposing secrets."""
    cfg = read_config(config)
    missing = validate_secrets(cfg, os.environ)
    if missing or (cfg.llm.enabled and not cfg.llm.model):
        if missing:
            typer.echo('필요한 환경변수: ' + ', '.join(missing))
        if cfg.llm.enabled and not cfg.llm.model:
            typer.echo('llm.model을 설정해 주세요.')
        raise typer.Exit(1)
    typer.echo(f'설정 확인 완료: {cfg.schedule.timezone} {cfg.schedule.digest_at:%H:%M}')
    typer.echo('정확한 예약 실행에는 serve를 상시 실행해야 합니다.')


@app.command()
def feedback(paper_id: str, kind: str = typer.Option(..., '--kind'), topic: str | None = typer.Option(None, '--topic'), config: Path = typer.Option(default_config_path(), '--config')):
    """Record explicit useful/not_relevant/already_known/weak_evidence feedback."""
    from datetime import datetime, timezone
    from .store import Store
    from .feedback import FeedbackService
    cfg = read_config(config)
    if not cfg.feedback.enabled:
        typer.echo('피드백 기능이 비활성화되어 있습니다.', err=True)
        raise typer.Exit(2)
    if topic and topic not in {t.id for t in cfg.profile.topics}:
        typer.echo('알 수 없는 주제 ID입니다.', err=True)
        raise typer.Exit(2)
    try:
        FeedbackService(Store(cfg.state_path)).record(paper_id,kind,topic,datetime.now(timezone.utc))
    except ValueError:
        typer.echo('논문 ID 또는 피드백 종류를 확인해 주세요.', err=True)
        raise typer.Exit(2) from None
    typer.echo('명시적 피드백을 저장했습니다. 설정 변경 제안은 preview에서 확인하세요.')



def _ready(cfg):
    missing = validate_secrets(cfg,os.environ)
    if missing or (cfg.llm.enabled and not cfg.llm.model):
        typer.echo('doctor로 모델 및 환경변수 설정을 확인해 주세요.',err=True)
        raise typer.Exit(2)


@app.command()
def preview(config: Path = typer.Option(default_config_path(),'--config'), offline_fixtures: bool = typer.Option(False,'--offline-fixtures')):
    """Preview ranking and a digest without sending or changing delivery/watch state."""
    import tempfile
    import httpx
    from .runtime import build_runner
    from .offline import offline_runner
    cfg=read_config(config)
    if offline_fixtures:
        with tempfile.TemporaryDirectory() as temporary:
            report=offline_runner(cfg,Path(temporary)/'state.db').preview()
        typer.echo('오프라인 합성 예제입니다. 실제 논문 추천이 아닙니다.')
    else:
        _ready(cfg)
        with httpx.Client() as client:report=build_runner(cfg,client).preview()
    typer.echo(report.sample_message)
    typer.echo(f'후보 검색: {report.retrieval_mode} · 평가 {len(report.scored)} · 추천 {len(report.selected)}')
    rejected = {item.paper.canonical_id:item.reason for item in report.rejected}
    selected = {item.paper.canonical_id for item in report.selected}
    typer.echo('후보별 평가 (중요성/근거/적합성/관련성):')
    for item in sorted(report.scored,key=lambda item:(-item.score,item.paper.canonical_id)):
        ev=item.evaluation
        status='선정' if item.paper.canonical_id in selected else rejected.get(item.paper.canonical_id,'미선정')
        typer.echo(f'{item.paper.canonical_id} · {item.score:.2f}/5 · {ev.importance}/{ev.evidence}/{ev.fit}/{ev.relevance} · {status}')
    assessed={item.paper.canonical_id for item in report.scored}
    for item in report.rejected:
        if item.paper.canonical_id not in assessed:typer.echo(f'{item.paper.canonical_id} · 평가 없음 · {item.reason}')
    for warning in report.coverage_warnings:typer.echo('누락: '+warning)
    for suggestion in report.profile_suggestions:
        typer.echo(f'설정 제안: {suggestion.topic_id or "global"}.{suggestion.field} → {suggestion.proposed_value} ({suggestion.reason})')


@app.command()
def run(once: bool = typer.Option(False,'--once'), config: Path = typer.Option(default_config_path(),'--config')):
    """Perform one digest and watch run now; use serve for scheduled execution."""
    import httpx
    from zoneinfo import ZoneInfo
    from .runtime import build_runner
    if not once:
        typer.echo('--once를 지정하거나 serve를 사용하세요.',err=True)
        raise typer.Exit(2)
    cfg=read_config(config);_ready(cfg)
    with httpx.Client() as client:
        runner=build_runner(cfg,client)
        reports=[runner.run_digest(runner.clock().astimezone(ZoneInfo(cfg.schedule.timezone)).date()),runner.run_watch()]
    failed=False
    for report in reports:
        failures=report.source_failures or (report.delivery.failed if report.delivery else {})
        if failures:
            failed=True
            typer.echo(report.kind+': 일부 작업 미완료; preview/doctor를 확인하세요.',err=True)
        else:typer.echo(report.kind+': 실행 완료')
    if failed:raise typer.Exit(1)


@app.command()
def serve(config: Path = typer.Option(default_config_path(),'--config')):
    """Stay running and reload configuration every minute."""
    import httpx
    from .runtime import build_runner
    from .schedule import serve as loop
    cfg=read_config(config);_ready(cfg)
    typer.echo(f'예약 실행 시작: {cfg.schedule.timezone} {cfg.schedule.digest_at:%H:%M}')
    try:
        with httpx.Client() as client:
            def factory():
                current=read_config(config);_ready(current)
                return build_runner(current,client)
            loop(factory)
    except KeyboardInterrupt:typer.echo('예약 실행을 종료했습니다.')



def _watch_id(kind,identifier):
    from .identity import normalize_watch_id
    try:return normalize_watch_id(kind,identifier)
    except ValueError:
        typer.echo('Semantic Scholar author ID 또는 arXiv/DOI/S2 paper ID를 사용하세요.',err=True)
        raise typer.Exit(2) from None


@app.command()
def follow(kind: str, identifier: str, policy: str | None = typer.Option(None,'--policy'), topic_filter: bool = typer.Option(True,'--topic-filter/--no-topic-filter'), config: Path = typer.Option(default_config_path(),'--config')):
    """Follow paper citations or an author; first scan establishes a quiet baseline."""
    from .config import AuthorWatch,PaperWatch,save_config
    cfg=read_config(config);identifier=_watch_id(kind,identifier)
    policy=policy or cfg.notifications.default_watch_policy
    if policy not in {'immediate','next_digest'}:
        typer.echo('policy는 immediate 또는 next_digest입니다.',err=True);raise typer.Exit(2)
    entries=cfg.watchlist.authors if kind=='author' else cfg.watchlist.papers
    existing=next((e for e in entries if e.id==identifier),None)
    if existing:
        existing.policy=policy
        if kind=='author':existing.topic_filter=topic_filter
    else:entries.append(AuthorWatch(id=identifier,policy=policy,topic_filter=topic_filter) if kind=='author' else PaperWatch(id=identifier,policy=policy))
    save_config(config,cfg)
    typer.echo(f'팔로우 저장: {kind} {identifier} ({policy})')


@app.command()
def unfollow(kind: str, identifier: str, config: Path = typer.Option(default_config_path(),'--config')):
    """Remove a watch from configuration."""
    from .config import save_config
    cfg=read_config(config);identifier=_watch_id(kind,identifier)
    if kind=='author':cfg.watchlist.authors=[e for e in cfg.watchlist.authors if e.id!=identifier]
    else:cfg.watchlist.papers=[e for e in cfg.watchlist.papers if e.id!=identifier]
    save_config(config,cfg);typer.echo(f'팔로우 해제: {kind} {identifier}')


if __name__ == '__main__':
    app()
