from datetime import datetime,timezone
from typer.testing import CliRunner


def test_explicit_feedback_requires_distinct_papers_and_preserves_config(tmp_path):
    from research_digest.store import Store
    from research_digest.models import Paper
    from research_digest.config import AppConfig,write_initial_config
    from research_digest.feedback import FeedbackService
    config_path=tmp_path/'profile.yaml';write_initial_config(config_path,{})
    before=config_path.read_bytes();config=AppConfig();before_model=config.model_dump()
    store=Store(tmp_path/'state.db');service=FeedbackService(store)
    store.upsert_papers([Paper(title=f'P{i}',arxiv_id=str(i)) for i in range(4)])
    assert service.suggest(config)==[]
    for _ in range(4):service.record('arxiv:0','useful','reasoning',datetime.now(timezone.utc))
    assert service.suggest(config)==[]
    service.record('arxiv:1','useful','reasoning',datetime.now(timezone.utc))
    assert service.suggest(config)==[]
    service.record('arxiv:2','useful','reasoning',datetime.now(timezone.utc))
    proposal=service.suggest(config)[0]
    assert proposal.field=='priority' and proposal.proposed_value==4 and len(proposal.supporting_paper_ids)==3
    assert config_path.read_bytes()==before and config.model_dump()==before_model
    for i in range(3):service.record(f'arxiv:{i}','already_known','reasoning',datetime.now(timezone.utc))
    assert service.suggest(config)==[]


def test_feedback_cli_and_unknown_ids(tmp_path):
    from research_digest.cli import app
    from research_digest.config import write_initial_config,load_config
    from research_digest.store import Store
    from research_digest.models import Paper
    import yaml
    path=tmp_path/'config.yaml';write_initial_config(path,{})
    raw=yaml.safe_load(path.read_text());raw['state_path']=str(tmp_path/'state.db');path.write_text(yaml.safe_dump(raw))
    store=Store(tmp_path/'state.db');store.upsert_papers([Paper(title='P',arxiv_id='2609.12345',metadata={'topic_id':'safety'})])
    runner=CliRunner()
    assert runner.invoke(app,['feedback','arxiv:2609.12345','--kind','useful','--config',str(path)]).exit_code==0
    assert store.list_feedback()[0]['topic_id']=='safety'
    assert runner.invoke(app,['feedback','arxiv:missing','--kind','useful','--config',str(path)]).exit_code==2
    assert runner.invoke(app,['feedback','arxiv:2609.12345','--kind','skip','--config',str(path)]).exit_code==2
