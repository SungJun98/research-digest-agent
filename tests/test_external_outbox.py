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
