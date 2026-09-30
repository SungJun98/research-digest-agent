from pathlib import Path
import httpx


def test_render_provenance_bounds_escaping_and_links():
    from research_digest.render import render_digest,safe_url
    from research_digest.models import Paper,Evaluation
    from research_digest.selection import ScoredPaper,SelectionResult
    ev=Evaluation.model_validate_json(Path('tests/fixtures/evaluations.json').read_text())
    p=Paper(title='<script>secret</script>Reliable [paper]',url='https://arxiv.org/abs/2609.12345',arxiv_id='2609.12345')
    a=ScoredPaper(p,ev,4,'attention unknown')
    b=ScoredPaper(p.model_copy(update={'title':'Second'}),ev.model_copy(update={'coverage':'partial_html'}),4,'HF votes 12')
    body=render_digest(SelectionResult([a,b],[a,b],[]),[],'ko')
    assert '정독 후보' in body and '빠르게 훑어볼 후보' in body
    assert '초록 기반' in body and '본문 일부 확인' in body
    assert '<script>' not in body and '[원문](https://arxiv.org/abs/2609.12345)' in body
    assert '관심 미확인' in body
    explanatory=[line for line in body.splitlines() if line.startswith(('문제:','기여·근거:','관심 주제:','관심·한계:','읽을 질문:'))]
    assert len(explanatory)==10 and sum(len(line) for line in explanatory[:5])<=400
    assert safe_url('javascript:alert(1)')=='' and safe_url('https://example.org/x\nsecret')==''


def test_restart_partial_failure_keeps_original_body(tmp_path):
    from research_digest.delivery import Dispatcher,DeliveryError
    from research_digest.store import Store
    class Recording:
        def __init__(self,fail=False): self.calls=[];self.fail=fail
        def send(self,subject,body):
            self.calls.append((subject,body))
            if self.fail: self.fail=False;raise DeliveryError('DO_NOT_LEAK_SECRET')
    store=Store(tmp_path/'state.db');ok=Recording();flaky=Recording(True)
    report=Dispatcher(store,{'email':ok,'slack':flaky},sleep=lambda _:None).send('digest:d','Original','Original body',['email','slack'])
    assert 'DO_NOT_LEAK_SECRET' not in str(report.failed) and report.failed
    Dispatcher(Store(tmp_path/'state.db'),{'email':ok,'slack':flaky}).send('digest:d','Changed','Changed body',['email','slack'])
    assert len(ok.calls)==1 and len(flaky.calls)==2
    assert flaky.calls[-1]==('Original','Original body')


def test_transient_retries_markdown_and_discord_chunking(tmp_path):
    from research_digest.delivery import Dispatcher,DeliveryError,MarkdownTransport,DiscordWebhookTransport
    from research_digest.store import Store
    calls=[]
    class Transient:
        def send(self,subject,body):
            calls.append(body)
            if len(calls)<3:raise DeliveryError('unavailable',retryable=True)
    dispatcher=Dispatcher(Store(tmp_path/'state.db'),{'email':Transient()},sleep=lambda _:None)
    assert dispatcher.send('x','P','B',['email']).delivered==['email'] and len(calls)==3
    transport=MarkdownTransport(tmp_path/'digests');transport.send('P','B')
    assert list((tmp_path/'digests').glob('*.md'))[0].read_text().endswith('B\n')
    payloads=[]
    def response(request):
        import json
        payloads.append(json.loads(request.content)['content'])
        return httpx.Response(204)
    DiscordWebhookTransport(httpx.Client(transport=httpx.MockTransport(response)),'https://discord.com/api/webhooks/example').send('P','x'*4500)
    assert len(payloads)==3 and max(map(len,payloads))<=1900
