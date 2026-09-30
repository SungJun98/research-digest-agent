from pathlib import Path
import re
from typer.testing import CliRunner


def test_public_release_assets_and_offline_preview():
    from research_digest.cli import app
    from research_digest.config import load_config
    cfg=load_config(Path('config.example.yaml'))
    assert cfg.profile.topics and cfg.selection.max_count==5
    assert Path('LICENSE').exists() and 'MIT License' in Path('LICENSE').read_text()
    assert Path('README.md').exists() and 'offline-fixtures' in Path('README.md').read_text()
    assert Path('compose.yaml').exists() and Path('.github/workflows/ci.yml').exists()
    result=CliRunner().invoke(app,['preview','--config','config.example.yaml','--offline-fixtures'])
    assert result.exit_code==0 and '정독 후보' in result.output


def test_packaged_fixtures_and_no_private_values():
    from importlib.resources import files
    assert files('research_digest').joinpath('demo/sample.html').is_file()
    for root in [Path('src'),Path('config.example.yaml')]:
        paths=root.rglob('*') if root.is_dir() else [root]
        for path in paths:
            if path.suffix not in {'.py','.yaml','.json','.html'}:continue
            text=path.read_text()
            assert not re.search(r'sk-[A-Za-z0-9_-]{24,}',text)
            assert 'BEGIN PRIVATE KEY' not in text
