from pathlib import Path
from datetime import datetime,date,time,timezone,timedelta
import pytest
from research_digest.config import AppConfig
from research_digest.store import Store
from research_digest.models import Paper,Evaluation
from research_digest.delivery import Dispatcher

NOW=datetime(2026,9,30,2,tzinfo=timezone.utc)


def test_local_time_catchup_timezone_and_dst():
    from research_digest.schedule import due_digest
    assert due_digest(NOW,'Asia/Seoul',time(9),date(2026,9,26))==date(2026,9,30)
    assert due_digest(NOW,'UTC',time(9),None) is None
    assert due_digest(NOW,'Asia/Seoul',time(9),date(2026,9,30)) is None
    assert due_digest(datetime(2026,11,1,5,30,tzinfo=timezone.utc),'America/New_York',time(1,30),None)==date(2026,11,1)
    assert due_digest(datetime(2026,11,1,6,30,tzinfo=timezone.utc),'America/New_York',time(1,30),date(2026,11,1)) is None


class Source:
    name='good'
    def fetch(self,since,preview=False):
        return [Paper(title=f'Paper {i}',arxiv_id=f'2609.{10000+i}',abstract='Verification reduces failures.',url=f'https://arxiv.org/abs/2609.{10000+i}',seen_at=NOW) for i in range(5)]


class Eval:
    def __init__(self):self.reassessed=[]
    def evaluate(self,paper,topics):
        i=int(paper.arxiv_id[-1])
        ev=Evaluation.model_validate_json(Path('tests/fixtures/evaluations.json').read_text())
        return ev.model_copy(update={'topic_id':topics[i%len(topics)].id,'problem_concepts':[f'p{i}'],'method_concepts':[f'm{i}']})
    def reassess(self,paper,evaluation,context):
        self.reassessed.append(paper.canonical_id)
        return evaluation.model_copy(update={'evidence':4,'coverage':'partial_html'})


class Transport:
    def __init__(self):self.sent=[];self.fail=False
    def send(self,subject,body):
        self.sent.append(body)
        if self.fail:raise RuntimeError('secret')


def setup(tmp_path,sources=None):
    from research_digest.runner import Runner
    cfg=AppConfig(state_path=tmp_path/'state.db');store=Store(cfg.state_path);transport=Transport();evaluator=Eval()
    runner=Runner(cfg,store,sources or [Source()],evaluator,Dispatcher(store,{'markdown':transport}),clock=lambda:NOW)
    return runner,store,transport,evaluator


def test_preview_is_readonly_and_source_failures_isolated(tmp_path):
    from research_digest.sources import SourceError
    class Bad:
        name='bad'
        def fetch(self,since,preview=False):raise SourceError('bad: unavailable')
    runner,store,transport,_=setup(tmp_path,[Bad(),Source()])
    before=store.snapshot_counts(exclude={'llm_usage','cache'})
    report=runner.preview()
    assert report.scored and report.sample_message and report.coverage_warnings
    assert store.snapshot_counts(exclude={'llm_usage','cache'})==before and not transport.sent
    run=runner.run_digest(NOW.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).date())
    assert run.source_failures=={'bad':'source unavailable'} and transport.sent


def test_failed_digest_restarts_original_payload_and_catchup_once(tmp_path):
    runner,store,transport,_=setup(tmp_path)
    transport.fail=True
    store.set_last_success('digest',date(2026,9,26))
    runner.tick(NOW)
    assert store.last_success('digest')=='2026-09-26'
    original=transport.sent[0]
    transport.fail=False
    runner.tick(NOW+timedelta(minutes=1))
    assert store.last_success('digest')=='2026-09-30' and transport.sent[-1]==original
    count=len(transport.sent)
    runner.tick(NOW+timedelta(minutes=2))
    assert len(transport.sent)==count


def test_fulltext_before_final_evidence_gate_and_top_k(tmp_path):
    from research_digest.models import FulltextContext
    runner,_,_,evaluator=setup(tmp_path)
    original=evaluator.evaluate
    evaluator.evaluate=lambda paper,topics:original(paper,topics).model_copy(update={'evidence':3})
    class HTML:
        def fetch(self,paper,max_chars):return FulltextContext(text='Evidence',url='https://arxiv.org/html/'+paper.arxiv_id)
    runner.fulltext=HTML();runner.config.retrieval.fulltext_top_k=2
    report=runner.preview()
    assert len(evaluator.reassessed)==2
    assert 'Paper' in report.sample_message and '본문 일부 확인' in report.sample_message


