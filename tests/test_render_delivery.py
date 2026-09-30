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


def test_discord_chunk_progress_survives_failure_and_restart(tmp_path):
    import json
    from research_digest.delivery import Dispatcher,DiscordWebhookTransport
    from research_digest.store import Store
    accepted=[];calls=[0]
    def response(request):
        calls[0]+=1
        content=json.loads(request.content)['content']
        if calls[0]==2:return httpx.Response(500)
        accepted.append(content)
        return httpx.Response(204)
    store=Store(tmp_path/'state.db')
    client=httpx.Client(transport=httpx.MockTransport(response))
    dispatcher=Dispatcher(store,{'discord':DiscordWebhookTransport(client,'https://discord.com/api/webhooks/example')},sleep=lambda _:None)
    dispatcher.send('chunks','P','a'*1900+'b'*1900,['discord'])
    assert len(accepted)==len(set(accepted))==3
    assert store.notification_complete('chunks')


def test_smtp_partial_recipients_resume_only_failed_recipient(tmp_path,monkeypatch):
    from research_digest.delivery import Dispatcher,SmtpTransport
    from research_digest.config import EmailConfig
    from research_digest.store import Store
    accepted=[];attempts=[];fail=[True]
    class SMTP:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def starttls(self,**kwargs):pass
        def login(self,*args):pass
        def send_message(self,message,to_addrs=None):
            recipients=to_addrs or ['a@example.org','b@example.org']
            for recipient in recipients:
                attempts.append(recipient)
                if recipient=='b@example.org' and fail[0]:
                    fail[0]=False
                    return {recipient:(450,b'temporarily unavailable')}
                accepted.append(recipient)
            return {}
    monkeypatch.setattr('smtplib.SMTP',SMTP);monkeypatch.setenv('SMTP_PASSWORD','test-value')
    cfg=EmailConfig(enabled=True,host='smtp.example.org',sender='sender@example.org',recipients=['a@example.org','b@example.org'])
    store=Store(tmp_path/'state.db');transports={'email':SmtpTransport(cfg)}
    first=Dispatcher(store,transports,sleep=lambda _:None).send('recipients','P','B',['email'])
    Dispatcher(Store(tmp_path/'state.db'),transports,sleep=lambda _:None).send('recipients','P','B',['email'])
    assert accepted==['a@example.org','b@example.org']
    assert store.notification_complete('recipients')


def test_webhook_partial_progress_is_durable_across_process_restart(tmp_path):
    import json
    from research_digest.delivery import Dispatcher,DiscordWebhookTransport
    from research_digest.store import Store
    accepted=[];blocked=[True]
    def response(request):
        content=json.loads(request.content)['content']
        if blocked[0] and accepted:return httpx.Response(503)
        accepted.append(content)
        return httpx.Response(204)
    def transports():return {'discord':DiscordWebhookTransport(httpx.Client(transport=httpx.MockTransport(response)),'https://discord.com/api/webhooks/example')}
    first=Dispatcher(Store(tmp_path/'state.db'),transports(),sleep=lambda _:None).send('persist','P','a'*1900+'b'*1900,['discord'])
    assert first.failed and len(accepted)==1
    blocked[0]=False
    second=Dispatcher(Store(tmp_path/'state.db'),transports(),sleep=lambda _:None).send('persist','Changed','Changed',['discord'])
    assert second.delivered==['discord'] and len(accepted)==len(set(accepted))==3
