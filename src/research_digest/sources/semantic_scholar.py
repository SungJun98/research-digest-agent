from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, timezone
from urllib.parse import quote
import time
from ..models import Paper
from . import RateLimiter, SourceError, request_json

FIELDS = 'paperId,externalIds,title,abstract,authors,publicationDate,url,citationCount'
BASE = 'https://api.semanticscholar.org/graph/v1'


@dataclass
class CitationMetric:
    count: int
    publication_date: date | None
    observed_at: datetime


class SemanticScholarSource:
    def __init__(self, client, api_key=None, max_pages=10, interval=1, sleep=time.sleep):
        self.client, self.max_pages, self.sleep = client, max_pages, sleep
        self.headers = {'x-api-key': api_key} if api_key else {}
        self.limiter = RateLimiter(interval,sleep=sleep)

    def _get(self, path, params=None):
        data = request_json(self.client,BASE+path,label='Semantic Scholar',params=params or {'fields':FIELDS},
                            headers=self.headers,limiter=self.limiter,sleep=self.sleep)
        if not isinstance(data,dict): raise SourceError('Semantic Scholar: invalid response')
        return data

    @staticmethod
    def _paper(data):
        try:
            external = data.get('externalIds') or {}
            published = data.get('publicationDate')
            return Paper(s2_id=data['paperId'],doi=external.get('DOI'),arxiv_id=external.get('ArXiv'),
                title=data['title'],abstract=data.get('abstract') or '',
                authors=[a['name'] for a in data.get('authors',[]) if a.get('name')],
                url=data.get('url') or f"https://www.semanticscholar.org/paper/{data['paperId']}",
                published_at=published+'T00:00:00Z' if published else None,
                seen_at=datetime.now(timezone.utc),sources={'semantic_scholar'},
                signals={'s2_citations':data['citationCount']} if isinstance(data.get('citationCount'),int) and data['citationCount'] >= 0 else {})
        except (KeyError,TypeError,ValueError):
            raise SourceError('Semantic Scholar: invalid paper') from None

    def _pages(self,path,since,wrapped=False):
        result, offset, seen = [], 0, set()
        for _ in range(self.max_pages):
            data = self._get(path,{'fields':FIELDS,'offset':offset,'limit':100})
            if not isinstance(data.get('data'),list): raise SourceError('Semantic Scholar: invalid page')
            for item in data['data']:
                paper = self._paper(item.get('citingPaper',{}) if wrapped else item)
                if paper.published_at is None or paper.published_at >= since:
                    result.append(paper)
            next_offset = data.get('next')
            if next_offset is None or not data['data']: return result
            if not isinstance(next_offset,int) or next_offset <= offset or next_offset in seen:
                raise SourceError('Semantic Scholar: invalid pagination')
            seen.add(offset)
            offset = next_offset
        raise SourceError('Semantic Scholar: page limit reached; increase max_pages')

    def author_papers(self,author_id,since):
        return self._pages(f'/author/{quote(author_id,safe="")}/papers',since)

    def paper_citations(self,paper_id,since):
        return self._pages(f'/paper/{quote(paper_id,safe="")}/citations',since,True)

    def paper(self,paper_id):
        return self._paper(self._get(f'/paper/{quote(paper_id,safe="")}'))

    def paper_metrics(self,paper_ids):
        result = {}
        for paper_id in paper_ids:
            try:
                data = self._get(f'/paper/{quote(paper_id,safe="")}')
                count = data.get('citationCount')
                if not isinstance(count,int) or isinstance(count,bool) or count < 0: continue
                published = data.get('publicationDate')
                result[paper_id] = CitationMetric(count,date.fromisoformat(published) if published else None,datetime.now(timezone.utc))
            except (SourceError,ValueError):
                continue  # An unavailable metric stays unknown; discovery can proceed.
        return result
