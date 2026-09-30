from pathlib import Path
import httpx


def test_html_sections_bounds_cache_and_no_foreign_url(tmp_path):
    from research_digest.sources.fulltext import FulltextSource
    from research_digest.sources import RateLimiter
    from research_digest.store import Store
    from research_digest.models import Paper
    calls=[]
    def response(request):
        calls.append(request)
        return httpx.Response(200,text=Path('tests/fixtures/arxiv_paper.html').read_text())
    source=FulltextSource(httpx.Client(transport=httpx.MockTransport(response)),Store(tmp_path/'state.db'),limiter=RateLimiter(0))
    paper=Paper(title='P',arxiv_id='2609.12345',url='https://arxiv.org/abs/2609.12345v2')
    context=source.fetch(paper,8000)
    assert context.coverage=='partial_html' and len(context.text)<=8000
    assert 'Introduction' in context.text and 'References' not in context.text and 'Ignore' not in context.text
    assert source.fetch(paper,50).text == context.text[:50] and len(calls)==1
    assert source.fetch(Paper(title='P',arxiv_id='https://evil.org/x')) is None


def test_missing_large_or_redirected_html_falls_back(tmp_path):
    from research_digest.sources.fulltext import FulltextSource
    from research_digest.sources import RateLimiter
    from research_digest.store import Store
    from research_digest.models import Paper
    for response in [httpx.Response(404),httpx.Response(302,headers={'Location':'https://evil.org/x'}),httpx.Response(200,content=b'x'*2_100_000)]:
        source=FulltextSource(httpx.Client(transport=httpx.MockTransport(lambda _,r=response:r)),Store(tmp_path/'state.db'),limiter=RateLimiter(0))
        assert source.fetch(Paper(title='P',arxiv_id='2609.12345')) is None


def test_timeout_falls_back(tmp_path):
    from research_digest.sources.fulltext import FulltextSource
    from research_digest.sources import RateLimiter
    from research_digest.store import Store
    from research_digest.models import Paper
    def timeout(request): raise httpx.ReadTimeout('timeout',request=request)
    source=FulltextSource(httpx.Client(transport=httpx.MockTransport(timeout)),Store(tmp_path/'state.db'),limiter=RateLimiter(0))
    assert source.fetch(Paper(title='P',arxiv_id='2609.12345')) is None
