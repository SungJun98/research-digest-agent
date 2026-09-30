import json
from pathlib import Path

import pytest
from typer.testing import CliRunner


def fake_codex(tmp_path, mode='normal'):
    data=json.loads(Path('tests/fixtures/evaluations.json').read_text())
    script=tmp_path/'fake-codex'
    script.write_text('''#!/usr/bin/env python3
import json, sys
from pathlib import Path
if sys.argv[1:]==['login','status']:
    print('Logged in using ChatGPT'); sys.exit(0)
args=sys.argv[1:]
assert '--ignore-user-config' in args and '--ephemeral' in args
assert args[args.index('--sandbox')+1]=='read-only'
for feature in ['shell_tool','apps','plugins','hooks']:
    assert any(args[i:i+2]==['--disable',feature] for i in range(len(args)-1))
payload=json.loads(sys.stdin.read().split('\\nINPUT_JSON\\n')[-1])
counter=Path(__file__+'.calls')
counter.write_text(str(int(counter.read_text())+1 if counter.exists() else 1))
data=DATA
mode=MODE
if mode=='failed': sys.exit(1)
if 'items' in payload:
    result={'evaluations':[{'paper_id':p['paper_id'],'evaluation':data} for p in payload['items']]}
    if mode=='partial': result['evaluations']=result['evaluations'][:1]
else: result=data
if mode=='invented': result=dict(data,evidence_spans=[{'text':'Invented evidence','source':'abstract','url':'https://arxiv.org/abs/2609.12345'}])
Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(result))
print(json.dumps({'type':'turn.completed'}))
'''.replace('DATA',repr(data)).replace('MODE',repr(mode)))
    script.chmod(0o700)
    return script


def example_paper():
    from research_digest.models import Paper
    return Paper(title='Oversight',abstract='Verification reduces failures.',arxiv_id='2609.12345',url='https://arxiv.org/abs/2609.12345')


def build(tmp_path,mode='normal',limit=80):
    from research_digest.codex import CodexEvaluator
    from research_digest.config import Topic
    from research_digest.store import Store
    command=fake_codex(tmp_path,mode)
    evaluator=CodexEvaluator(str(command),'',Store(tmp_path/'state.db'),max_requests_per_day=limit,batch_size=5)
    return evaluator,command,[Topic(id='safety',description='Safety and alignment')]


def test_codex_evaluation_uses_login_and_preserves_validation_cache_budget(tmp_path):
    from research_digest.llm import InvalidEvaluation
    evaluator,command,topics=build(tmp_path,limit=1)
    paper=example_paper()
    result=evaluator.evaluate(paper,topics)
    assert result.evidence==4 and result.topic_id=='safety'
    assert evaluator.evaluate(paper,topics)==result
    assert Path(str(command)+'.calls').read_text()=='1'
    with pytest.raises(InvalidEvaluation,match='budget'):
        evaluator.evaluate(paper.model_copy(update={'title':'Changed title'}),topics)


@pytest.mark.parametrize('mode',['failed','invented'])
def test_codex_failure_or_unsupported_evidence_is_rejected(tmp_path,mode):
    from research_digest.llm import InvalidEvaluation
    evaluator,_,topics=build(tmp_path,mode)
    with pytest.raises(InvalidEvaluation):evaluator.evaluate(example_paper(),topics)


def test_codex_batch_keeps_valid_partial_results_without_individual_retry_storm(tmp_path):
    from research_digest.runner import evaluate_candidates
    evaluator,command,topics=build(tmp_path,'partial')
    papers=[example_paper(),example_paper().model_copy(update={'title':'Other contribution','arxiv_id':'2609.12346'})]
    warnings=[]
    results=evaluate_candidates(papers,evaluator,topics,warnings)
    assert list(results)==['arxiv:2609.12345']
    assert len(warnings)==1
    assert Path(str(command)+'.calls').read_text()=='1'


def test_codex_doctor_requires_no_api_key_or_explicit_model(tmp_path):
    from research_digest.config import AppConfig,save_config,validate_secrets
    from research_digest.cli import app
    command=fake_codex(tmp_path)
    config=AppConfig.model_validate({'llm':{'backend':'codex_cli','codex_command':str(command)}})
    assert validate_secrets(config,{})==[]
    path=tmp_path/'config.yaml';save_config(path,config)
    result=CliRunner().invoke(app,['doctor','--config',str(path)])
    assert result.exit_code==0,result.output
    assert 'API' not in result.output


def test_codex_runtime_selects_cli_backend(tmp_path):
    import httpx
    from research_digest.config import AppConfig
    from research_digest.runtime import build_runner
    from research_digest.codex import CodexEvaluator
    config=AppConfig.model_validate({'llm':{'backend':'codex_cli','codex_command':str(fake_codex(tmp_path))},'state_path':str(tmp_path/'state.db')})
    with httpx.Client() as client:
        runner=build_runner(config,client)
        assert isinstance(runner.evaluator,CodexEvaluator)
