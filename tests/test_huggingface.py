from datetime import date
from pathlib import Path
import httpx
import pytest


def test_observed_zero_unknown_and_date_pagination():
    from research_digest.sources.huggingface import HuggingFaceSource
    calls = []
    def respond(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, text=Path('tests/fixtures/hf_daily.json').read_text())
    papers = HuggingFaceSource(httpx.Client(transport=httpx.MockTransport(respond))).fetch([date(2026,9,29),date(2026,9,30)])
    assert len(calls) == 2 and calls[1]['date'] == '2026-09-30'
    assert papers[0].arxiv_id == '2609.12345'
    assert papers[0].signals['hf_upvotes'] == 0
    assert papers[0].signals['hf_daily_rank'] == 1
    assert papers[0].metadata['hf_posted_date'] == '2026-09-30'
    assert papers[0].seen_at is not None
    assert 'hf_upvotes' not in papers[1].signals
    assert papers[0].authors == ['A Researcher']


def test_hf_retry_empty_and_invalid():
    from research_digest.sources.huggingface import HuggingFaceSource
    from research_digest.sources import SourceError
    responses = [httpx.Response(429),httpx.Response(200,json=[]),httpx.Response(200,json={})]
    source = HuggingFaceSource(httpx.Client(transport=httpx.MockTransport(lambda _: responses.pop(0))),sleep=lambda _:None)
    assert source.fetch([date(2026,9,30)]) == []
    with pytest.raises(SourceError):
        source.fetch([date(2026,9,30)])
