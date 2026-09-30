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


if __name__ == '__main__':
    app()
