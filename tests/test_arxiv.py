from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest


def test_arxiv_fresh_metadata_and_shared_throttle():
    from research_digest.sources.arxiv import ArxivSource, RateLimiter
    fixture = Path('tests/fixtures/arxiv.xml').read_text()
    times, requests = [0.0], []
    def sleep(seconds):
        times[0] += seconds
    def respond(request):
        requests.append(times[0])
        return httpx.Response(200, text=fixture)
    client = httpx.Client(transport=httpx.MockTransport(respond))
    limiter = RateLimiter(3, lambda: times[0], sleep)
    first = ArxivSource(client, limiter=limiter)
    second = ArxivSource(client, limiter=limiter)
    since = datetime(2026, 9, 29, tzinfo=timezone.utc)
    papers = first.fetch(['cat:cs.AI'], since)
    second.fetch(['cat:cs.LG'], since)
    assert [p.arxiv_id for p in papers] == ['2609.12345']
    assert papers[0].abstract and papers[0].authors == ['A Researcher']
    assert papers[0].published_at.utcoffset().total_seconds() == 0
    assert papers[0].seen_at == datetime(2026,9,30,tzinfo=timezone.utc)
    assert requests == [0, 3]


def test_arxiv_retries_and_malformed_response():
    from research_digest.sources import SourceError
    from research_digest.sources.arxiv import ArxivSource, RateLimiter
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(429 if len(calls) < 3 else 200, text='<broken>')
    client = httpx.Client(transport=httpx.MockTransport(respond))
    source = ArxivSource(client, limiter=RateLimiter(0), sleep=lambda _: None)
    with pytest.raises(SourceError, match='arXiv'):
        source.fetch(['cat:cs.AI'], datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert len(calls) == 3
