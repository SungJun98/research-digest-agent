"""Opt-in public read-only smoke tests; no mail or notification sending."""
import os
import httpx
import pytest
from datetime import datetime,timedelta,timezone

pytestmark=[pytest.mark.live,pytest.mark.skipif(os.environ.get('DIGEST_LIVE_SMOKE')!='1',reason='set DIGEST_LIVE_SMOKE=1 explicitly')]


def test_public_arxiv_and_huggingface():
    from research_digest.sources.arxiv import ArxivSource
    from research_digest.sources.huggingface import HuggingFaceSource
    now=datetime.now(timezone.utc)
    with httpx.Client() as client:
        arxiv=ArxivSource(client,max_results=2).fetch(['cat:cs.AI'],now-timedelta(days=14))
        assert isinstance(arxiv,list)
        hf=HuggingFaceSource(client,limit=2).fetch([now.date()])
        assert isinstance(hf,list)
