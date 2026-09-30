from __future__ import annotations

import time
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import httpx
from ..models import Paper
from . import ARXIV_LIMITER, RateLimiter, SourceError, request

ATOM = '{http://www.w3.org/2005/Atom}'


class ArxivSource:
    def __init__(self, client: httpx.Client, clock=None, sleep=time.sleep, limiter=None, max_results=200):
        self.client, self.sleep = client, sleep
        self.limiter = limiter or (RateLimiter(3, clock, sleep) if clock else ARXIV_LIMITER)
        self.max_results = min(1000, max_results)

    def fetch(self, queries: list[str], since: datetime) -> list[Paper]:
        result = []
        for query in queries:
            response = request(self.client, 'https://export.arxiv.org/api/query', label='arXiv', params={
                'search_query': query, 'start': 0, 'max_results': self.max_results,
                'sortBy': 'lastUpdatedDate', 'sortOrder': 'descending',
            }, limiter=self.limiter, sleep=self.sleep)
            try:
                root = ET.fromstring(response.content)
                if root.tag != ATOM + 'feed':
                    raise ValueError()
                for entry in root.findall(ATOM + 'entry'):
                    def value(tag):
                        return ' '.join((entry.findtext(ATOM + tag) or '').split())
                    updated = datetime.fromisoformat(value('updated').replace('Z', '+00:00')).astimezone(timezone.utc)
                    if updated < since:
                        continue
                    url = value('id').replace('http://', 'https://')
                    if not url.startswith('https://arxiv.org/abs/'):
                        raise ValueError()
                    result.append(Paper(title=value('title'), abstract=value('summary'),
                        authors=[a.findtext(ATOM+'name') or '' for a in entry.findall(ATOM+'author')],
                        url=url, arxiv_id=url, published_at=value('published'), first_seen_at=updated,
                        sources={'arxiv'}, metadata={'updated_at': updated.isoformat()}))
            except (ET.ParseError, ValueError, TypeError):
                raise SourceError('arXiv: invalid Atom response') from None
        return result
