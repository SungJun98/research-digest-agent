import json

from typer.testing import CliRunner


def test_external_slack_stages_without_failure_and_acknowledges_only_known_payload(tmp_path):
    from research_digest.config import AppConfig,save_config,validate_secrets
    from research_digest.runtime import build_runner
    from research_digest.cli import app
    import httpx
    cfg=AppConfig.model_validate({'llm':{'enabled':False},'state_path':str(tmp_path/'state.db'),'notifications':{'slack':{'enabled':True,'transport':'external','workspace_name':'MLAI','channel_name':'paper-digest'},'markdown':{'enabled':False}}})
    assert validate_secrets(cfg,{})==[]
    path=tmp_path/'config.yaml';save_config(path,cfg)
    with httpx.Client() as client:
        runner=build_runner(cfg,client)
        key='digest:test'
        runner.store.create_notification(key,'Research digest','Saved immutable body',['slack'],['arxiv:2609.12345'],local_day='2026-09-30',kind='digest')
        report=runner.dispatcher.send(key,'Changed','Changed',['slack'])
        assert report.delivered==[] and report.failed=={}
        assert not runner.store.paper_delivered('arxiv:2609.12345','slack')
        cli=CliRunner()
        listed=cli.invoke(app,['outbox','--config',str(path)])
        data=json.loads(listed.output)
        assert data[0]['body']=='Saved immutable body' and data[0]['id']==key
        cfg.notifications.slack.enabled=False;save_config(path,cfg)
        disabled=cli.invoke(app,['outbox','--claim','--config',str(path)])
        assert json.loads(disabled.output)==[]
        cfg.notifications.slack.enabled=True;save_config(path,cfg)
        claimed=cli.invoke(app,['outbox','--claim','--config',str(path)])
        assert claimed.exit_code==0,claimed.output
        assert json.loads(claimed.output)[0]['id']==key
        assert json.loads(cli.invoke(app,['outbox','--claim','--config',str(path)]).output)==[]
        rejected=cli.invoke(app,['ack',key,'--message-url','https://example.org/fake','--config',str(path)])
        assert rejected.exit_code!=0
        assert not runner.store.was_delivered(key,'slack')
        ack=cli.invoke(app,['ack',key,'--message-url','https://mlai.slack.com/archives/C123/p1234567890123456','--config',str(path)])
        assert ack.exit_code==0,ack.output
        assert runner.store.paper_delivered('arxiv:2609.12345','slack')
        assert json.loads(cli.invoke(app,['outbox','--config',str(path)]).output)==[]
        unknown=cli.invoke(app,['ack','missing','--message-url','https://app.slack.com/archives/C123/p1234567890123456','--config',str(path)])
        assert unknown.exit_code!=0


def test_external_recovered_digest_consumes_today_slot_and_receipt_is_idempotent(tmp_path):
    from datetime import datetime,timedelta,timezone
    from zoneinfo import ZoneInfo
    from research_digest.config import AppConfig,save_config
    from research_digest.runtime import build_runner
    from research_digest.cli import app
    import httpx
    cfg=AppConfig.model_validate({'llm':{'enabled':False},'state_path':str(tmp_path/'state.db'),'notifications':{'slack':{'enabled':True,'transport':'external','channel_id':'C123'},'markdown':{'enabled':False}}})
    path=tmp_path/'config.yaml';save_config(path,cfg)
    today=datetime.now(timezone.utc).astimezone(ZoneInfo(cfg.schedule.timezone)).date()
    old_day=(today-timedelta(days=2)).isoformat()
    with httpx.Client() as client:
        runner=build_runner(cfg,client)
        calls=[]
        class Source:
            name='source'
            def fetch(self,*args,**kwargs):calls.append(True);return []
        runner.sources=[Source()]
        runner.store.create_notification('old','Old digest','Original',['slack'],['arxiv:2609.12345'],local_day=old_day,kind='digest')
        result=CliRunner().invoke(app,['ack','old','--message-url','https://mlai.slack.com/archives/C123/p1234567890123456','--config',str(path)])
        assert result.exit_code==0,result.output
        runner.run_digest(today)
        assert calls==[]
        assert runner.store.last_success('digest_covered_day')==today.isoformat()
        assert runner.store.last_success('digest')==old_day
        # Repeating an acknowledgement tomorrow must not suppress tomorrow's work.
        runner.store.set_last_success('digest_covered_day',old_day)
        again=CliRunner().invoke(app,['ack','old','--message-url','https://mlai.slack.com/archives/C123/p1234567890123456','--config',str(path)])
        assert again.exit_code==0
        assert runner.store.last_success('digest_covered_day')==old_day


def test_external_outbox_resolves_alias_delivery_and_claims_only_one_digest_day(tmp_path):
    from research_digest.config import AppConfig,save_config
    from research_digest.store import Store
    from research_digest.models import Paper
    from research_digest.cli import app
    cfg=AppConfig.model_validate({'llm':{'enabled':False},'state_path':str(tmp_path/'state.db'),'notifications':{'slack':{'enabled':True,'transport':'external'},'markdown':{'enabled':False}}})
    path=tmp_path/'config.yaml';save_config(path,cfg)
    store=Store(cfg.state_path)
    a=Paper(title='A',arxiv_id='2609.12345');b=Paper(title='B',s2_id='a'*40)
    store.upsert_papers([a,b])
    store.create_notification('watch:a','A','A',['slack'],[a.canonical_id],kind='immediate')
    store.create_notification('watch:b','B','B',['slack'],[b.canonical_id],kind='immediate')
    store.mark_delivered('watch:a','slack')
    store.upsert_papers([Paper(title='Merged',arxiv_id='2609.12345',s2_id='a'*40)])
    cli=CliRunner()
    result=cli.invoke(app,['outbox','--claim','--config',str(path)])
    assert result.exit_code==0,result.output
    assert json.loads(result.output)==[]
    assert store.notification_complete('watch:b')
    store.create_notification('day1','Day 1','One',['slack'],['arxiv:2609.12346'],local_day='2026-09-28',kind='digest')
    store.create_notification('day2','Day 2','Two',['slack'],['arxiv:2609.12347'],local_day='2026-09-29',kind='digest')
    assert [n['id'] for n in json.loads(cli.invoke(app,['outbox','--claim','--config',str(path)]).output)]==['day1']


def test_external_receipt_write_failure_rolls_back_delivery_and_recovery_markers(tmp_path):
    from research_digest.config import AppConfig,save_config
    from research_digest.store import Store
    from research_digest.cli import app
    cfg=AppConfig.model_validate({'llm':{'enabled':False},'state_path':str(tmp_path/'state.db'),'notifications':{'slack':{'enabled':True,'transport':'external'}}})
    path=tmp_path/'config.yaml';save_config(path,cfg)
    store=Store(cfg.state_path)
    store.create_notification('receipt','Digest','Body',['slack'],['arxiv:2609.12345'],local_day='2026-09-30',kind='digest')
    with store.connection() as db:
        db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON cache WHEN NEW.namespace='external_delivery_receipt' BEGIN SELECT RAISE(ABORT,'test failure'); END;")
    result=CliRunner().invoke(app,['ack','receipt','--message-url','https://mlai.slack.com/archives/C123/p1234567890123456','--config',str(path)])
    assert result.exit_code!=0
    assert not store.was_delivered('receipt','slack')
    assert store.last_success('digest_covered_day') is None