def test_offline_cli_makes_no_network_calls_and_no_user_state(tmp_path,monkeypatch):
    import httpx
    from typer.testing import CliRunner
    from research_digest.cli import app
    from research_digest.config import write_initial_config
    import yaml
    def forbidden(*args,**kwargs):raise AssertionError('network forbidden')
    monkeypatch.setattr(httpx.Client,'request',forbidden)
    path=tmp_path/'profile.yaml';write_initial_config(path,{})
    raw=yaml.safe_load(path.read_text());raw['state_path']=str(tmp_path/'never.db');path.write_text(yaml.safe_dump(raw))
    before=path.read_bytes()
    result=CliRunner().invoke(app,['preview','--config',str(path),'--offline-fixtures'])
    assert result.exit_code==0,result.output
    assert '정독 후보' in result.output and not (tmp_path/'never.db').exists() and path.read_bytes()==before


def test_follow_unfollow_and_guided_channels(tmp_path):
    from typer.testing import CliRunner
    from research_digest.cli import app
    from research_digest.config import load_config
    runner=CliRunner();path=tmp_path/'profile.yaml'
    # timezone, time, language, topics, provider, model, channels, follow policy, poll
    result=runner.invoke(app,['init','--config',str(path)],input='Asia/Seoul\n09:00\nko\n\nhttps://example.org/v1\nm\nmarkdown,slack\nnext_digest\n60\n')
    assert result.exit_code==0,result.output
    cfg=load_config(path)
    assert cfg.notifications.slack.enabled and cfg.notifications.markdown.enabled
    assert runner.invoke(app,['follow','paper','https://arxiv.org/abs/2605.21849v2','--policy','immediate','--config',str(path)]).exit_code==0
    assert load_config(path).watchlist.papers[0].id=='ARXIV:2605.21849'
    assert runner.invoke(app,['follow','author','Some Person','--config',str(path)]).exit_code==2
    assert runner.invoke(app,['unfollow','paper','ARXIV:2605.21849','--config',str(path)]).exit_code==0
    assert not load_config(path).watchlist.papers


def test_total_evaluation_failure_is_retryable_not_empty_success(tmp_path):
    from research_digest.llm import InvalidEvaluation
    runner,store,transport,evaluator=setup(tmp_path)
    def unavailable(paper,topics):raise InvalidEvaluation('provider unavailable')
    evaluator.evaluate=unavailable
    report=runner.run_digest(date(2026,9,30))
    assert report.source_failures.get('evaluation')
    assert not transport.sent and store.last_success('digest') is None


def test_preview_exposes_candidate_scores_and_rejection_reasons(tmp_path):
    import yaml
    from typer.testing import CliRunner
    from research_digest.cli import app
    from research_digest.config import write_initial_config
    path=tmp_path/'config.yaml';write_initial_config(path,{})
    raw=yaml.safe_load(path.read_text());raw['selection']['unknown_attention_min']=5;path.write_text(yaml.safe_dump(raw))
    result=CliRunner().invoke(app,['preview','--config',str(path),'--offline-fixtures'])
    assert result.exit_code==0
    assert 'arxiv:2609.99001' in result.output and 'unknown attention' in result.output and '4.00' in result.output


def test_watch_baseline_catalog_is_not_daily_discovery(tmp_path):
    from research_digest.watch import WatchService
    from research_digest.config import Watchlist,AuthorWatch
    runner,store,_,evaluator=setup(tmp_path)
    historical=Paper(title='Historical 2016 work',abstract='Old work',s2_id='a'*40,published_at=datetime(2016,1,1,tzinfo=timezone.utc),seen_at=NOW)
    class Catalog:
        def author_papers(self,author_id,since):return [historical]
    watch=WatchService(Catalog(),store,evaluator)
    assert watch.scan(Watchlist(authors=[AuthorWatch(id='123')]),NOW)==[]
    papers,_=runner._collect(NOW)
    assert historical.canonical_id not in {p.canonical_id for p in papers}
    assert store.get_paper(historical.canonical_id) is not None


def test_pending_immediate_and_digest_share_one_delivery_per_paper_channel(tmp_path):
    runner,store,transport,_=setup(tmp_path)
    p=Source().fetch(NOW)[0]
    store.upsert_papers([p])
    store.create_notification('event:old','Immediate','WATCH '+p.canonical_id,['markdown'],[p.canonical_id],kind='immediate',local_day='2026-09-29')
    original=transport.send
    def fail_immediate(subject,body):
        if subject=='Immediate':raise RuntimeError('temporarily unavailable')
        original(subject,body)
    transport.send=fail_immediate
    runner.run_digest(date(2026,9,30))
    assert all(p.canonical_id not in body for body in transport.sent)
    transport.send=original
    runner.run_watch()
    assert sum(p.canonical_id in body for body in transport.sent)==1


def test_recovered_old_digest_consumes_todays_digest_slot(tmp_path):
    runner,store,transport,_=setup(tmp_path)
    store.create_notification('old','Old digest','Old body',['markdown'],local_day='2026-09-25',kind='digest')
    runner.tick(NOW)
    runner.tick(NOW+timedelta(minutes=1))
    assert transport.sent==['Old body']
    assert store.last_success('digest_covered_day')=='2026-09-30'
