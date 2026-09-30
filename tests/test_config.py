from pathlib import Path

import pytest


def test_invalid_timezone_and_unknown_fields(tmp_path):
    from research_digest.config import load_config
    path = tmp_path / 'config.yaml'
    path.write_text('schedule:\n  timezone: Mars/Olympus\n')
    with pytest.raises(ValueError, match='timezone'):
        load_config(path)
    path.write_text('selection:\n  unknown_option: 1\n')
    with pytest.raises(ValueError, match='unknown_option'):
        load_config(path)


def test_secret_values_are_rejected_and_missing_names_reported():
    from research_digest.config import AppConfig, validate_secrets
    config = AppConfig.model_validate({'llm': {'enabled': False}, 'notifications': {'email': {
        'enabled': True, 'host': 'smtp.example.org', 'sender': 'from@example.org',
        'recipients': ['to@example.org'], 'password_env': 'SMTP_PASSWORD'}}})
    assert validate_secrets(config, {}) == ['SMTP_PASSWORD']
    assert validate_secrets(config, {'SMTP_PASSWORD': 'never-print-me'}) == []
    with pytest.raises(ValueError):
        AppConfig.model_validate({'llm': {'api_key': 'secret'}})


def test_invalid_selection_and_embedding_configuration():
    from research_digest.config import AppConfig
    with pytest.raises(ValueError, match='max_count'):
        AppConfig.model_validate({'selection': {'base_count': 5, 'max_count': 3}})
    with pytest.raises(ValueError, match='embedding'):
        AppConfig.model_validate({'retrieval': {'embeddings_enabled': True}})
    with pytest.raises(ValueError, match='weights'):
        AppConfig.model_validate({'selection': {'weights': {'importance': 0, 'evidence': 0, 'attention': 0, 'fit': 0}}})


def test_initialization_does_not_overwrite_existing_file(tmp_path):
    from research_digest.config import load_config, write_initial_config
    path = tmp_path / 'config.yaml'
    write_initial_config(path, {'timezone': 'Asia/Seoul', 'digest_at': '09:00'})
    config = load_config(path)
    assert config.schedule.digest_at.hour == 9
    assert {'safety', 'reasoning'} <= {t.id for t in config.profile.topics}
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_initial_config(path, {})
    assert path.read_bytes() == original


def test_doctor_never_prints_secret(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from research_digest.cli import app
    from research_digest.config import write_initial_config
    path = tmp_path / 'config.yaml'
    write_initial_config(path, {'model': 'configured-model'})
    monkeypatch.setenv('DIGEST_LLM_API_KEY', 'never-print-me')
    result = CliRunner().invoke(app, ['doctor', '--config', str(path)])
    assert result.exit_code == 0
    assert 'never-print-me' not in result.stdout
