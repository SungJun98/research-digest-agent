from pathlib import Path
from datetime import datetime, timezone
import httpx
import pytest

SINCE = datetime(2026,9,1,tzinfo=timezone.utc)


def test_author_pagination_citation_missing_abstract_and_metrics():
    from research_digest.sources.semantic_scholar import SemanticScholarSource
    def respond(request):
        if '/citations' in request.url.path:
            return httpx.Response(200,text=Path('tests/fixtures/s2_citations.json').read_text())
        if '/author/' in request.url.path:
            if request.url.params['offset'] == '0':
                return httpx.Response(200,text=Path('tests/fixtures/s2_author.json').read_text())
            return httpx.Response(200,json={'data':[{'paperId':'b','title':'New Reasoning Paper','publicationDate':'2026-09-20'}]})
        return httpx.Response(200,json={'paperId':'a','title':'New Safety Paper','citationCount':0,'publicationDate':'2026-09-10'})
    source = SemanticScholarSource(httpx.Client(transport=httpx.MockTransport(respond)),None,interval=0)
    papers = source.author_papers('12345',SINCE)
    assert [p.title for p in papers] == ['New Safety Paper','New Reasoning Paper']
    assert papers[0].abstract == '' and all(p.s2_id for p in papers)
    assert papers[0].seen_at is not None
    assert source.paper_citations('ARXIV:2605.21849',SINCE)[0].s2_id == 'citing-paper-id'
    assert source.paper_metrics(['a'])['a'].count == 0


def test_s2_retry_empty_unavailable_and_page_bound():
    from research_digest.sources.semantic_scholar import SemanticScholarSource
    from research_digest.sources import SourceError
    responses=[httpx.Response(429,headers={'Retry-After':'1'}),httpx.Response(200,json={'data':[]}),httpx.Response(404)]
    waits=[]
    source = SemanticScholarSource(httpx.Client(transport=httpx.MockTransport(lambda _:responses.pop(0))),None,interval=0,sleep=waits.append)
    assert source.author_papers('1',SINCE) == [] and 1 in waits
    with pytest.raises(SourceError): source.paper_citations('bad',SINCE)
    source = SemanticScholarSource(httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'data':[{'paperId':'a','title':'P'}],'next':100}))),None,interval=0,max_pages=1)
    with pytest.raises(SourceError,match='page limit'): source.author_papers('1',SINCE)


@pytest.mark.parametrize('item',[None,123,{'paperId':'x','title':'P','authors':[None]}])
def test_s2_malformed_paper_is_source_error(item):
    from research_digest.sources.semantic_scholar import SemanticScholarSource
    from research_digest.sources import SourceError
    source=SemanticScholarSource(httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'data':[item]}))),None,interval=0)
    with pytest.raises(SourceError):source.author_papers('1',SINCE)
